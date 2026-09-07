"""Generate the gating retrieval benchmark dataset from screening dataset.

Extracts candidate profile from cv.pdf via PydanticAI LLM agent, generates query_text
and query_vector, and computes 1536-d vector embeddings for the 300 screening job postings.
Outputs candidate.json, corpus.jsonl, manifest.json, and baseline.json.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
from pydantic_ai import Agent, BinaryContent

from agents.model_factory import Model, ModelFactory
from config import ConfigProvider
from logger_provider import LoggerProvider
from models.users import UserProfile
from search.embeddings import EmbeddingClient
from search.text import flatten_profile, job_embedding_text, strip_html

log = LoggerProvider.get_logger()

_DIM = 1536
_DEFAULT_SCREENING_DIR = Path("benchmarks/screening/dataset/05082026")
_DEFAULT_OUTPUT_ROOT = Path("benchmarks/retrieval/dataset")


def _deterministic_unit_vector(seed: str, dim: int = _DIM) -> list[float]:
    """Generate a deterministic 1536-d unit vector from a seed string (offline/testing)."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        block = hashlib.sha256(digest + struct.pack(">I", counter)).digest()
        for i in range(0, len(block), 4):
            if len(values) >= dim:
                break
            unsigned = int.from_bytes(block[i : i + 4], "big")
            values.append((unsigned / 0xFFFFFFFF) * 2.0 - 1.0)
        counter += 1
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


async def extract_candidate_profile(
    cv_path: Path,
    *,
    model_name: str = "gpt-5.6-luna",
) -> UserProfile:
    """Extract structured UserProfile from cv.pdf using a PydanticAI LLM agent."""
    log.info(
        "Extracting UserProfile from {cv} using model {model}...", cv=cv_path, model=model_name
    )
    model = ModelFactory.get_model(Model(model_name))
    agent: Agent[None, UserProfile] = Agent(
        model=model,
        output_type=UserProfile,
        system_prompt=(
            "You are an expert technical recruiter and profile extractor. "
            "Extract the complete structured UserProfile matching the schema from the candidate CV. "
            "Ensure username is set to 'cshadiev'. "
            "Fill all required fields accurately, inferring reasonable career goals, role fit signals, "
            "and preferences based on the candidate's technical experience, target roles, and CV content."
        ),
    )
    result = await agent.run(
        [
            "Extract candidate profile from this CV for candidate Chingiz Shadiev (username 'cshadiev'):",
            BinaryContent.from_path(cv_path),
        ]
    )
    log.info(
        "Successfully extracted UserProfile for {username} with {exp} experience items",
        username=result.output.username,
        exp=len(result.output.experience),
    )
    return result.output


async def generate_dataset(
    screening_dir: Path,
    output_dir: Path,
    *,
    dataset_version: str,
    model_name: str = "gpt-5.6-luna",
    cached_profile_path: Path | None = None,
    force_extract: bool = False,
    deterministic_vectors: bool = False,
    batch_size: int = 64,
) -> Path:
    """Generate gating retrieval benchmark dataset from screening dataset.

    Args:
        screening_dir: Path to directory containing cv.pdf and entries.jsonl.
        output_dir: Path to target version directory.
        dataset_version: Version string (e.g. '05082026').
        model_name: LLM model name to use for extraction.
        cached_profile_path: Path to cached/pre-extracted UserProfile JSON.
        force_extract: If True, ignores cached profile and runs fresh LLM extraction.
        deterministic_vectors: If True, uses deterministic hashing for vectors (offline).
        batch_size: Batch size for OpenAI embedding API calls.

    Returns:
        Path to output dataset directory.
    """
    cv_path = screening_dir / "cv.pdf"
    entries_path = screening_dir / "entries.jsonl"
    if not cv_path.exists():
        raise FileNotFoundError(f"Missing CV at {cv_path}")
    if not entries_path.exists():
        raise FileNotFoundError(f"Missing screening entries at {entries_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Candidate profile extraction
    profile: UserProfile
    profile_cache_file = output_dir / "extracted_profile.json"

    if not force_extract and cached_profile_path and cached_profile_path.exists():
        log.info("Loading cached profile from {path}", path=cached_profile_path)
        profile = UserProfile.model_validate_json(cached_profile_path.read_text(encoding="utf-8"))
    elif not force_extract and profile_cache_file.exists():
        log.info("Loading previously extracted profile from {path}", path=profile_cache_file)
        profile = UserProfile.model_validate_json(profile_cache_file.read_text(encoding="utf-8"))
    else:
        profile = await extract_candidate_profile(cv_path, model_name=model_name)
        profile_cache_file.write_text(profile.model_dump_json(indent=2), encoding="utf-8")

    # 2. Candidate query formulation
    query_text = flatten_profile(profile)
    log.info(
        "Candidate query_text formulated ({len} chars): {preview}...",
        len=len(query_text),
        preview=query_text[:120],
    )

    # 3. Read screening entries
    raw_entries: list[dict[str, Any]] = []
    with entries_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                raw_entries.append(json.loads(line))
    log.info("Loaded {n} entries from screening dataset", n=len(raw_entries))

    # 4. Generate embeddings
    config = ConfigProvider.get_config()
    async with aiohttp.ClientSession() as session:
        embed_client = EmbeddingClient(
            session,
            batch_size=batch_size,
            config=config,
        )

        if deterministic_vectors:
            log.info("Generating deterministic unit vectors for candidate and corpus...")
            query_vector = _deterministic_unit_vector(query_text)
            job_texts = [
                job_embedding_text(
                    entry["job"].get("title", ""),
                    entry["job"].get("description_raw", ""),
                )
                for entry in raw_entries
            ]
            job_vectors = [_deterministic_unit_vector(t) for t in job_texts]
        else:
            log.info("Embedding candidate query vector via EmbeddingClient...")
            query_vector = await embed_client.embed_profile(profile)
            log.info("Embedding {n} corpus documents via EmbeddingClient...", n=len(raw_entries))
            job_texts = [
                job_embedding_text(
                    entry["job"].get("title", ""),
                    entry["job"].get("description_raw", ""),
                )
                for entry in raw_entries
            ]
            job_vectors = await embed_client.embed_texts(job_texts)

    # 5. Write candidate.json
    candidate_data = {
        "username": profile.username,
        "profile": profile.model_dump(mode="json"),
        "query_text": query_text,
        "query_vector": query_vector,
    }
    candidate_file = output_dir / "candidate.json"
    candidate_file.write_text(json.dumps(candidate_data, indent=2), encoding="utf-8")
    log.info("Wrote candidate artifact to {path}", path=candidate_file)

    # 6. Write corpus.jsonl
    corpus_file = output_dir / "corpus.jsonl"
    n_good = 0
    n_moderate = 0
    n_low = 0
    with corpus_file.open("w", encoding="utf-8") as fh:
        for entry, vector in zip(raw_entries, job_vectors, strict=True):
            job = entry["job"]
            gold = entry["gold"]
            category = gold.get("cv_category", "low")
            if category == "good":
                n_good += 1
            elif category == "moderate":
                n_moderate += 1
            else:
                n_low += 1

            clean_desc = strip_html(job.get("description_raw") or "")
            doc = {
                "uid": job["uid"],
                "title": job.get("title", ""),
                "description": clean_desc,
                "description_raw": job.get("description_raw", ""),
                "embedding": vector,
                "source": job.get("source", "unknown"),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "remote": bool(job.get("remote", False)),
                "url": job.get("url", ""),
                "job_types": job.get("job_types", []),
                "posted_at": job.get("posted_at", "2026-01-01T00:00:00Z"),
                "gold": gold,
            }
            fh.write(json.dumps(doc) + "\n")
    log.info("Wrote {n} corpus documents to {path}", n=len(raw_entries), path=corpus_file)

    # 7. Write manifest.json
    manifest = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_username": profile.username,
        "n_entries": len(raw_entries),
        "n_fitting": n_good + n_moderate,
        "stratification": {
            "good": n_good,
            "moderate": n_moderate,
            "low": n_low,
        },
        "positive_definition": (
            "worth_full_assessment is true (cv_category in {moderate, good}, score >= 50)"
        ),
        "source": {
            "screening_dataset": str(screening_dir),
            "cv_path": str(cv_path),
            "vector_mode": "deterministic" if deterministic_vectors else "text-embedding-3-small",
        },
    }
    manifest_file = output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Wrote dataset manifest to {path}", path=manifest_file)

    # 8. Write baseline.json
    baseline = {
        "dataset_version": dataset_version,
        "hybrid_mrr": 1.0,
        "hybrid_good_recall_at_20": 0.15,
        "hybrid_fitting_recall_at_90": 0.45,
        "hybrid_good_recall_at_150": 0.70,
        "hybrid_fitting_recall_at_150": 0.70,
    }
    baseline_file = output_dir / "baseline.json"
    baseline_file.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    log.info("Wrote baseline gates to {path}", path=baseline_file)

    return output_dir


def main() -> None:
    """CLI entrypoint for generating the gating benchmark dataset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--screening-dir",
        type=Path,
        default=_DEFAULT_SCREENING_DIR,
        help="Path to screening dataset directory containing cv.pdf and entries.jsonl",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_DEFAULT_OUTPUT_ROOT,
        help="Target benchmark dataset root directory",
    )
    parser.add_argument(
        "--dataset-version",
        default="05082026",
        help="Dataset version folder name (default: 05082026)",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.6-luna",
        help="Model name for candidate profile extraction (default: gpt-5.6-luna)",
    )
    parser.add_argument(
        "--cached-profile",
        type=Path,
        default=None,
        help="Optional path to existing UserProfile JSON to bypass LLM extraction",
    )
    parser.add_argument(
        "--force-extract",
        action="store_true",
        help="Force fresh LLM extraction of profile from cv.pdf",
    )
    parser.add_argument(
        "--deterministic-vectors",
        action="store_true",
        help="Generate deterministic unit vectors instead of calling OpenAI Embeddings API",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Embedding batch chunk size",
    )
    args = parser.parse_args()

    output_dir = args.output_root / args.dataset_version
    asyncio.run(
        generate_dataset(
            screening_dir=args.screening_dir,
            output_dir=output_dir,
            dataset_version=args.dataset_version,
            model_name=args.model,
            cached_profile_path=args.cached_profile,
            force_extract=args.force_extract,
            deterministic_vectors=args.deterministic_vectors,
            batch_size=args.batch_size,
        )
    )
    print(f"Generated gating benchmark dataset at {output_dir}")


if __name__ == "__main__":
    main()
