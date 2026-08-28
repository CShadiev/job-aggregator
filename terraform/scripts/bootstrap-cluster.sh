#!/usr/bin/env bash
# Idempotent cluster bootstrap.
#
# Owns installation of CRDs that Helm releases and in-cluster Terraform
# resources (environments/cluster-services) depend on already existing.
# Terraform stops at the cluster edge — this script is what stands
# between "cluster exists" (environments/dev) and "cluster has the
# CRDs its workloads assume" (environments/cluster-services).
#
# Documented `up` sequence, run identically by CI and local operators:
#   1. terraform apply   (environments/dev)             — creates the cluster
#   2. ./scripts/bootstrap-cluster.sh                    — this script
#   3. terraform apply   (environments/cluster-services) — Helm releases, Gateway/HTTPRoute, etc.
#
# Safe to re-run on every deploy: `kubectl apply` is idempotent, and this
# script does nothing destructive.
set -euo pipefail

# Single source of truth for versions — bump here, nowhere else.
# NOTE: TRAEFIK_CHART_VERSION and CERT_MANAGER_VERSION must stay in
# lockstep with the `version` pinned on the helm_release.traefik /
# helm_release.cert_manager resources in cluster-services' main.tf. Two
# places agreeing on one version is a known small seam in splitting
# CRD-install (script) from release-install (Terraform) — acceptable
# for now, worth revisiting if it ever causes real drift.
GATEWAY_API_VERSION="v1.6.1"
TRAEFIK_CHART_VERSION="41.2.0"
CERT_MANAGER_VERSION="v1.21.1"

# Must match the cluster name Terraform creates (see environments/dev's
# `${var.environment}-cluster`). Override via env var if you ever run
# this against a differently-named environment.
EXPECTED_CLUSTER_NAME="${EXPECTED_CLUSTER_NAME:-dev-cluster}"

# Explicit, not ambient: resolve the kubeconfig into a scoped temp file
# rather than relying on (or mutating) whatever context a developer's or
# CI runner's ~/.kube/config already happens to point at. This is the
# fix for the "wrong cluster, no warning" hazard — the ambient-context
# approach used interactively earlier in this project was fine for one
# person on one machine, but isn't something CI should ever inherit.
KUBECONFIG_PATH="$(mktemp -d)/kubeconfig-bootstrap"
trap 'rm -rf "$(dirname "${KUBECONFIG_PATH}")"' EXIT

echo "==> Resolving kubeconfig explicitly for cluster: ${EXPECTED_CLUSTER_NAME}"
doctl kubernetes cluster kubeconfig show "${EXPECTED_CLUSTER_NAME}" > "${KUBECONFIG_PATH}"
export KUBECONFIG="${KUBECONFIG_PATH}"

echo "==> Verifying kubeconfig context matches expected cluster"
CURRENT_CONTEXT="$(kubectl config current-context)"
if [[ "${CURRENT_CONTEXT}" != *"${EXPECTED_CLUSTER_NAME}"* ]]; then
  echo "ERROR: resolved context '${CURRENT_CONTEXT}' does not match expected cluster '${EXPECTED_CLUSTER_NAME}'." >&2
  echo "Aborting rather than risk applying CRDs to the wrong cluster." >&2
  exit 1
fi
echo "    OK: context '${CURRENT_CONTEXT}' matches."

echo "==> Installing Gateway API CRDs (${GATEWAY_API_VERSION}, standard channel)"
# --server-side is non-negotiable: these CRDs are large enough that
# client-side apply exceeds the 256 KB kubectl.kubernetes.io/last-applied-
# configuration annotation limit and fails outright.
#
# --field-manager gives THIS script a fixed, explicit identity for
# Server-Side Apply's per-field ownership tracking, instead of letting
# kubectl assign a default that can vary by invocation. Re-running this
# script later will consistently be recognized as the same manager.
#
# --force-conflicts is required the first time these CRDs are applied
# under this field-manager identity, if anything else (an earlier manual
# apply, a prior experiment, etc.) already owns these fields under a
# DIFFERENT manager name. Safe here: these are the standard, vendored
# CRD definitions — there's no bespoke customization we'd be clobbering.
kubectl apply --server-side=true --force-conflicts=true \
  --field-manager=bootstrap-cluster-script \
  -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"

echo "==> Verifying installed CRDs"
kubectl get crd | grep 'gateway.networking.k8s.io'

echo "==> Adding/updating Traefik chart repo"
helm repo add traefik https://traefik.github.io/charts > /dev/null 2>&1 || true
helm repo update traefik > /dev/null

echo "==> Installing/updating Traefik's own CRDs (chart ${TRAEFIK_CHART_VERSION})"
# Traefik-specific CRDs (Middleware, IngressRoute, etc.) — distinct from
# the generic Gateway API CRDs above. Recent chart versions stopped
# auto-installing these via Helm's own crds/ mechanism; they now require
# this same explicit, server-side apply pattern.
helm show crds traefik/traefik --version "${TRAEFIK_CHART_VERSION}" | \
  kubectl apply --server-side=true --force-conflicts=true \
    --field-manager=bootstrap-cluster-script -f -

echo "==> Installing cert-manager CRDs (${CERT_MANAGER_VERSION})"
# Same chicken-and-egg problem as Gateway API CRDs (see ADR 0001): the
# cluster-services stack declares a ClusterIssuer via kubernetes_manifest,
# which needs the CRD's schema to exist before that stack is ever planned.
# Letting the Helm chart install its own CRDs (crds.enabled=true) would put
# them back inside the same apply that consumes them — exactly what ADR 0001
# moved out of Terraform for Traefik/Gateway API. This is the upstream-blessed
# procedure too: https://cert-manager.io/docs/installation/helm/.
kubectl apply --server-side=true --force-conflicts=true \
  --field-manager=bootstrap-cluster-script \
  -f "https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.crds.yaml"

echo "==> Verifying installed CRDs"
kubectl get crd | grep 'cert-manager.io'

echo "==> Bootstrap complete."