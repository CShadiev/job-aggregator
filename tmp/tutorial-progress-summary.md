# Flagship Demo Tutorial — Resume Summary

*Generated to compress context for continuing this tutorial in a new conversation.*

## Premise

Chingiz is turning an existing personal project (a German IT job-aggregation service — LangGraph pipeline, FastAPI, MongoDB, PydanticAI agents) into a flagship portfolio piece for a Germany-focused job search, per a self-written 3-week (120h) epic plan. Two source documents underpin everything: the project's own **README** (architecture, tech stack, roadmap) and the **Epic outline** (week-by-week plan, budget, cut list, decisions).

**Format:** tutorial, not "just build it." Claude explains concepts, checks understanding via plan-output walkthroughs before applying, points to resources, and does not rush past genuinely new material — this is explicitly about building real understanding, not just shipping fastest.

**Calibration from his profile** (9y backend Python/FastAPI, AWS Developer Associate Nov 2025, IBM RAG & Agentic AI professional cert Jan 2026, prior GitHub Actions CI/CD experience at two jobs):

- **Genuinely new, go slow, full depth:** Terraform/cloud infra, Kubernetes, OpenSearch/hybrid search, Observability (OTel/Prometheus/Grafana/SLOs).  
- **Real prior background, move faster on fundamentals:** RAG concepts, CI/CD wiring.  
- **Important exception:** RAG/Agentic AI is his actual target career specialization (architecture \+ production-grade implementation) — so despite prior coursework, this area should get the **deepest** treatment of the whole project, not a light pass. Schedule is explicitly allowed to stretch here; stretch items (cross-encoder reranking, multi-turn/agentic RAG, query understanding) become worth doing rather than optional if ahead of schedule elsewhere.  
- **Timeline:** soft. \~1 month until he starts actively applying. The 3-week/120h budget is for self-discipline and reference, not a hard deadline — going over is fine, especially to protect real understanding of RAG/agentic material.  
- **If forced to cut scope:** protect RAG/agentic depth and the epic's own "never cut" list (retrieval eval harness, LLM cost metrics, ADRs) before cutting demo UI polish or canary sophistication.

## Key decisions made so far (ADR-worthy, not yet written up)

1. **MongoDB Atlas Flex tier**, not M0 — M0's 512MB limit was already tight (`failed_entries` alone was \~4GB before cleanup); Flex is $8 base \+ usage, capped $30/mo, 5GB storage, supports vector search (needed later for embeddings).  
2. **Non-HA DOKS control plane** — HA's flat fee (\~$40/mo) doesn't fit the \~$65–75/mo ceiling. Accepted trade-off for a demo project.  
3. **`destroy_all_associated_resources = true`** on the cluster — otherwise in-cluster-created LBs/PVCs (from Kubernetes `Service`/`PVC` objects) orphan and keep billing after `terraform destroy`.  
4. **Gateway API \+ Traefik, not classic Ingress / ingress-nginx.** Discovered mid-project that the community `kubernetes/ingress-nginx` project is archived (EOL announced, maintenance ended March 24, 2026); maintainers explicitly recommend migrating to Gateway API. Argo Rollouts (week 3 canary requirement) has mature official Gateway API traffic-splitting support, which derisks this choice for later.  
5. **Traefik over Cilium's built-in Gateway controller** — DOKS ships Cilium as default CNI, which already provides its own `GatewayClass` named `cilium`, discovered by surprise after installing Traefik. Kept Traefik deliberately (richer middleware ecosystem, more Gateway API mindshare) rather than switching. **Must always set `parentRefs.name: traefik-gateway` explicitly in any future `HTTPRoute`** since both GatewayClasses coexist.  
6. **"Terraform stops at the cluster edge."** CRD installation (Gateway API's and Traefik's own) lives in `scripts/bootstrap-cluster.sh`, not in Terraform — avoids the same-apply CRD/schema chicken-and-egg problem, and is run identically by CI and local operators as a documented step between the two `terraform apply`s.  
7. **Three separate Terraform root modules**, not one:  
   - `bootstrap/` — creates the remote-state Spaces bucket. Local state, applied once, ever.  
   - `environments/dev/` — DO account-level infra (VPC, DOKS cluster+node pool, DOCR registry, app storage bucket).  
   - `environments/cluster-services/` — anything needing the `kubernetes`/`helm` providers (Traefik, cert-manager next, DNS). Split specifically because HashiCorp's own docs warn against configuring `kubernetes`/`helm` providers from a resource created in the *same* apply — causes "intermittent and unpredictable errors," worst on any apply that recreates the cluster. `cluster-services` looks the cluster up via a `data "digitalocean_kubernetes_cluster"` block instead.  
8. **DOCR "starter" tier** (free) — sufficient since the project builds one image (API and pipeline worker share it, different `CMD`/entrypoint).  
9. **DNS: delegated only the subdomain `app.cshadiev.dev`** to DigitalOcean, not the whole `cshadiev.dev` domain — leaves the rest of the domain (apex, MX, other subdomains) untouched at the registrar. Confirmed resolving correctly.  
10. **`kube_config` never exposed via Terraform outputs** — it's a sensitive, computed attribute that lives in state either way, but we don't add convenience outputs for it. Cluster access goes through `doctl kubernetes cluster kubeconfig save/show` instead.
11. **cert-manager 1.21.1**, CRDs installed via `bootstrap-cluster.sh` (same chicken-and-egg reasoning as Gateway API's CRDs — see ADR 0001, now written up); the Helm release itself runs with `crds.enabled=false` so the CRDs are never fought over by two owners.
12. **ClusterIssuer proven staging-first, then flipped to prod.** Built `letsencrypt-staging` and `letsencrypt-prod` `ClusterIssuer`s side by side (HTTP-01 via `gatewayHTTPRoute` solver, pointed at `traefik-gateway/web`); validated a real cert issuance against staging's fake CA first, then switched the Traefik `Gateway`'s `cert-manager.io/cluster-issuer` annotation to `letsencrypt-prod`. `app.cshadiev.dev` now serves a real, trusted TLS cert.
13. **Gateway listeners need `namespacePolicy.from: All` explicitly.** Discovered via a temporary `whoami` test: Gateway API listeners default to same-namespace-only routes, but `traefik-gateway` lives in the `traefik` namespace while every app `HTTPRoute` lives in its own app namespace (`job-aggregator`, etc.) — without this, routes get silently rejected with `NotAllowedByListeners`.
14. **Helm (not Terraform) owns API/worker/OpenSearch**, formalized as ADR 0001's step 3/4 split. Chart lives at `charts/job-aggregator/`; deployed by hand today (`helm upgrade --install`), CI-driven starting in 1.4.
15. **`job-aggregator-secrets` is a plain `kubectl`-created Secret, never templated into `values.yaml`.** Keeps real credentials out of `--set`/Helm release history/`values.yaml` diffs entirely — created directly from `.env` via `kubectl create secret generic --from-env-file`.
16. **OpenSearch: single-node, security plugin disabled, ClusterIP-only, never behind the Gateway.** Accepted trade-off for a demo scope — revisit before any multi-tenant/internet-facing use. `discovery.type=single-node` avoids master-election hangs; heap sized to ~50% of the container memory limit, leaving room for off-heap k-NN/HNSW memory.
17. **Docker build stopgap via GitHub Actions, not local build.** The sandbox this conversation runs in has *no* Docker at all (no daemon, no socket, no CLI) — confirmed directly, not assumed. Since the real CI/CD pipeline (1.4) doesn't exist yet either, added a deliberately minimal `.github/workflows/build-docr.yml` (build + push to DOCR, tagged by commit SHA, triggered on push to `epic-flagship`, no lint/test/CD) purely to get one real image into the registry and unblock testing the chart. Meant to be absorbed or replaced by 1.4, not grown alongside it.
18. **MongoDB Atlas Flex decision (item 1) made but never executed.** `.env`'s `MONGODB_HOST` is still a local/dev-only value, not reachable from inside the cluster. Deploying the chart anyway to prove OpenSearch + the chart/probe/Gateway mechanics; API/worker are expected to fail Mongo connectivity until Atlas Flex is actually provisioned as a separate follow-up.

## Conventions established (carry forward)

- Terraform files split by convention: `versions.tf` / `provider.tf` / `variables.tf` / `main.tf` / `outputs.tf` per root module.  
- Always read `terraform plan` output and paraphrase it back before applying — a deliberate habit-building exercise, not busywork.  
- Kubernetes versions, Helm chart versions, etc. are always pinned to a literal value looked up once, **never** wired to a "latest" data source (avoids surprise upgrades showing up in unrelated `plan`s).  
- Credential env-var names are **not unified** across tools and this has already caused one real bug: `DIGITALOCEAN_TOKEN` (digitalocean provider, native API) vs `SPACES_ACCESS_KEY_ID`/`SPACES_SECRET_ACCESS_KEY` (digitalocean provider, Spaces/S3-API resources) vs `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (Terraform's generic `s3` backend, which has no idea DigitalOcean exists).  
- `.dockerignore` \+ multi-stage, non-root, digest-pinned Dockerfile (`ARG PYTHON_DIGEST`, `UV_PYTHON_PREFERENCE=only-system` so uv doesn't fetch a managed interpreter whose symlink breaks across build stages).  
- CORS wildcard+credentials bug (`allow_origins=["*"]` \+ `allow_credentials=True`) identified and fixed with a real allowlist — Starlette's `CORSMiddleware` echoes the request's `Origin` header when this combination is set, rather than failing safe.  
- All API keys/secrets rotated after discovering `.env` had been baked into previously-pushed GHCR image layers (no `.dockerignore` existed at the time). Note: GHCR packages default to **private** regardless of repo visibility (corrected an earlier overclaim mid-conversation) — rotated anyway as cheap insurance.  
- Pydantic (`BaseModel.model_validate(os.environ)`, not `BaseSettings`) coerces `list[str]` from an env var only if the value is valid JSON array syntax; recommended a `field_validator(mode="before")` to also accept comma-separated values for friendlier `.env` authoring.  
- Server-Side Apply field-manager conflicts are resolved with an explicit, fixed `--field-manager` name (`bootstrap-cluster-script`) plus `--force-conflicts` — real conflict was hit once (manager `c3`, cause likely a stale local kubeconfig context after a cluster destroy/recreate, not the script itself, which resolves kubeconfig explicitly and ephemerally via `doctl kubernetes cluster kubeconfig show` rather than touching `~/.kube/config`).

## Current file structure

Dockerfile                      \# multi-stage, non-root, ARG-pinned digest

.dockerignore

main.py                         \# `/health` endpoint, `root_path` wired from config

.github/workflows/

  docker-publish.yml            \# original GHCR publish, tag-triggered

  build-docr.yml                \# NEW stopgap: build \+ push to DOCR, sha-tagged, push-to-`epic-flagship`-triggered

charts/

  job-aggregator/

    Chart.yaml, values.yaml

    templates/

      \_helpers.tpl, api-deployment.yaml, api-service.yaml, api-httproute.yaml,

      worker-deployment.yaml, opensearch-statefulset.yaml, opensearch-service.yaml

docs/

  adr/0001-gateway-api-crd-installation.md   \# formally written up

scripts/

  bootstrap-cluster.sh           \# Gateway API \+ Traefik \+ cert-manager CRDs, explicit kubeconfig \+ cluster guard

terraform/

  .gitignore

  bootstrap/

    versions.tf provider.tf variables.tf main.tf outputs.tf

    terraform.tfvars.example

  environments/

    dev/

      versions.tf provider.tf variables.tf main.tf outputs.tf

      generate-backend-config.sh

    cluster-services/

      versions.tf provider.tf variables.tf main.tf

      generate-backend-config.sh, terraform.tfvars (acme\_email)

## What's confirmed working right now

- Remote state: `flagship-tf-state` Spaces bucket (bootstrap), three state keys in use (bootstrap's own local state \+ `dev/terraform.tfstate` \+ `cluster-services/terraform.tfstate`).  
- VPC (`dev-vpc`, `fra1`, `10.10.0.0/24`).  
- DOKS cluster `dev-cluster`: 2× `s-2vcpu-4gb` nodes, v1.36.3-do.2 pinned, auto/surge upgrade on, non-HA, registry integration on, `destroy_all_associated_resources = true`.  
- DOCR registry (starter tier) \+ Spaces app-storage bucket, both live.  
- Gateway API v1.6.1 (Standard channel) \+ cert-manager v1.21.1 CRDs installed via `scripts/bootstrap-cluster.sh`.  
- Traefik 41.2.0 installed via `helm_release`, Gateway API provider mode enabled; `GatewayClass traefik` \+ `Gateway traefik-gateway` (both `web`/`websecure` listeners, `namespacePolicy.from: All`), bound to a real DO Load Balancer.  
- cert-manager installed via `helm_release` (`crds.enabled=false`, Gateway API support on). `letsencrypt-staging` and `letsencrypt-prod` `ClusterIssuer`s created; **real TLS is live** — proved end-to-end with a temporary `whoami` Deployment/Service/HTTPRoute (created, verified, then deleted).  
- DNS: `app.cshadiev.dev` (+ wildcard) → Load Balancer IP, confirmed resolving via `dig`.  
- Helm chart `charts/job-aggregator/` written for API Deployment, worker Deployment, and OpenSearch StatefulSet (+ Services \+ API `HTTPRoute` with a `/api` prefix `URLRewrite`) — renders cleanly, resource requests/limits sized against real `kubectl describe nodes` allocatable memory.  
- `job-aggregator` namespace and `job-aggregator-secrets` Secret created on-cluster from `.env` (17 keys — confirmed key *names* only, values never printed); `S3_*` vars filled in from the existing DO Spaces account \+ the `app_storage` bucket Terraform already created; `AUTH0_*` vars added to `.env` directly by Chingiz.  
- `.github/workflows/build-docr.yml` committed and pushed to `epic-flagship` (commit `9ac175e`) to trigger a DOCR build — **run result pending confirmation.**  
- **Not yet done:** no image confirmed in DOCR yet; `helm upgrade --install` of the app chart itself hasn't run; MongoDB Atlas Flex not provisioned (API/worker expected to fail Mongo connectivity until it is).

## Immediate next step (resume here)

1. Confirm the `build-docr.yml` run succeeded (Actions tab) and note the resulting image tag (short commit SHA).  
2. Set `charts/job-aggregator/values.yaml`'s `image.tag` to that real SHA (currently a `0.1.0-manual` placeholder).  
3. `helm upgrade --install` the chart into the `job-aggregator` namespace; expect OpenSearch to come up clean, and API/worker pods to start but fail readiness/crash on Mongo connectivity (accepted, known gap).  
4. Separately: provision MongoDB Atlas Flex (decision already made, never executed) to actually close that gap.

## Not yet started

- Rest of Week 1: 1.4 (**real** CI gate \+ CD — `build-docr.yml` is a deliberate stopgap, not this; should move faster given real prior GH Actions experience), 1.5 (OTel baseline), 1.6/1.7 (OpenSearch index \+ hybrid query).  
- Week 2 (retrieval eval harness, embeddings, retrieval-gated pipeline, RAG assistant — deepest-treatment area, expect to exceed budgeted hours here deliberately) and Week 3 (observability/SLOs, autoscaling, Argo Rollouts canary, demo UI, ADRs, README) entirely.  
- Confirm the three "cheap wins" from the epic's §4 that were designed but not confirmed applied to the actual app repo: delete `workers/job_processing.py` \+ its collections; confirm the CORS fix and the `field_validator`\-based `ALLOWED_ORIGINS` change were actually committed to `config.py`/`main.py` (code was drafted in this conversation, not confirmed pushed).  
- Running ADR backlog to formally write up later: non-HA control plane; `destroy_all_associated_resources`; Gateway API over Ingress; Traefik over Cilium's built-in controller; Atlas Flex over M0 (✅ Gateway API CRD installation itself is now written up as ADR 0001); (plus the original plan's own OpenSearch-over-Elasticsearch ADR, already decided before this conversation started).

