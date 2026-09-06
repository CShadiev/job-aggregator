"""Generate the frozen retrieval smoke dataset with deterministic 1536-d vectors."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

from benchmarks.retrieval.labels import ats_score_to_grade

_DIM = 1536
_OUT = Path("benchmarks/retrieval/dataset/06092026")

_JOBS = [
    (
        "job-py-backend",
        "Senior Python Backend Engineer",
        "FastAPI MongoDB distributed systems Python",
        "Acme",
        88,
        True,
    ),
    (
        "job-py-ml",
        "Machine Learning Engineer",
        "PyTorch NLP retrieval ranking Python embeddings",
        "VectorLabs",
        76,
        True,
    ),
    (
        "job-js-fe",
        "Frontend Engineer React",
        "React TypeScript CSS design systems",
        "PixelForge",
        55,
        True,
    ),
    (
        "job-go-plat",
        "Platform Engineer Go",
        "Kubernetes Terraform Go observability",
        "CloudNative Inc",
        82,
        True,
    ),
    (
        "job-java-be",
        "Java Backend Developer",
        "Spring Boot Kafka microservices Java",
        "LegacyBank",
        41,
        False,
    ),
    ("job-data-eng", "Data Engineer", "Spark Airflow warehouse SQL Python", "DataPipe", 71, True),
    ("job-ios", "iOS Engineer Swift", "Swift UIKit SwiftUI mobile iPhone", "AppCo", 35, False),
    (
        "job-sec",
        "Security Engineer",
        "application security threat modeling pentest",
        "ShieldSoft",
        64,
        True,
    ),
    (
        "job-rust",
        "Rust Systems Engineer",
        "Rust systems programming performance concurrency",
        "Oxidize",
        79,
        True,
    ),
    (
        "job-pm",
        "Technical Product Manager",
        "roadmap stakeholders discovery product strategy",
        "Roadmap Ltd",
        22,
        False,
    ),
    (
        "job-sre",
        "Site Reliability Engineer",
        "SRE SLOs Kubernetes incident response",
        "Uptime Corp",
        69,
        True,
    ),
    (
        "job-nlp",
        "NLP Research Engineer",
        "transformers information retrieval RAG embeddings",
        "LangWorks",
        91,
        True,
    ),
    (
        "job-qa",
        "QA Automation Engineer",
        "Playwright pytest test strategy quality",
        "QualityFirst",
        48,
        True,
    ),
    ("job-devops", "DevOps Engineer", "CI CD GitHub Actions Terraform AWS", "ShipIt", 73, True),
    (
        "job-android",
        "Android Engineer Kotlin",
        "Kotlin Jetpack Compose Android mobile",
        "DroidWorks",
        33,
        False,
    ),
    (
        "job-full",
        "Full Stack Engineer",
        "React FastAPI TypeScript Python Postgres",
        "StackAll",
        84,
        True,
    ),
    (
        "job-embed",
        "Search Relevance Engineer",
        "BM25 vector search OpenSearch hybrid ranking",
        "Findly",
        93,
        True,
    ),
    ("job-etl", "Analytics Engineer", "dbt SQL warehouse modeling looker", "Metricly", 58, True),
    (
        "job-lead",
        "Engineering Manager",
        "people leadership hiring delivery coaching",
        "PeopleFirst",
        18,
        False,
    ),
    (
        "job-gpu",
        "GPU Inference Engineer",
        "CUDA Triton model serving latency",
        "InferFast",
        67,
        True,
    ),
]

_QUERIES = [
    (
        "q01",
        "Python FastAPI backend engineer MongoDB",
        ["job-py-backend", "job-full"],
        ["job-data-eng", "job-py-ml"],
    ),
    (
        "q02",
        "machine learning PyTorch embeddings retrieval",
        ["job-py-ml", "job-nlp"],
        ["job-embed", "job-gpu"],
    ),
    ("q03", "React TypeScript frontend design systems", ["job-js-fe", "job-full"], ["job-qa"]),
    ("q04", "Kubernetes platform Go Terraform SRE", ["job-go-plat", "job-sre"], ["job-devops"]),
    ("q05", "OpenSearch hybrid BM25 vector ranking", ["job-embed", "job-nlp"], ["job-py-ml"]),
    (
        "q06",
        "Spark Airflow data engineer warehouse",
        ["job-data-eng", "job-etl"],
        ["job-py-backend"],
    ),
    ("q07", "Rust systems concurrency performance", ["job-rust"], ["job-gpu", "job-go-plat"]),
    ("q08", "application security threat modeling", ["job-sec"], ["job-sre"]),
    ("q09", "DevOps CI CD GitHub Actions AWS", ["job-devops", "job-sre"], ["job-go-plat"]),
    (
        "q10",
        "full stack React FastAPI TypeScript Python",
        ["job-full", "job-py-backend"],
        ["job-js-fe"],
    ),
]


def _unit_vector(seed: str) -> list[float]:
    """Generate a pseudo-random deterministic unit vector from a seed string."""
    digest = hashlib.sha256(seed.encode()).digest()
    values: list[float] = []
    counter = 0
    while len(values) < _DIM:
        block = hashlib.sha256(digest + struct.pack(">I", counter)).digest()
        for i in range(0, len(block), 4):
            if len(values) >= _DIM:
                break
            unsigned = int.from_bytes(block[i : i + 4], "big")
            values.append((unsigned / 0xFFFFFFFF) * 2.0 - 1.0)
        counter += 1
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def _mix(base: list[float], other: list[float], weight: float) -> list[float]:
    """Linearly interpolate and normalize two vectors."""
    mixed = [weight * a + (1.0 - weight) * b for a, b in zip(base, other, strict=True)]
    norm = math.sqrt(sum(v * v for v in mixed)) or 1.0
    return [v / norm for v in mixed]


def main() -> None:
    """Generate synthetic jobs, queries, and qrels for smoke testing and save to disk."""
    _OUT.mkdir(parents=True, exist_ok=True)
    job_vectors = {uid: _unit_vector(f"job::{uid}") for uid, *_ in _JOBS}
    corpus_lines = []
    for uid, title, description, company, _score, _worth in _JOBS:
        corpus_lines.append(
            json.dumps(
                {
                    "uid": uid,
                    "title": title,
                    "description": description,
                    "embedding": job_vectors[uid],
                    "source": "synthetic",
                    "company": company,
                    "location": "Berlin",
                    "url": f"https://example.com/{uid}",
                    "remote": True,
                    "posted_at": "2026-01-01T00:00:00Z",
                }
            )
        )
    query_lines = []
    qrel_lines = []
    job_meta = {uid: (score, worth) for uid, _t, _d, _c, score, worth in _JOBS}
    for query_id, text, primary, secondary in _QUERIES:
        primary_vec = job_vectors[primary[0]]
        query_vec = _mix(primary_vec, _unit_vector(f"query::{query_id}"), 0.82)
        query_lines.append(json.dumps({"query_id": query_id, "text": text, "embedding": query_vec}))
        graded: dict[str, int] = {}
        for uid in primary:
            score, worth = job_meta[uid]
            graded[uid] = ats_score_to_grade(score, screened_through=worth)
        for uid in secondary:
            score, worth = job_meta[uid]
            graded[uid] = min(ats_score_to_grade(score, screened_through=worth), 2)
        for uid, grade in graded.items():
            qrel_lines.append(json.dumps({"query_id": query_id, "uid": uid, "grade": grade}))

    (_OUT / "corpus.jsonl").write_text("\n".join(corpus_lines) + "\n")
    (_OUT / "queries.jsonl").write_text("\n".join(query_lines) + "\n")
    (_OUT / "qrels.jsonl").write_text("\n".join(qrel_lines) + "\n")
    manifest = {
        "schema_version": 1,
        "dataset_version": "06092026",
        "n_queries": len(_QUERIES),
        "n_corpus": len(_JOBS),
        "n_qrels": len(qrel_lines),
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": _DIM,
        "label_source": "ATS-band proxy (Q8) over a frozen synthetic split for CI; vectors are deterministic stand-ins for precomputed OpenAI embeddings (zero live API calls).",
        "smoke_query_ids": [qid for qid, *_ in _QUERIES],
        "ks": [5, 10, 20],
    }
    (_OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Conservative floor: CI fails only on real ranking regressions, not noise.
    (_OUT / "baseline.json").write_text(
        json.dumps(
            {
                "metric": "ndcg@10",
                "hybrid_ndcg_at_10": 0.35,
                "note": "Initial conservative floor for the synthetic smoke split. Tighten after a measured full run.",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote dataset to {_OUT}")


if __name__ == "__main__":
    main()
