"""Load a frozen retrieval dataset version from disk."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path("benchmarks/retrieval/dataset")


@dataclass(frozen=True)
class CorpusDoc:
    uid: str
    title: str
    description: str
    embedding: list[float]
    source: str = "synthetic"
    company: str = ""
    location: str = ""
    url: str = ""
    remote: bool = False
    posted_at: str = "2026-01-01T00:00:00Z"


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class RetrievalDataset:
    version: str
    path: Path
    manifest: dict[str, Any]
    corpus: list[CorpusDoc]
    queries: list[Query]
    qrels: dict[str, dict[str, int]]

    def relevant_uids(self, query_id: str) -> set[str]:
        return {uid for uid, grade in self.qrels.get(query_id, {}).items() if grade > 0}

    def grades(self, query_id: str) -> dict[str, int]:
        return dict(self.qrels.get(query_id, {}))

    def posted_at_dt(self, uid: str) -> datetime:
        for doc in self.corpus:
            if doc.uid == uid:
                return datetime.fromisoformat(doc.posted_at.replace("Z", "+00:00"))
        return datetime.fromisoformat("2026-01-01T00:00:00+00:00")

    def smoke_subset(self) -> RetrievalDataset:
        smoke_ids = set(self.manifest.get("smoke_query_ids") or [])
        if not smoke_ids:
            return self
        queries = [query for query in self.queries if query.query_id in smoke_ids]
        qrels = {qid: grades for qid, grades in self.qrels.items() if qid in smoke_ids}
        used_uids = {uid for grades in qrels.values() for uid in grades}
        corpus = [doc for doc in self.corpus if doc.uid in used_uids] or list(self.corpus)
        return RetrievalDataset(
            version=self.version,
            path=self.path,
            manifest=self.manifest,
            corpus=corpus,
            queries=queries,
            qrels=qrels,
        )


def resolve_dataset_dir(dataset_root: Path, dataset_version: str | None) -> Path:
    if not dataset_root.is_dir():
        raise SystemExit(f"Dataset root not found: {dataset_root}")
    versions = sorted(p.name for p in dataset_root.iterdir() if p.is_dir())
    if dataset_version:
        dataset_dir = dataset_root / dataset_version
        if not dataset_dir.is_dir():
            available = ", ".join(versions) if versions else "(none)"
            raise SystemExit(
                f"Dataset version {dataset_version!r} not found under {dataset_root}. "
                f"Available: {available}"
            )
        return dataset_dir
    if not versions:
        raise SystemExit(f"No dataset versions under {dataset_root}")
    return dataset_root / versions[-1]


def load_dataset(dataset_dir: Path) -> RetrievalDataset:
    manifest = json.loads((dataset_dir / "manifest.json").read_text())
    corpus = [
        CorpusDoc(**_load_jsonl_obj(line)) for line in _read_jsonl(dataset_dir / "corpus.jsonl")
    ]
    queries = [
        Query(**_load_jsonl_obj(line, allowed={"query_id", "text", "embedding"}))
        for line in _read_jsonl(dataset_dir / "queries.jsonl")
    ]
    qrels: dict[str, dict[str, int]] = {}
    for line in _read_jsonl(dataset_dir / "qrels.jsonl"):
        row = json.loads(line)
        qrels.setdefault(row["query_id"], {})[row["uid"]] = int(row["grade"])
    return RetrievalDataset(
        version=manifest.get("dataset_version", dataset_dir.name),
        path=dataset_dir,
        manifest=manifest,
        corpus=corpus,
        queries=queries,
        qrels=qrels,
    )


def _read_jsonl(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.strip()]


def _load_jsonl_obj(line: str, allowed: set[str] | None = None) -> dict[str, Any]:
    obj = json.loads(line)
    if allowed is not None:
        return {key: obj[key] for key in allowed if key in obj}
    return obj
