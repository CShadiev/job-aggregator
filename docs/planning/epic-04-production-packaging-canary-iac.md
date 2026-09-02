# Epic 4: Production Packaging, Canary Deployments & Infrastructure as Code

**Status:** Planned  
**Prerequisites:** Epic 1, Epic 2, Epic 3  
**Scope:** Cloud infrastructure with Terraform, automated CD pipeline, canary deployments with automated rollback on SLO breaches, autoscaling, and Architecture Decision Records (ADRs).  
**Demonstrable Outcome:** A fully automated production deployment pipeline with a recorded artifact demonstrating an automatic canary rollback on a faulty release, backed by documented infrastructure and senior-level ADRs.

---

## 1. Problem Statement & Motivation

1. **Silent Ranking & Performance Regressions:** LLM and search systems can degrade silently (e.g., increased latency, degraded retrieval accuracy, higher error rates). Deploying changes directly to 100% of traffic carries unacceptable risk.
2. **Reproducibility & Teardown Costs:** Hosting search clusters and LLM services in the cloud without codified infrastructure leads to configuration drift and unexpected hosting bills. Infrastructure must be strictly versioned and tear down cleanly with one command.
3. **Engineering Rigor & Defensibility:** A senior-level project is judged not just by whether it runs, but by how architecture trade-offs (e.g. OpenSearch vs. Elasticsearch licensing, CRD ordering, deployment strategies) were evaluated and recorded.

---

## 2. Vertical Slice Deliverables

### A. Infrastructure as Code (Terraform)
- **Modular Terraform Architecture:**
  - `modules/compute`: Managed Kubernetes (e.g., DigitalOcean DOKS or lightweight managed container service), node pools, and autoscaling config.
  - `modules/networking`: Load balancer, Ingress/Gateway API, DNS, and automated TLS (cert-manager / Let's Encrypt).
  - `modules/storage`: Managed MongoDB Atlas / S3-compatible object storage connection.
- **Reproducibility & Lifecycle:**
  - Remote state management with locking.
  - Documented `Makefile` targets for predictable bootstrap and one-command teardown (`make infra-up`, `make infra-down`).

### B. Continuous Delivery & Canary Deployments
- **Automated CD Workflow (`.github/workflows/cd.yml`):**
  - Triggers on merge to `main` following successful CI quality gate.
  - Builds and pushes signed container image to container registry.
  - Triggers automated progressive delivery rollout.
- **Canary Release Automation (Argo Rollouts):**
  - Progressive traffic shifting (e.g., 10% $\rightarrow$ 25% $\rightarrow$ 50% $\rightarrow$ 100%).
  - `AnalysisTemplate` querying Prometheus metrics during the canary phase:
    - Metric 1: Request error rate ($< 1\%$).
    - Metric 2: p95 API latency ($< 200\text{ms}$).
    - Metric 3: Retrieval smoke check success rate.
  - Automatic rollback on metric threshold violations without human intervention.

### C. Chaos & Rollback Verification Artifact
- **Automated Rollback Simulation:**
  - Scripted chaos test deploying a deliberately degraded release (e.g., injected 500ms sleep or artificial error rate).
  - Observe Argo Rollouts detecting the SLO violation, aborting the release, and rolling back traffic to the stable revision.
  - Record a concise proof artifact (e.g., terminal/dashboard recording or log dump) showcasing the automatic recovery.

### D. Autoscaling & Operational Hardening
- **Horizontal Pod Autoscaling (HPA):**
  - Configure HPA for the API deployment based on CPU utilization and custom Prometheus request metrics.
- **Worker Scaling:**
  - Configure pipeline worker to run as a Kubernetes `CronJob` or scale-to-zero when idle between batch processing cycles.

### E. Architecture Decision Records (ADRs) & Documentation
- **6–8 Focused ADRs in `docs/adr/`:**
  - *ADR 0001: Gateway API CRD Installation & Terraform Boundary* (already drafted).
  - *ADR 0002: Self-Hosted OpenSearch vs. Elasticsearch Enterprise Licensing for RRF*.
  - *ADR 0003: Ingestion Embedding Strategy & Asymmetric Vector Search*.
  - *ADR 0004: Progressive Canary Deployments vs. Blue-Green*.
  - *ADR 0005: Mongo Checkpointing vs. Stateless Ephemeral LangGraph Workers*.
  - *ADR 0006: In-Cluster Prometheus vs. Fully Managed SaaS Observability*.
- **Comprehensive Runbook & Live Demo Script:**
  - 5-minute interactive walkthrough covering search, RAG, metrics dashboards, and canary deployment.

---

## 3. Step-by-Step Execution Plan

| Step | Task | Deliverable |
| --- | --- | --- |
| **4.1** | Terraform compute & network modules | `terraform/` configurations for cluster, ingress, TLS, and storage. |
| **4.2** | Deployment manifests & Helm charts | Kubernetes manifests for API, worker, OpenSearch, and HPA. |
| **4.3** | Automated CD with Argo Rollouts | GitHub Actions CD workflow + Argo Rollouts `AnalysisTemplate`. |
| **4.4** | Chaos rollback verification | Run chaos test, trigger auto-rollback, capture proof artifact. |
| **4.5** | ADR documentation & demo guide | 6–8 ADRs in `docs/adr/`, updated `README.md`, 5-minute demo script. |

---

## 4. Acceptance Criteria & Verification

- [ ] `terraform apply` stands up the complete cloud environment; `terraform destroy` successfully tears down all resources.
- [ ] Merging a PR into `main` automatically builds a Docker image and initiates a canary rollout on the cluster.
- [ ] Deploying a build with an injected fault triggers an automatic rollback within 60 seconds, leaving the stable version serving 100% of traffic.
- [ ] Under simulated load (k6), HPA scales the API deployment from baseline to target replicas and scales back down when traffic subsides.
- [ ] All 6+ ADRs are committed and cross-referenced in the repository documentation.
