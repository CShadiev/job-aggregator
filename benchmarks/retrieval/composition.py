"""Compose hybrid retrieval with stored screening predictions. No LLM calls."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from monitoring.pricing import DEFAULT_RATES, PricingCache

# Luna run on the production screening prompt (constant prefix, job payload last).
# Matches the model the live environment still runs.
SCREENING_RESULTS_PATH = Path(
    "benchmarks/screening/reports/20260915_125405_gpt-5.6-luna.results.jsonl"
)
# Luna fit-assessment report. Per-call cost is the mean of this run; the corpus
# does not have per-job assessment tokens, and this plan does not re-run the model.
FIT_ASSESSMENT_REPORT_PATH = Path(
    "benchmarks/fit_assessment/reports/20260909_173301_gpt-5.6-luna.md"
)
RANKED_UIDS_PATH = Path("benchmarks/retrieval/reports/05082026_hybrid_ranked_uids.json")
COMPOSED_JSON_PATH = Path("benchmarks/retrieval/reports/05082026_composed_gate.json")
COMPOSED_MARKDOWN_PATH = Path("benchmarks/retrieval/reports/05082026_composed_gate.md")
PRODUCTION_PROMPT_SUFFIX = "agents/prompt_templates/screening.md"
SCREENING_MODEL = "gpt-5.6-luna"
ASSESSMENT_MODEL = "gpt-5.6-luna"

_PRICING = PricingCache(ttl_seconds=300.0)
_TOKEN_LINE = re.compile(r"^- (completed requests|input_tokens|output_tokens): (\d+)\s*$")


@dataclass(frozen=True)
class ScreeningRow:
    """One stored screening prediction plus its gold label."""

    job_uid: str
    cv_category: str
    worth_full_assessment_gold: bool
    predicted_keep: bool
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int


def load_screening_results(path: Path) -> tuple[dict, list[ScreeningRow]]:
    """Load the meta record and per-job rows from a screening ``.results.jsonl``."""
    meta: dict | None = None
    rows: list[ScreeningRow] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        obj = json.loads(line)
        record_type = obj.get("type")
        if record_type == "meta":
            meta = obj
            continue
        if record_type != "result":
            raise ValueError(f"{path}:{line_number} has unexpected type {record_type!r}")
        predicted = obj.get("predicted") or {}
        gold = obj["gold"]
        keep = predicted.get("worth_full_assessment")
        rows.append(
            ScreeningRow(
                job_uid=obj["job_uid"],
                cv_category=str(gold["cv_category"]),
                worth_full_assessment_gold=bool(gold["worth_full_assessment"]),
                predicted_keep=bool(keep) and obj.get("error") is None,
                input_tokens=int(predicted.get("input_tokens") or 0),
                output_tokens=int(predicted.get("output_tokens") or 0),
                cache_read_tokens=int(predicted.get("cache_read_tokens") or 0),
            )
        )
    if meta is None:
        raise ValueError(f"No meta record in {path}")
    return meta, rows


def assessment_cost_per_call(report_text: str, model: str) -> tuple[float, dict[str, int]]:
    """Mean USD per fit-assessment call from a report's token-usage lines."""
    totals = _parse_token_usage(report_text)
    rate = DEFAULT_RATES[model]
    total_usd = _PRICING.estimate_cost_usd(rate, totals["input_tokens"], totals["output_tokens"])
    completed = totals["completed requests"]
    if completed <= 0:
        raise ValueError("Fit-assessment report has no completed requests")
    return total_usd / completed, totals


def compose_gate(
    *,
    ranked_uids: list[str],
    operating_k: int,
    rows: list[ScreeningRow],
    assessment_cost_per_call_usd: float,
    screening_model: str,
) -> dict[str, float | int]:
    """Replay screening over the top-K retrieved jobs and measure the composed gate.

    A gold job is retained only when retrieval ranks it inside ``operating_k`` and
    screening predicts ``worth_full_assessment``. Screening spend is the stored
    token cost of those retrieved calls. Assessment spend is
    ``n_assessed * assessment_cost_per_call_usd``. The counterfactual is assessing
    every corpus pair and skipping both gates.
    """
    if operating_k < 1:
        raise ValueError("operating_k must be >= 1")
    if len(ranked_uids) < operating_k:
        raise ValueError(f"Ranked list has {len(ranked_uids)} uids, shorter than K={operating_k}")
    retrieved = ranked_uids[:operating_k]
    by_uid: dict[str, ScreeningRow] = {}
    for row in rows:
        if row.job_uid in by_uid:
            raise ValueError(f"Duplicate screening job_uid {row.job_uid}")
        by_uid[row.job_uid] = row
    missing = [uid for uid in retrieved if uid not in by_uid]
    if missing:
        raise ValueError(
            f"{len(missing)} ranked uids are absent from screening results, "
            f"first missing: {missing[0]}"
        )

    n_corpus = len(rows)
    retrieved_rows = [by_uid[uid] for uid in retrieved]
    assessed_uids = [row.job_uid for row in retrieved_rows if row.predicted_keep]
    good = {row.job_uid for row in rows if row.cv_category == "good"}
    fitting = {
        row.job_uid
        for row in rows
        if row.worth_full_assessment_gold or row.cv_category in {"good", "moderate"}
    }
    retrieved_set = set(retrieved)
    assessed_set = set(assessed_uids)

    screening_usd = _screening_cost_usd(retrieved_rows, screening_model)
    n_assessed = len(assessed_uids)
    assessment_usd = n_assessed * assessment_cost_per_call_usd
    composed_usd = screening_usd + assessment_usd
    assess_all_usd = n_corpus * assessment_cost_per_call_usd
    if assess_all_usd <= 0:
        raise ValueError("Assessment counterfactual cost must be positive")

    return {
        "n_corpus": n_corpus,
        "operating_k": operating_k,
        "n_retrieved": len(retrieved),
        "n_assessed": n_assessed,
        "n_good": len(good),
        "n_fitting": len(fitting),
        "reduction_rate": (n_corpus - n_assessed) / n_corpus,
        "good_recall": _recall(good, assessed_set),
        "fitting_recall": _recall(fitting, assessed_set),
        "retrieval_good_recall": _recall(good, retrieved_set),
        "retrieval_fitting_recall": _recall(fitting, retrieved_set),
        "naive_recall": n_assessed / n_corpus,
        "screening_usd": screening_usd,
        "assessment_usd": assessment_usd,
        "composed_usd": composed_usd,
        "assess_all_usd": assess_all_usd,
        "cost_reduction": (assess_all_usd - composed_usd) / assess_all_usd,
        "assessment_cost_per_call_usd": assessment_cost_per_call_usd,
    }


def compose_from_disk(
    *,
    ranked_path: Path = RANKED_UIDS_PATH,
    screening_path: Path = SCREENING_RESULTS_PATH,
    fit_report_path: Path = FIT_ASSESSMENT_REPORT_PATH,
) -> dict:
    """Build the committed composition report from the public artifacts."""
    ranked = json.loads(ranked_path.read_text(encoding="utf-8"))
    meta, rows = load_screening_results(screening_path)
    _require_luna_production_prompt(meta, screening_path)
    if ranked.get("dataset_version") != meta.get("dataset_version"):
        raise ValueError(
            "Ranked-uid dataset "
            f"{ranked.get('dataset_version')!r} does not match screening dataset "
            f"{meta.get('dataset_version')!r}"
        )
    if ranked.get("mode") != "hybrid":
        raise ValueError(f"Ranked-uid artifact mode must be hybrid, got {ranked.get('mode')!r}")
    per_call, token_totals = assessment_cost_per_call(
        fit_report_path.read_text(encoding="utf-8"), ASSESSMENT_MODEL
    )
    metrics = compose_gate(
        ranked_uids=list(ranked["ranked_uids"]),
        operating_k=int(ranked["operating_k"]),
        rows=rows,
        assessment_cost_per_call_usd=per_call,
        screening_model=str(meta["model"]),
    )
    if int(ranked["n_corpus"]) != int(metrics["n_corpus"]):
        raise ValueError(
            f"Ranked artifact n_corpus={ranked['n_corpus']} but screening results "
            f"contain {metrics['n_corpus']} rows"
        )
    return {
        "dataset_version": ranked["dataset_version"],
        "retrieval_mode": "hybrid",
        "operating_k": int(ranked["operating_k"]),
        "retrieval_ratio": ranked.get("retrieval_ratio"),
        "screening_model": meta["model"],
        "screening_prompt": meta.get("prompt_template"),
        "screening_results": screening_path.as_posix(),
        "screening_timestamp": meta.get("timestamp"),
        "fit_assessment_model": ASSESSMENT_MODEL,
        "fit_assessment_report": fit_report_path.as_posix(),
        "fit_assessment_completed": token_totals["completed requests"],
        "fit_assessment_input_tokens": token_totals["input_tokens"],
        "fit_assessment_output_tokens": token_totals["output_tokens"],
        "ranked_uids": ranked_path.as_posix(),
        "ranked_uids_timestamp": ranked.get("timestamp"),
        **metrics,
    }


def render_markdown(report: dict) -> str:
    """Render the composition report. Numbers come only from ``report``."""
    k = report["operating_k"]
    n = report["n_corpus"]
    n_assessed = report["n_assessed"]
    return "\n".join(
        [
            f"# Composed Retrieval + Screening Gate — {report['dataset_version']}",
            "",
            "Measured replay. No new model calls.",
            "",
            f"- Dataset: `{report['dataset_version']}` ({n} postings)",
            f"- Retrieval: {report['retrieval_mode']} at K={k} "
            f"(code default `PIPELINE_RETRIEVAL_RATIO={report['retrieval_ratio']}`)",
            f"- Ranked uids: `{report['ranked_uids']}`",
            f"- Screening: `{report['screening_model']}` at t=0.0 "
            f"(`{report['screening_results']}`)",
            f"- Screening prompt: `{report['screening_prompt']}`",
            "- Assessment cost: mean call from "
            f"`{report['fit_assessment_report']}` "
            f"({report['fit_assessment_input_tokens']} input / "
            f"{report['fit_assessment_output_tokens']} output tokens over "
            f"{report['fit_assessment_completed']} calls, `{report['fit_assessment_model']}` "
            "rates in `monitoring/pricing.py`)",
            "",
            "A posting reaches fit assessment only when hybrid retrieval ranks it inside "
            f"the top {k} and screening predicts `worth_full_assessment`. "
            "Good recall and fitting recall are against the full gold sets "
            f"({report['n_good']} good / {report['n_fitting']} fitting), so a miss by either gate counts.",
            "",
            "## Composed operating point",
            "",
            "| Reduction rate | Cost reduction vs assess-all | Good recall | Fitting recall | Naive recall |",
            "|---|---|---|---|---|",
            "| "
            + " | ".join(
                [
                    _pct(report["reduction_rate"]),
                    _pct(report["cost_reduction"]),
                    f"{report['good_recall']:.4f}",
                    f"{report['fitting_recall']:.4f}",
                    f"{report['naive_recall']:.4f}",
                ]
            )
            + " |",
            "",
            "## What each gate kept",
            "",
            "| Stage | Pairs remaining | Good recall | Fitting recall |",
            "|---|---|---|---|",
            f"| Corpus | {n} | 1.0000 | 1.0000 |",
            f"| After hybrid retrieval K={k} | {report['n_retrieved']} | "
            f"{report['retrieval_good_recall']:.4f} | {report['retrieval_fitting_recall']:.4f} |",
            f"| After screening t=0.0 | {n_assessed} | "
            f"{report['good_recall']:.4f} | {report['fitting_recall']:.4f} |",
            "",
            "## Cost",
            "",
            "Screening USD is the stored token cost of the retrieved calls only. "
            "Assessment USD is `n_assessed` times the mean luna fit-assessment call. "
            "The counterfactual assesses every corpus pair and pays no screening cost.",
            "",
            "| Path | USD |",
            "|---|---|",
            f"| Screen the top {k}, assess the {n_assessed} survivors | "
            f"{_usd(report['composed_usd'])} |",
            f"| — screening | {_usd(report['screening_usd'])} |",
            f"| — fit assessment | {_usd(report['assessment_usd'])} |",
            f"| Assess all {n} pairs | {_usd(report['assess_all_usd'])} |",
            f"| Assessment cost per call | {_usd(report['assessment_cost_per_call_usd'])} |",
            "",
            f"Cost reduction is `{report['cost_reduction']:.6f}` "
            f"({_pct(report['cost_reduction'])}). "
            "This is the measured composition on this corpus. "
            "It is not the historical single-gate 23% figure and not the 61% estimate.",
            "",
        ]
    )


def _require_luna_production_prompt(meta: dict, path: Path) -> None:
    model = meta.get("model")
    prompt = str(meta.get("prompt_template") or "")
    if model != SCREENING_MODEL:
        raise ValueError(f"{path} model is {model!r}, expected {SCREENING_MODEL!r}")
    if not prompt.replace("\\", "/").endswith(PRODUCTION_PROMPT_SUFFIX):
        raise ValueError(f"{path} prompt {prompt!r} is not the production screening template")


def _parse_token_usage(report_text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for line in report_text.splitlines():
        match = _TOKEN_LINE.match(line)
        if match:
            found[match.group(1)] = int(match.group(2))
    missing = {"completed requests", "input_tokens", "output_tokens"} - found.keys()
    if missing:
        raise ValueError(f"Fit-assessment report is missing token lines: {sorted(missing)}")
    return found


def _screening_cost_usd(rows: list[ScreeningRow], model: str) -> float:
    rate = DEFAULT_RATES[model]
    return sum(
        _PRICING.estimate_cost_usd(rate, row.input_tokens, row.output_tokens, row.cache_read_tokens)
        for row in rows
    )


def _recall(relevant: set[str], kept: set[str]) -> float:
    if not relevant:
        return 0.0
    return len(relevant & kept) / len(relevant)


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _usd(value: float) -> str:
    return f"${value:.6f}"
