# Candidate–Job Ranking: Hybrid Search Design

## Motivation

Ranking job postings for a given candidate profile using a combination of vector
(semantic) search and keyword search — exploiting the natural split between
free-text fields and structured technology terms.

---

## Candidate profile structure

| Component | Description |
|---|---|
| Short description | Central role, domain(s) |
| Core stack | Programming languages and technologies |
| Experience | Short blocks describing past projects and achievements |

---

## Matching strategy per field

### Role / domain / experience → vector similarity (HNSW)

These fields have rich paraphrase structure that exact-match approaches cannot
capture. Dense embeddings + approximate nearest-neighbour search (HNSW) are the
right tool.

**Watch-out — asymmetric retrieval**: candidate experience blocks ("led
migration of monolith to microservices") and job requirement fragments ("experience
with distributed systems") are stylistically very different. Mitigations:

- Use a model that supports **instruction prefixes** (E5 / BGE-style): prepend
  `"Represent this experience:"` to the candidate side and `"Represent this job
  requirement:"` to the job side.
- Alternatively, normalize both sides to a common format with a lightweight LLM
  step before embedding.

### Core stack → keyword search (BM25)

Technology names are proper nouns — exact or near-exact matching is more
appropriate than semantic proximity. BM25 over the job's `tags` field (already
lower-cased) is the right approach.

**Watch-out — synonym variants**: `k8s` vs `kubernetes`, `js` vs `javascript`,
`pg` vs `postgresql`. Apply a canonical synonym dictionary during both indexing
and querying. The existing key-normalization agent is the natural place to enforce
tag canonicalization.

---

## Job description prerequisites

For field-level matching to work, the job side needs the same structure. Currently
`JobPosting.description_raw` is a free-text blob. The **description enrichment**
pipeline step should extract:

- Normalized role / seniority
- Required stack (already partially captured in `tags`)
- Key requirements / experience bullets

Without this, the match degrades to a structured query against an unstructured
document.

---

## Scoring and fusion

### Stack as a pre-filter (optional)

If the stack overlap falls below a minimum threshold, exclude the job before
scoring — strong role/experience similarity should not surface a job that requires
a completely different stack.

### Reciprocal Rank Fusion (RRF)

Start with RRF as the fusion technique. It is rank-based so no score normalization
across systems is needed, and it degrades gracefully.

```
semantic_score  = mean cosine(role_emb_pair)
                + max-pool cosine over (experience × requirement) cross-sim matrix

stack_score     = BM25(candidate_stack_terms, job_stack_terms)

final_score     = RRF([semantic_rank, stack_rank])
```

If multiple semantic streams are kept separate (role, domain, experience), they
can each enter RRF independently for finer-grained weight control.

---

## Two-stage pipeline (recommended for production)

| Stage | Method | Output |
|---|---|---|
| Coarse retrieval | HNSW + BM25 → RRF | Top-K candidates (cheap, fast) |
| Reranking | Cross-encoder or LLM agent | Final ranked list (high quality) |

The existing PydanticAI fit-assessment agent is a natural fit for stage 2 — apply
it only to the top-K jobs surfaced by the hybrid retriever instead of running it
on every posting. This keeps LLM cost proportional to retrieval quality rather
than total job volume.

---

## Baseline to validate first

Before investing in the full field-decomposed pipeline, embed `description_raw`
directly against a flat candidate summary and evaluate ranking quality. If the
simple baseline is already reasonable, measure how much the structured approach
actually improves it — this sets the right threshold for added complexity.

---

## Open questions

- Which embedding model? General-purpose (`text-embedding-3-large`) vs.
  domain-specific (E5, BGE). Instruction-prefix models are preferred given the
  asymmetric retrieval problem.
- Where to store embeddings? A vector store alongside the existing job DB, or an
  integrated solution (e.g. pgvector if switching to Postgres, Qdrant, Weaviate).
- Ground truth for evaluation? Human relevance labels on a small gold set, or a
  proxy (e.g. personal ranking of known jobs for a known profile).
- How often to re-embed? Candidate profile changes should trigger re-scoring;
  job embeddings can be computed once at ingestion time.
