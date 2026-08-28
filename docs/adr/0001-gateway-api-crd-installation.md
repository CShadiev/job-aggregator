# ADR 0001 — Install Gateway API CRDs from CI, not Terraform

**Status:** accepted — implementation pending (epic §5 task 1.2b)
**Date:** 2026-08-25
**Context:** epic §5 task 1.2 / 1.2b / 1.4, `terraform/environments/cluster-services/`

The *Decision* section below describes the target state. As of this ADR's date,
`cluster-services/gateway-api-crds.tf` still contains the `null_resource` it
replaces, and `scripts/bootstrap-cluster.sh` does not exist yet.

---

## Context

The Gateway API CRDs (`GatewayClass`, `Gateway`, `HTTPRoute`, …) are a SIG-Network
standard that Traefik — our chosen implementation — watches but does not own. They
have to exist in the cluster before Traefik is installed and before any
`GatewayClass` or `Gateway` object can be created.

That ordering requirement collides with how Terraform works. Terraform is
plan-then-apply against a schema it discovers **once, before anything runs**.
Installing a CRD changes the schema of the API being managed *mid-apply*, so
"install the CRD, then create a resource of that kind" cannot be expressed in a
single apply: at plan time the second thing's type does not exist yet. There is no
retry, because a plan is a commitment made before execution.

Every available approach is therefore some way of manufacturing a **phase
boundary** between "CRDs exist" and "things that need CRDs." The question is only
which mechanism, and what it costs.

The first implementation used `null_resource` + `local-exec` running
`kubectl apply --server-side=true` against a pinned release URL. It worked, and it
is in fact the procedure upstream recommends (see *Alternatives*, option D), but it
carried three problems:

1. **It lied to Terraform about ownership.** State recorded that a `null_resource`
   existed; it recorded nothing about the ~6 CRDs that landed in the cluster. No
   drift detection, no destroy, and a `terraform plan` diff whose content was
   meaningless.
2. **It bypassed the provider wiring.** Nothing in the graph connected the
   `null_resource` to `data.digitalocean_kubernetes_cluster.main`, so the command
   authenticated via whatever `kubectl config current-context` happened to be. This
   directly undercuts the reasoning in `cluster-services/provider.tf`, and its
   failure mode — silently installing CRDs into the wrong cluster and reporting
   success — is the worst kind.
3. **It made `terraform apply` require a `kubectl` binary and a live kubeconfig**,
   which is the classic works-on-my-laptop-fails-in-CI shape and rules out any
   runner image we do not control.

Points 1 and 3 were already documented as caveats in the file. Point 2 was not, and
is the one that actually decided this.

## Decision

**Terraform stops at the cluster edge. Prerequisite CRDs are installed by an
idempotent bootstrap script that CI runs before any Helm or in-cluster Terraform
work.**

Concretely:

- `terraform/environments/cluster-services/gateway-api-crds.tf` is deleted, along
  with the `null` provider requirement in that stack's `versions.tf`.
- A new `scripts/bootstrap-cluster.sh` owns CRD installation. It pins the Gateway
  API version in one place, applies with `--server-side=true` (non-negotiable: these
  CRDs are large enough that client-side apply exceeds the 256 KB
  `last-applied-configuration` annotation limit), and is safe to re-run on every
  deploy.
- The script **verifies the target cluster** before applying — it resolves the
  kubeconfig explicitly rather than inheriting the ambient context, and aborts if
  the current context does not match the expected cluster name. This is the specific
  hazard from context point 2, fixed by being explicit where Terraform was implicit.
- The CD workflow runs the script between the two Terraform stacks. Local operators
  run the same script; it is the documented `up` sequence, not a CI-only path.

The resulting order, which is now a documented pipeline sequence rather than an
implicit Terraform graph edge:

| # | Step | Owns |
|---|---|---|
| 1 | `terraform apply` in `environments/dev` | VPC, DOKS cluster, node pool, DOCR, Spaces |
| 2 | `scripts/bootstrap-cluster.sh` | Gateway API CRDs |
| 3 | `terraform apply` in `environments/cluster-services` | Traefik + cert-manager Helm releases, `GatewayClass`, `Gateway`, `ClusterIssuer` |
| 4 | `helm upgrade --install` | API, worker, OpenSearch, UI |

Teardown runs in reverse; step 1's `destroy_all_associated_resources = true` takes
the CRDs with the cluster, so there is nothing to clean up separately.

The important payoff is **step 3**. Because the CRDs now exist before that stack is
ever planned, `kubernetes_manifest` becomes legal there. We can declare
`GatewayClass`, `Gateway` and `ClusterIssuer` as real Terraform resources — with
plan diffs, drift detection and working destroy — which was impossible while CRD
installation lived inside the same apply. This decision does not just remove a wart;
it moves the Gateway objects themselves *into* proper Terraform management.

## Consequences

**Good**

- Terraform state no longer claims ownership of objects it cannot see. Every
  resource in both stacks now has a meaningful plan diff.
- The wrong-cluster failure mode is gone: cluster targeting is explicit and
  verified, and it fails loudly instead of succeeding against the wrong API server.
- `terraform apply` no longer depends on host binaries, so both stacks can run in
  any runner image, or in Terraform Cloud / Atlantis later.
- `GatewayClass` / `Gateway` / `ClusterIssuer` become first-class Terraform
  resources (see above).
- The bootstrap step is honest about being imperative, which makes it obvious where
  to add the next prerequisite CRD set (Prometheus operator, Argo Rollouts) rather
  than growing a second `null_resource`.

**Bad, and accepted**

- CRD installation is outside any state file, so **nothing detects CRD drift**. If
  someone deletes a CRD by hand, we find out when Traefik breaks. Accepted: CRDs are
  cluster-scoped infrastructure nobody edits casually, re-running the script is the
  fix, and the `null_resource` had exactly the same gap.
- Ordering is enforced by documentation and the CD workflow, not by a dependency
  graph. A human running steps out of order gets a confusing failure. Mitigated by
  the script being idempotent and step 3 failing fast and clearly when CRDs are
  absent.
- CI needs `kubectl` and `doctl`. This is a real requirement, but it moved from
  `terraform apply` (where it was surprising) to a shell script (where it is
  obvious), and CD needed cluster access for `helm upgrade` regardless.
- Two `terraform apply` invocations with a shell step wedged between them is not a
  single "one command up." A `Makefile` target wraps the sequence so the epic's
  §4 item 7 promise still holds from the operator's point of view.

## Alternatives considered

### A. `null_resource` + `local-exec` (the status quo)

**Rejected.** See *Context*. Worth being precise about which objections actually
bit, since two of the standard ones did not: `kubectl apply` is genuinely
idempotent, so the usual "provisioners aren't idempotent" complaint was moot; and
the usual "provisioners have no destroy" complaint was neutralised by
`destroy_all_associated_resources = true` on the cluster. What remained was the
ambient-credential hazard, the meaningless plan, and the host dependency.

### B. `kubernetes_manifest` (hashicorp/kubernetes)

**Rejected for installing the CRDs**, adopted for consuming them in step 3.

The comment in the deleted file justified avoiding it on the grounds that
`kubernetes_manifest` validates against the CRD schema at plan time. That reasoning
was subtly wrong: `CustomResourceDefinition` is a built-in `apiextensions.k8s.io/v1`
type present in every cluster's OpenAPI, so the resource can create a CRD without
any bootstrapping problem. The real objections are practical —
`standard-install.yaml` is a multi-document YAML that would need fetching, splitting
and `yamldecode`-ing per document, and the resource is notoriously slow and
memory-hungry on schemas as large as Gateway API's, because it materialises the
whole OpenAPI schema as typed HCL in both plan and state.

### C. `alekc/kubectl` provider

**Rejected.** Technically the best in-Terraform option: `kubectl_manifest` with
`for_each` over `kubectl_file_documents` gives real state, per-CRD plan output,
drift detection and clean destroy, without a `kubectl` binary. Rejected on
supply-chain grounds — it is a community fork of the abandoned `gavinbunney/kubectl`
provider, and taking a maintainer-risk dependency on the bootstrap-critical path to
solve a one-line problem is a bad trade for a three-week demo. Revisit if the number
of raw-YAML prerequisites grows past two or three.

### D. Helm chart for the CRDs

**Rejected — no such thing exists, deliberately.** SIG-Network has declined to ship
an official Gateway API CRD chart
([kubernetes-sigs/gateway-api#4809](https://github.com/kubernetes-sigs/gateway-api/issues/4809)),
because Helm cannot safely upgrade CRDs and because an implementation's chart must
not be able to bump your Gateway API version behind your back. Traefik removed
Gateway API CRDs from its own chart in v40.2.0 for the same reason and its docs now
instruct you to `kubectl apply` them first; Envoy Gateway ships a CRD chart but
documents `helm template … | kubectl apply --server-side -f -` rather than
`helm install`.

This is the strongest evidence that the chosen approach is not a workaround:
`kubectl apply --server-side` *is* the upstream-blessed procedure, and the only real
question was whether to hide it inside Terraform or run it honestly.

### E. GitOps (Argo CD)

**Rejected — correct architecture, wrong budget.** A reconciling controller with
retry dissolves this entire problem class: Argo CD applies YAML server-side,
refreshes its API discovery cache and retries, and sync waves
(`argocd.argoproj.io/sync-wave`) express "CRDs, then controllers, then custom
resources" as a first-class ordering primitive. `selfHeal: true` would even give us
the CRD drift detection this decision gives up.

Rejected for three reasons. It is already out of scope per epic §4. It costs 6–10 h
against a 121 h plan with zero buffer. And its footprint is a real capacity risk:
application-controller, repo-server, server and redis on 2 × 4 GB nodes that also
have to hold an OpenSearch StatefulSet with a JVM heap, `kube-prometheus-stack`, the
API, the worker and the UI. The `argocd-core` install shrinks it, but drops the web
UI, which is most of the demo-visible payoff.

Argo **Rollouts** — a different project — remains in scope and covers the epic's
canary requirement on its own.

### F. A third Terraform stack for CRDs only

**Rejected.** Would work, and would let step 3 use `kubernetes_manifest` exactly as
the chosen option does. Rejected because it pays a whole extra state file, backend
config and apply step to accomplish what a shell script does, and stack
proliferation has its own ongoing cost.

## Notes for the follow-up work

- Pin the Gateway API version in exactly one place. The deleted resource duplicated
  it between `triggers` and the URL, where a partial edit would silently bump the
  trigger without changing what got installed.
- The Argo Rollouts traffic-router story for Gateway API is
  [`argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi`](https://github.com/argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi),
  which is less mature than the nginx / Istio / Traefik integrations. Epic §5 task
  3.3 budgets 7 h with no slack; if the plugin fights back, fall back to Traefik's
  native `TraefikService` routing, or to replica-based canary with analysis and no
  traffic router at all. Deserves its own ADR when we get there.
