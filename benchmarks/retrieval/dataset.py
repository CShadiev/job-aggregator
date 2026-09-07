"""Load a frozen retrieval dataset version from disk."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_ROOT = Path("benchmarks/retrieval/dataset")


@dataclass(frozen=True)
class CorpusDoc:
    """Corpus document representation containing job metadata, vector embedding, and gold labels."""

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
    job_types: list[str] = field(default_factory=list)
    description_raw: str = ""
    gold: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateQuery:
    """Candidate profile representation with text query and dense embedding vector."""

    username: str
    query_text: str
    query_vector: list[float]
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Query:
    """Evaluation query containing identifier, text query, and vector embedding."""

    query_id: str
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class RetrievalDataset:
    """Frozen retrieval benchmark dataset containing manifest, corpus, candidate profile, and relevance labels."""

    version: str
    path: Path
    manifest: dict[str, Any]
    corpus: list[CorpusDoc]
    candidate: CandidateQuery | None = None
    queries: list[Query] = field(default_factory=list)
    qrels: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def fitting_uids(self) -> set[str]:
        """Return set of job UIDs deemed fitting (worth_full_assessment=True or score >= 50)."""
        fitting: set[str] = set()
        for doc in self.corpus:
            gold = doc.gold
            if gold.get("worth_full_assessment") or gold.get("cv_category") in {"good", "moderate"}:
                fitting.add(doc.uid)
        if not fitting and self.qrels:
            # Fallback to qrels with positive grade
            for grades in self.qrels.values():
                fitting.update(uid for uid, grade in grades.items() if grade > 0)
        return fitting

    @property
    def good_uids(self) -> set[str]:
        """Return set of job UIDs with 'good' cv_category (grade 3, score >= 70)."""
        good: set[str] = set()
        for doc in self.corpus:
            if doc.gold.get("cv_category") == "good":
                good.add(doc.uid)
        if not good and self.qrels:
            for grades in self.qrels.values():
                good.update(uid for uid, grade in grades.items() if grade >= 3)
        return good

    @property
    def moderate_uids(self) -> set[str]:
        """Return set of job UIDs with 'moderate' cv_category (grade 2, score 50-69)."""
        moderate: set[str] = set()
        for doc in self.corpus:
            if doc.gold.get("cv_category") == "moderate":
                moderate.add(doc.uid)
        if not moderate and self.qrels:
            for grades in self.qrels.values():
                moderate.update(uid for uid, grade in grades.items() if grade == 2)
        return moderate

    @property
    def low_uids(self) -> set[str]:
        """Return set of job UIDs with 'low' cv_category (grade 0, score < 50)."""
        low: set[str] = set()
        for doc in self.corpus:
            if doc.gold.get("cv_category") == "low":
                low.add(doc.uid)
        return low

    def relevant_uids(self, query_id: str = "candidate") -> set[str]:
        """Return set of job UIDs with positive relevance grade for the query."""
        if query_id in self.qrels:
            return {uid for uid, grade in self.qrels[query_id].items() if grade > 0}
        return self.fitting_uids

    def grades(self, query_id: str = "candidate") -> dict[str, int]:
        """Return mapping of job UID to integer relevance grade for the query."""
        if query_id in self.qrels:
            return dict(self.qrels[query_id])
        result: dict[str, int] = {}
        for doc in self.corpus:
            cat = doc.gold.get("cv_category")
            if cat == "good":
                result[doc.uid] = 3
            elif cat == "moderate":
                result[doc.uid] = 2
            elif doc.gold.get("worth_full_assessment"):
                result[doc.uid] = 1
            else:
                result[doc.uid] = 0
        return result

    def posted_at_dt(self, uid: str) -> datetime:
        """Extract posting timestamp datetime for the specified job UID."""
        for doc in self.corpus:
            if doc.uid == uid:
                return datetime.fromisoformat(doc.posted_at.replace("Z", "+00:00"))
        return datetime.fromisoformat("2026-01-01T00:00:00+00:00")

    def smoke_subset(self) -> RetrievalDataset:
        """Return smoke subset or self if no separate smoke IDs configured."""
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
            candidate=self.candidate,
            queries=queries,
            qrels=qrels,
        )


def resolve_dataset_dir(
    dataset_root: Path = _DEFAULT_ROOT, dataset_version: str | None = None
) -> Path:
    """Resolve the specific version subdirectory within a benchmark dataset root directory."""
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
    """Load and parse manifest, corpus, candidate profile, and relevance labels from dataset directory."""
    manifest_file = dataset_dir / "manifest.json"
    if not manifest_file.exists():
        raise SystemExit(f"Missing manifest file at {manifest_file}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    corpus_file = dataset_dir / "corpus.jsonl"
    if not corpus_file.exists():
        raise SystemExit(f"Missing corpus file at {corpus_file}")

    corpus: list[CorpusDoc] = []
    with corpus_file.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            corpus.append(
                CorpusDoc(
                    uid=row["uid"],
                    title=row["title"],
                    description=row.get("description", ""),
                    embedding=row["embedding"],
                    source=row.get("source", "synthetic"),
                    company=row.get("company", ""),
                    location=row.get("location", ""),
                    url=row.get("url", ""),
                    remote=bool(row.get("remote", False)),
                    posted_at=row.get("posted_at", "2026-01-01T00:00:00Z"),
                    job_types=row.get("job_types", []),
                    description_raw=row.get("description_raw", ""),
                    gold=row.get("gold", {}),
                )
            )

    candidate: CandidateQuery | None = None
    candidate_file = dataset_dir / "candidate.json"
    queries: list[Query] = []
    qrels: dict[str, dict[str, int]] = {}

    if candidate_file.exists():
        c_data = json.loads(candidate_file.read_text(encoding="utf-8"))
        candidate = CandidateQuery(
            username=c_data.get("username", "cshadiev"),
            query_text=c_data["query_text"],
            query_vector=c_data["query_vector"],
            profile=c_data.get("profile", {}),
        )
        queries.append(
            Query(
                query_id="candidate",
                text=candidate.query_text,
                embedding=candidate.query_vector,
            )
        )
        grade_map: dict[str, int] = {}
        for doc in corpus:
            cat = doc.gold.get("cv_category")
            if cat == "good":
                grade_map[doc.uid] = 3
            elif cat == "moderate":
                grade_map[doc.uid] = 2
            elif doc.gold.get("worth_full_assessment"):
                grade_map[doc.uid] = 1
            else:
                grade_map[doc.uid] = 0
        qrels["candidate"] = grade_map

    queries_file = dataset_dir / "queries.jsonl"
    if queries_file.exists():
        queries = []
        with queries_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    q_data = json.loads(line)
                    queries.append(
                        Query(
                            query_id=q_data["query_id"],
                            text=q_data["text"],
                            embedding=q_data["embedding"],
                        )
                    )

    qrels_file = dataset_dir / "qrels.jsonl"
    if qrels_file.exists():
        qrels = {}
        with qrels_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    qr = json.loads(line)
                    qrels.setdefault(qr["query_id"], {})[qr["uid"]] = int(qr["grade"])

    return RetrievalDataset(
        version=manifest.get("dataset_version", dataset_dir.name),
        path=dataset_dir,
        manifest=manifest,
        corpus=corpus,
        candidate=candidate,
        queries=queries,
        qrels=qrels,
    )
