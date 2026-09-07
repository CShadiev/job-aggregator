"""Compare BM25 / k-NN / hybrid retrieval gating against frozen candidate benchmark."""

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
    fitting_recall_at_k,
    gating_reduction_rate,
    good_recall_at_k,
    llm_calls_saved,
    mean_reciprocal_rank,
    moderate_recall_at_k,
    naive_recall_at_k,
    ndcg_at_k,
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
_KS = (20, 50, 90, 100, 150)


async def run_benchmark(
    dataset: RetrievalDataset,
    reports_dir: Path,
    ks: tuple[int, ...] = _KS,
) -> dict:
    """Run retrieval gating evaluation comparing BM25, k-NN, and hybrid retrieval modes.

    Args:
        dataset: RetrievalDataset containing candidate query, corpus, and relevance labels.
        reports_dir: Directory where JSON and markdown reports will be written.
        ks: Tuple of ranking cutoff depths to evaluate.

    Returns:
        Dictionary summarizing aggregated gating retrieval metrics across modes.
    """
    config = ConfigProvider.get_config()
    client = build_opensearch_client(config)
    search = SearchService(
        client,
        jobs_index=f"gating_bench_{dataset.version}".lower(),
        config=config,
    )
    try:
        await _index_corpus(search, dataset)
        candidate = dataset.candidate
        if candidate is None and dataset.queries:
            query_text = dataset.queries[0].text
            query_vector = dataset.queries[0].embedding
            username = "candidate"
        elif candidate is not None:
            query_text = candidate.query_text
            query_vector = candidate.query_vector
            username = candidate.username
        else:
            raise ValueError("Dataset does not contain candidate profile or query")

        good_uids = dataset.good_uids
        moderate_uids = dataset.moderate_uids
        fitting_uids = dataset.fitting_uids
        grades = dataset.grades()
        n_corpus = len(dataset.corpus)

        mode_metrics: dict[str, dict] = {}
        for mode in _MODES:
            hits = await search.search_jobs(
                query_text=query_text,
                query_vector=query_vector,
                filters=SearchFilters(),
                mode=mode,
                size=max(ks),
            )
            retrieved = [hit.uid for hit in hits.hits]
            m = {
                "mrr": mean_reciprocal_rank(retrieved, fitting_uids),
                "retrieved_count": len(retrieved),
            }
            for k in ks:
                m[f"naive_recall@{k}"] = naive_recall_at_k(k, n_corpus)
                m[f"good_recall@{k}"] = good_recall_at_k(retrieved, good_uids, k)
                m[f"moderate_recall@{k}"] = moderate_recall_at_k(retrieved, moderate_uids, k)
                m[f"fitting_recall@{k}"] = fitting_recall_at_k(retrieved, fitting_uids, k)
                m[f"reduction_rate@{k}"] = gating_reduction_rate(k, n_corpus)
                m[f"llm_calls_saved@{k}"] = llm_calls_saved(k, n_corpus)
                m[f"ndcg@{k}"] = ndcg_at_k(retrieved, grades, k)
            mode_metrics[mode] = m

        report = {
            "dataset_version": dataset.version,
            "candidate_username": username,
            "n_corpus": n_corpus,
            "n_fitting": len(fitting_uids),
            "n_good": len(good_uids),
            "n_moderate": len(moderate_uids),
            "n_low": len(dataset.low_uids),
            "cutoffs": list(ks),
            "metrics": mode_metrics,
            "timestamp": datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
        }
        _write_reports(reports_dir, report)
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
            job_types=doc.job_types,
            posted_at=datetime.fromisoformat(doc.posted_at.replace("Z", "+00:00")),
        )
        for doc in dataset.corpus
    ]
    await search.bulk_index_jobs(docs)


def _format_markdown_report(report: dict) -> str:
    """Format retrieval evaluation results into markdown tables."""
    headline_rows = []
    for mode in _MODES:
        m = report["metrics"][mode]
        headline_rows.append(
            f"| {mode} | {m.get('good_recall@20', 0):.4f} | "
            f"{m.get('fitting_recall@20', 0):.4f} | "
            f"{m.get('naive_recall@20', 0):.4f} | "
            f"{m.get('reduction_rate@20', 0):.1%} | "
            f"{m.get('llm_calls_saved@20', 0)} | "
            f"{m.get('mrr', 0):.4f} |"
        )

    cutoff_rows = [
        "| Mode | Cutoff (K) | Reduction Rate | LLM Calls Saved | Naive Recall | Good Recall | Moderate Recall | Total Fitting Recall | nDCG@K |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mode in _MODES:
        m = report["metrics"][mode]
        for k in report["cutoffs"]:
            cutoff_rows.append(
                f"| {mode} | {k} | {m.get(f'reduction_rate@{k}', 0):.1%} | "
                f"{m.get(f'llm_calls_saved@{k}', 0)} | "
                f"{m.get(f'naive_recall@{k}', 0):.4f} | "
                f"{m.get(f'good_recall@{k}', 0):.4f} | "
                f"{m.get(f'moderate_recall@{k}', 0):.4f} | "
                f"{m.get(f'fitting_recall@{k}', 0):.4f} | "
                f"{m.get(f'ndcg@{k}', 0):.4f} |"
            )

    if _REPORT_TEMPLATE_PATH.exists():
        template = _REPORT_TEMPLATE_PATH.read_text(encoding="utf-8")
        return template.format(
            timestamp=report["timestamp"],
            dataset_version=report["dataset_version"],
            candidate_username=report.get("candidate_username", "cshadiev"),
            n_corpus=report["n_corpus"],
            n_fitting=report["n_fitting"],
            n_good=report["n_good"],
            n_moderate=report["n_moderate"],
            n_low=report["n_low"],
            headline_table="\n".join(headline_rows),
            cutoff_table="\n".join(cutoff_rows),
        )

    lines = [
        f"# Retrieval Gating Benchmark — {report['dataset_version']}",
        "",
        f"- Candidate: {report.get('candidate_username', 'cshadiev')}",
        f"- Corpus: {report['n_corpus']}",
        f"- Fitting: {report['n_fitting']}",
        "",
        "| Mode | Good Recall@20 | Fitting Recall@20 | Naive Recall@20 | Reduction Rate | LLM Calls Saved | MRR |",
        "|---|---|---|---|---|---|---|",
        *headline_rows,
        "",
        *cutoff_rows,
    ]
    return "\n".join(lines) + "\n"


def _write_reports(reports_dir: Path, report: dict) -> None:
    """Write benchmark results as JSON and Markdown reports."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["timestamp"]
    json_path = reports_dir / f"{stamp}.json"
    md_path = reports_dir / f"{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_format_markdown_report(report), encoding="utf-8")
    log.info("Wrote retrieval gating reports to {json} and {md}", json=json_path, md=md_path)


def main() -> None:
    """CLI entrypoint for running the retrieval gating benchmark."""
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
