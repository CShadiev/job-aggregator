"""Unit tests for the retrieval benchmark dataset loader and generator."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from benchmarks.retrieval.dataset import (
    CorpusDoc,
    Query,
    load_dataset,
    resolve_dataset_dir,
)
from scripts.generate_retrieval_benchmark_dataset import (
    RawJobCandidate,
    _deterministic_unit_vector,
    _grade_job_by_rules,
    generate_dataset,
)

_COMPREHENSIVE_DIR = Path("benchmarks/retrieval/dataset/06092026_comprehensive")


def test_load_comprehensive_dataset():
    """Verify that the frozen comprehensive dataset loads and adheres to the schema."""
    assert _COMPREHENSIVE_DIR.is_dir(), "Comprehensive dataset directory must exist"
    dataset = load_dataset(_COMPREHENSIVE_DIR)

    assert dataset.version == "06092026_comprehensive"
    assert len(dataset.corpus) >= 300
    assert len(dataset.queries) == 100
    assert len(dataset.qrels) == 100

    # Verify corpus doc structure and 1536-d embeddings
    first_doc = dataset.corpus[0]
    assert isinstance(first_doc, CorpusDoc)
    assert first_doc.uid
    assert first_doc.title
    assert first_doc.description
    assert len(first_doc.embedding) == 1536

    # Verify query structure
    first_query = dataset.queries[0]
    assert isinstance(first_query, Query)
    assert first_query.query_id == "q001"
    assert len(first_query.text) > 0
    assert len(first_query.embedding) == 1536

    # Verify qrels and relevance methods
    relevant_q1 = dataset.relevant_uids("q001")
    grades_q1 = dataset.grades("q001")
    assert len(relevant_q1) > 0
    assert all(grades_q1[uid] > 0 for uid in relevant_q1)

    # Smoke subset
    smoke = dataset.smoke_subset()
    assert len(smoke.queries) == 10
    assert len(smoke.corpus) > 0


def test_resolve_dataset_dir():
    root = Path("benchmarks/retrieval/dataset")
    # Explicit version resolution
    resolved_comp = resolve_dataset_dir(root, "06092026_comprehensive")
    assert resolved_comp.name == "06092026_comprehensive"

    resolved_smoke = resolve_dataset_dir(root, "06092026")
    assert resolved_smoke.name == "06092026"

    # Default to latest version
    latest = resolve_dataset_dir(root, None)
    assert latest.is_dir()

    # Nonexistent version raises SystemExit
    with pytest.raises(SystemExit):
        resolve_dataset_dir(root, "nonexistent_version_12345")


def test_deterministic_unit_vector():
    vec1 = _deterministic_unit_vector("test seed 1")
    vec2 = _deterministic_unit_vector("test seed 1")
    vec3 = _deterministic_unit_vector("test seed 2")

    assert len(vec1) == 1536
    assert vec1 == vec2  # deterministic
    assert vec1 != vec3  # different seeds differ

    norm = math.sqrt(sum(v * v for v in vec1))
    assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_grade_job_by_rules():
    job = RawJobCandidate(
        uid="job-1",
        title="Senior Python Backend Developer (FastAPI)",
        description_raw="We are looking for a backend engineer with FastAPI, Docker, and PostgreSQL experience.",
    )

    # Strong match -> Grade 3
    grade3 = _grade_job_by_rules(
        job,
        role_terms=["python", "backend"],
        primary_tech=["fastapi", "docker"],
        secondary_tech=["postgresql"],
    )
    assert grade3 == 3

    # Moderate match -> Grade 2
    grade2 = _grade_job_by_rules(
        job,
        role_terms=["backend"],
        primary_tech=["kubernetes", "aws"],
        secondary_tech=["docker"],
    )
    assert grade2 in (1, 2)

    # Excluded term -> Grade 0
    grade0 = _grade_job_by_rules(
        job,
        role_terms=["python", "backend"],
        primary_tech=["fastapi"],
        exclude_terms=["senior"],
    )
    assert grade0 == 0


async def test_generator_deterministic_mode(tmp_path: Path):
    """Test generating a mini dataset offline in a temporary directory."""
    out_dir = tmp_path / "test_dataset"
    result_path = await generate_dataset(
        out_dir=out_dir,
        dataset_version="test_dataset",
        source="entries",
        n_queries=10,
        deterministic_vectors=True,
    )

    assert result_path == out_dir
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "corpus.jsonl").exists()
    assert (out_dir / "queries.jsonl").exists()
    assert (out_dir / "qrels.jsonl").exists()
    assert (out_dir / "baseline.json").exists()

    loaded = load_dataset(out_dir)
    assert loaded.version == "test_dataset"
    assert len(loaded.queries) == 10
    assert len(loaded.corpus) >= 100
    assert len(loaded.qrels) == 10
