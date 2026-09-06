"""Compare BM25 / k-NN / hybrid retrieval against a frozen gold set."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.retrieval.dataset import (
    RetrievalDataset,
    load_dataset,
    resolve_dataset_dir,
)
from benchmarks.retrieval.metrics import (
    aggregate_metrics,
    mean_reciprocal_rank,
    ndcg_at_k,
    recall_at_k,
)
from config import ConfigProvider
from logger_provider import LoggerProvider
from search.client import build_opensearch_client
from search.models import IndexedJob, SearchFilters
from search.search_service import SearchService

log = LoggerProvider.get_logger()

_DEFAULT_DATASET_ROOT = Path("benchmarks/retrieval/dataset")
_DEFAULT_REPORTS_DIR = Path("benchmarks/retrieval/reports")
_REPORT_TEMPLATE_PATH = Path(__file__).parent / "retrieval_benchmark_report.md"
_MODES = ("bm25", "knn", "hybrid")
_KS = (5, 10, 20)


async def run_benchmark(dataset: RetrievalDataset, reports_dir: Path) -> dict:
    """Run retrieval evaluation comparing BM25, k-NN, and hybrid retrieval modes over the dataset.

    Args:
        dataset: RetrievalDataset containing corpus, queries, and relevance labels.
        reports_dir: Directory where JSON and markdown reports will be written.

    Returns:
        Dictionary summarizing aggregated retrieval metrics across modes.
    """
    config = ConfigProvider.get_config()
    search = SearchService(
        build_opensearch_client(config),
        jobs_index=f"retrieval_bench_{dataset.version}".lower(),
        config=config,
    )
    try:
        await _index_corpus(search, dataset)
        mode_metrics: dict[str, dict[str, float]] = {}
        per_mode_rows: dict[str, list[dict]] = {}
        for mode in _MODES:
            rows = []
            for query in dataset.queries:
                hits = await search.search_jobs(
                    query_text=query.text,
                    query_vector=query.embedding,
                    filters=SearchFilters(),
                    mode=mode,
                    size=max(_KS),
                )
                retrieved = [hit.uid for hit in hits.hits]
                relevant = dataset.relevant_uids(query.query_id)
                grades = dataset.grades(query.query_id)
                row = {
                    "query_id": query.query_id,
                    "mrr": mean_reciprocal_rank(retrieved, relevant),
                }
                for k in _KS:
                    row[f"recall@{k}"] = recall_at_k(retrieved, relevant, k)
                    row[f"ndcg@{k}"] = ndcg_at_k(retrieved, grades, k)
                rows.append(row)
            per_mode_rows[mode] = rows
            mode_metrics[mode] = aggregate_metrics(
                [{k: v for k, v in row.items() if k != "query_id"} for row in rows]
            )
        report = {
            "dataset_version": dataset.version,
            "n_queries": len(dataset.queries),
            "n_corpus": len(dataset.corpus),
            "label_source": dataset.manifest.get(
                "label_source",
                "ATS-band proxy from historical assessments (Q8)",
            ),
            "metrics": mode_metrics,
            "timestamp": datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
        }
        _write_reports(reports_dir, report, per_mode_rows)
        return report
    finally:
        if await search._client.indices.exists(index=search.jobs_index):
            await search._client.indices.delete(index=search.jobs_index)
        await search.close()


async def _index_corpus(search: SearchService, dataset: RetrievalDataset) -> None:
    """Recreate temporary benchmark index and bulk index all corpus documents."""
    if await search._client.indices.exists(index=search.jobs_index):
        await search._client.indices.delete(index=search.jobs_index)
    await search.ensure_indices()
    docs = [
        IndexedJob(
            uid=doc.uid,
            title=doc.title,
            description=doc.description,
            embedding=doc.embedding,
            source=doc.source,
            company=doc.company,
            location=doc.location,
            url=doc.url or f"https://example.com/{doc.uid}",
            remote=doc.remote,
            posted_at=datetime.fromisoformat(doc.posted_at.replace("Z", "+00:00")),
        )
        for doc in dataset.corpus
    ]
    await search.bulk_index_jobs(docs)


def _format_markdown_report(report: dict) -> str:
    """Format retrieval evaluation results into markdown tables."""
    headline_rows = []
    cutoff_rows = []
    for mode in _MODES:
        metrics = report["metrics"][mode]
        headline_rows.append(
            f"| {mode} | {metrics.get('ndcg@10', 0):.4f} | "
            f"{metrics.get('recall@10', 0):.4f} | {metrics.get('mrr', 0):.4f} |"
        )
        cutoff_rows.append(
            f"| {mode} | {metrics.get('ndcg@5', 0):.4f} | {metrics.get('ndcg@10', 0):.4f} | {metrics.get('ndcg@20', 0):.4f} | "
            f"{metrics.get('recall@5', 0):.4f} | {metrics.get('recall@10', 0):.4f} | {metrics.get('recall@20', 0):.4f} | "
            f"{metrics.get('mrr', 0):.4f} |"
        )

    if _REPORT_TEMPLATE_PATH.exists():
        template = _REPORT_TEMPLATE_PATH.read_text(encoding="utf-8")
        return template.format(
            timestamp=report["timestamp"],
            dataset_version=report["dataset_version"],
            n_queries=report["n_queries"],
            n_corpus=report["n_corpus"],
            label_source=report["label_source"],
            headline_table="\n".join(headline_rows),
            cutoff_table="\n".join(cutoff_rows),
        )

    lines = [
        f"# Retrieval benchmark — {report['dataset_version']}",
        "",
        f"- Queries: {report['n_queries']}",
        f"- Corpus: {report['n_corpus']}",
        f"- Labels: {report['label_source']}",
        "",
        "| Mode | nDCG@10 | Recall@10 | MRR |",
        "| --- | --- | --- | --- |",
        *headline_rows,
    ]
    return "\n".join(lines) + "\n"


def _write_reports(reports_dir: Path, report: dict, per_mode_rows: dict) -> None:
    """Write benchmark results as JSON and Markdown reports."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["timestamp"]
    json_path = reports_dir / f"{stamp}.json"
    md_path = reports_dir / f"{stamp}.md"
    json_path.write_text(json.dumps({**report, "per_query": per_mode_rows}, indent=2))
    md_path.write_text(_format_markdown_report(report))
    log.info("Wrote retrieval reports to {json} and {md}", json=json_path, md=md_path)


def main() -> None:
    """CLI entrypoint for running the retrieval benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=_DEFAULT_DATASET_ROOT)
    parser.add_argument("--dataset-version", default=None)
    parser.add_argument("--reports-dir", type=Path, default=_DEFAULT_REPORTS_DIR)
    args = parser.parse_args()
    dataset_dir = resolve_dataset_dir(args.dataset_root, args.dataset_version)
    dataset = load_dataset(dataset_dir)
    report = asyncio.run(run_benchmark(dataset, args.reports_dir))
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
