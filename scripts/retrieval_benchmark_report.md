# Retrieval Benchmark Report — {dataset_version}

- Timestamp: {timestamp}
- Dataset version: {dataset_version}
- Queries: {n_queries}
- Corpus size: {n_corpus}
- Label source: {label_source}

## Headline Metrics

| Mode | nDCG@10 | Recall@10 | MRR |
|---|---|---|---|
{headline_table}

## Multi-Cutoff Evaluation

| Mode | nDCG@5 | nDCG@10 | nDCG@20 | Recall@5 | Recall@10 | Recall@20 | MRR |
|---|---|---|---|---|---|---|---|
{cutoff_table}

## Metrics Description & Interpretation Guide

### 1. nDCG@K (Normalized Discounted Cumulative Gain)
- **What it measures:** Overall ranking quality taking into account both **graded relevance** and **position**. It evaluates whether the most relevant jobs appear at the top of search results.
- **How it works:**
  - Each retrieved document earns a relevance gain: $\text{{gain}} = 2^{{\text{{grade}}}} - 1$ (where grades are 0 to 3).
  - Gains are discounted logarithmically based on their rank: $\text{{discount}} = \log_2(\text{{rank}} + 1)$.
  - Discounted Cumulative Gain: $\text{{DCG}}@K = \sum_{{i=1}}^{{K}} \frac{{2^{{\text{{grade}}_i}} - 1}}{{\log_2(i + 1)}}$.
  - Normalized by Ideal DCG (the score if documents were perfectly sorted by grade): $\text{{nDCG}}@K = \frac{{\text{{DCG}}@K}}{{\text{{IDCG}}@K}}$.
- **Scale:** $0.0$ to $1.0$ (where $1.0$ is an ideal, perfectly ordered ranking).
- **Interpretation:**
  - **nDCG@10** is the primary benchmark metric for retrieval quality.
  - A higher nDCG score indicates that Grade 3 (strong match) and Grade 2 (relevant match) postings are concentrated in top positions rather than buried under marginal or irrelevant listings.
  - **Benchmark Goal:** The hybrid search engine targets $\ge 15\%$ relative improvement in nDCG@10 over single-modality baselines (BM25 or k-NN).

### 2. Recall@K (Coverage / Gating Sensitivity)
- **What it measures:** The fraction of all known relevant documents (grade $\ge 1$) that are captured within the top-$K$ retrieved candidates.
- **Formula:**
  $$\text{{Recall}}@K = \frac{{|\text{{retrieved}}_{{1..K}} \cap \text{{relevant}}|}}{{|\text{{relevant}}|}}$$
- **Scale:** $0.0$ to $1.0$ ($0\%$ to $100\%$).
- **Interpretation:**
  - In retrieval gating (`build_pairs`), high recall ensures viable jobs are not prematurely discarded before downstream LLM screening and assessment.
  - **Recall@20** reflects candidate gating capacity when $K=20$. A Recall@20 of $0.85$ means $85\%$ of all viable roles were passed to downstream assessment.
  - Comparing Recall@5, Recall@10, and Recall@20 demonstrates how candidate coverage expands as the gating window widens.

### 3. MRR (Mean Reciprocal Rank)
- **What it measures:** How quickly the retrieval engine returns the very first relevant document.
- **Formula:**
  $$\text{{MRR}} = \frac{{1}}{{|Q|}} \sum_{{q \in Q}} \frac{{1}}{{\text{{rank}}_{{\text{{first relevant}}}}}}$$
  (Evaluates to $0$ if no relevant document is retrieved within the evaluated window).
- **Scale:** $0.0$ to $1.0$.
- **Interpretation:**
  - An MRR of $1.0$ means that for every query, the top retrieved result ($\text{{rank}} = 1$) was relevant.
  - An MRR of $0.50$ means the first relevant result appears at rank 2 on average.
  - High MRR indicates rapid discovery of relevant positions.

## Ground Truth Relevance Scale (Q8)

Ground truth judgments are assigned on a 4-tier relevance scale:
- **Grade 3 (Highly Relevant / Good Fit):** ATS score $\ge 80$. Close alignment with core role title, required technical stack, and responsibilities.
- **Grade 2 (Relevant / Moderate Fit):** ATS score $60$–$79$. Solid match with minor technology, domain, or experience gaps.
- **Grade 1 (Marginally Relevant / Screened Through):** ATS score $< 60$, but passed screening stage as worth evaluating.
- **Grade 0 (Irrelevant / Dropped):** Screened out, failed ATS thresholds, or completely off-topic roles.

## Retrieval Modalities

- **`bm25` (Lexical Search):** OpenSearch Okapi BM25 full-text search over job `title` and HTML-stripped `description`. Excels at exact keywords, frameworks, and company names.
- **`knn` (Dense Vector Search):** Approximate k-NN search using 1536-dimensional `text-embedding-3-small` vectors and cosine similarity. Excels at semantic context, synonyms, and generalized role descriptions.
- **`hybrid` (Reciprocal Rank Fusion - RRF):** Application-level rank fusion combining BM25 and k-NN rank lists:
  $$\text{{RRF}}(d) = \sum_{{m \in \{{\text{{bm25}}, \text{{knn}}\}}}} \frac{{1}}{{60 + \text{{rank}}_m(d)}}$$
  Combines keyword precision with semantic coverage.
