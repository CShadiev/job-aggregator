"""Gating and binary classification metrics for the screening benchmark."""

from __future__ import annotations

from collections.abc import Sequence

from benchmarks.fit_assessment.categories import FitCategory, category_order

ERROR_LABEL = "error"


def _require_same_length(*seqs: Sequence) -> None:
    """Ensure all provided input sequences have identical lengths."""
    if len({len(s) for s in seqs}) != 1:
        raise ValueError("all input lists must have the same length")


def binary_precision_recall_f1(
    gold: list[bool],
    pred: list[bool | None],
    *,
    positive: bool = True,
) -> dict[str, float]:
    """Precision/recall/F1/support for the positive class.

    ``None`` predictions count as false negatives when gold is *positive* and
    do not contribute true positives.
    """
    _require_same_length(gold, pred)

    tp = sum(1 for g, p in zip(gold, pred, strict=True) if g is positive and p is positive)
    fp = sum(1 for g, p in zip(gold, pred, strict=True) if g is not positive and p is positive)
    fn = sum(1 for g, p in zip(gold, pred, strict=True) if g is positive and p is not positive)
    support = sum(1 for g in gold if g is positive)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "support": float(support),
    }


def binary_accuracy(gold: list[bool], pred: list[bool | None]) -> float:
    """Fraction where prediction equals gold. ``None`` never matches."""
    if not gold:
        return 0.0
    _require_same_length(gold, pred)
    correct = sum(1 for g, p in zip(gold, pred, strict=True) if p is not None and p == g)
    return correct / len(gold)


def binary_confusion_matrix(
    gold: list[bool],
    pred: list[bool | None],
) -> dict[str, dict[str, int]]:
    """Build a gold-row × predicted-col matrix.

    Rows/cols are ``true`` / ``false``, plus ``error`` when any prediction is
    ``None``.
    """
    _require_same_length(gold, pred)

    labels = ("true", "false")
    include_error = any(p is None for p in pred)
    cols = list(labels) + ([ERROR_LABEL] if include_error else [])
    matrix: dict[str, dict[str, int]] = {row: {col: 0 for col in cols} for row in labels}

    for g, p in zip(gold, pred, strict=True):
        row = "true" if g else "false"
        col = ERROR_LABEL if p is None else ("true" if p else "false")
        matrix[row][col] += 1
    return matrix


def band_binary_accuracy(
    gold_categories: list[FitCategory],
    gold_worth: list[bool],
    pred: list[bool | None],
) -> dict[str, dict[str, float]]:
    """Per gold band: n, correct, accuracy under binary mapping."""
    _require_same_length(gold_categories, gold_worth, pred)

    result: dict[str, dict[str, float]] = {}
    for cls in category_order():
        indices = [i for i, c in enumerate(gold_categories) if c == cls]
        n = len(indices)
        correct = sum(1 for i in indices if pred[i] is not None and pred[i] == gold_worth[i])
        result[cls.value] = {
            "n": float(n),
            "correct": float(correct),
            "accuracy": (correct / n) if n else 0.0,
            "binary_gold": float(gold_worth[indices[0]]) if indices else 0.0,
        }
    return result


def _mean(values: list[float]) -> float:
    """Compute arithmetic mean of a float list, returning 0.0 for empty inputs."""
    return sum(values) / len(values) if values else 0.0


def _quantile(values: list[float], q: float) -> float:
    """Linear interpolation quantile; *q* in [0, 1]. Empty → 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _is_pass(value: bool | None) -> bool:
    """True only for an explicit keep; ``None`` never passes."""
    return value is True


def _recall_for_bands(
    gold_categories: list[FitCategory],
    passed: Sequence[bool | None],
    bands: frozenset[FitCategory],
) -> float:
    """Fraction of gold entries in *bands* that passed the screening gate."""
    _require_same_length(gold_categories, passed)
    relevant = [ok for cat, ok in zip(gold_categories, passed, strict=True) if cat in bands]
    if not relevant:
        return 0.0
    return sum(1 for ok in relevant if _is_pass(ok)) / len(relevant)


def good_recall(
    gold_categories: list[FitCategory],
    passed: Sequence[bool | None],
) -> float:
    """Fraction of gold-Good entries that passed the screening gate."""
    return _recall_for_bands(gold_categories, passed, frozenset({FitCategory.GOOD}))


def moderate_recall(
    gold_categories: list[FitCategory],
    passed: Sequence[bool | None],
) -> float:
    """Fraction of gold-Moderate entries that passed the screening gate."""
    return _recall_for_bands(gold_categories, passed, frozenset({FitCategory.MODERATE}))


def fitting_recall(
    gold_categories: list[FitCategory],
    passed: Sequence[bool | None],
) -> float:
    """Fraction of gold Good ∪ Moderate entries that passed the screening gate."""
    return _recall_for_bands(
        gold_categories,
        passed,
        frozenset({FitCategory.GOOD, FitCategory.MODERATE}),
    )


def n_passed(passed: Sequence[bool | None]) -> int:
    """Count of entries that passed the screening gate."""
    return sum(1 for value in passed if _is_pass(value))


def reduction_rate(passed_count: int, n_total: int) -> float:
    """Fraction of entries dropped from downstream fit assessment."""
    if n_total <= 0:
        return 0.0
    return max(0.0, float(n_total - min(passed_count, n_total)) / n_total)


def llm_calls_saved(passed_count: int, n_total: int) -> int:
    """Number of downstream fit-assessment calls avoided."""
    return max(0, n_total - passed_count)


def naive_recall(passed_count: int, n_total: int) -> float:
    """Expected recall of a random keep-set of size ``passed_count`` from ``n_total``.

    For any positive class of size ``R``, a uniform sample of ``k`` items has
    expected recall ``min(1, k / N)``.
    """
    if n_total <= 0:
        return 0.0
    return min(1.0, float(passed_count) / float(n_total))


def cost_per_100_usd(total_usd: float, n_completed: int) -> float:
    """Normalize screening spend to USD per 100 completed entries."""
    if n_completed <= 0:
        return 0.0
    return (total_usd / n_completed) * 100.0


def passed_at_threshold(
    pred_worth: Sequence[bool | None],
    confidences: list[float | None],
    threshold: float,
) -> list[bool]:
    """Pass iff predicted keep and confidence is at least *threshold*.

    ``None`` predictions or confidences never pass. ``threshold=0.0`` matches
    raw binary keep when every keep has a recorded confidence.
    """
    _require_same_length(pred_worth, confidences)
    return [
        worth is True and conf is not None and conf >= threshold
        for worth, conf in zip(pred_worth, confidences, strict=True)
    ]


def threshold_sweep(
    gold_categories: list[FitCategory],
    pred_worth: Sequence[bool | None],
    confidences: list[float | None],
    thresholds: tuple[float, ...] | list[float],
) -> list[dict[str, float]]:
    """Compute gating metrics at each confidence cutoff in *thresholds*."""
    _require_same_length(gold_categories, pred_worth, confidences)
    n_total = len(gold_categories)
    rows: list[dict[str, float]] = []
    for threshold in thresholds:
        passed = passed_at_threshold(pred_worth, confidences, threshold)
        passed_count = n_passed(passed)
        rows.append(
            {
                "threshold": float(threshold),
                "n_passed": float(passed_count),
                "n_total": float(n_total),
                "reduction_rate": reduction_rate(passed_count, n_total),
                "llm_calls_saved": float(llm_calls_saved(passed_count, n_total)),
                "naive_recall": naive_recall(passed_count, n_total),
                "good_recall": good_recall(gold_categories, passed),
                "moderate_recall": moderate_recall(gold_categories, passed),
                "fitting_recall": fitting_recall(gold_categories, passed),
            }
        )
    return rows


def confidence_summary(
    confidences: Sequence[float | None],
    correct: list[bool | None],
    gold_categories: list[FitCategory],
) -> dict:
    """Exploratory means (and simple quantiles) overall / by correctness / by band."""
    _require_same_length(confidences, correct, gold_categories)

    paired = [(c, ok) for c, ok in zip(confidences, correct, strict=True) if c is not None]
    overall_vals = [c for c, _ in paired]
    correct_vals = [c for c, ok in paired if ok is True]
    incorrect_vals = [c for c, ok in paired if ok is False]

    by_band: dict[str, dict[str, float]] = {}
    for cls in category_order():
        band_vals = [
            conf
            for conf, cat in zip(confidences, gold_categories, strict=True)
            if conf is not None and cat == cls
        ]
        by_band[cls.value] = {
            "n": float(len(band_vals)),
            "mean": _mean(band_vals),
            "p50": _quantile(band_vals, 0.5),
        }

    return {
        "overall": {
            "n": float(len(overall_vals)),
            "mean": _mean(overall_vals),
            "p25": _quantile(overall_vals, 0.25),
            "p50": _quantile(overall_vals, 0.5),
            "p75": _quantile(overall_vals, 0.75),
        },
        "correct": {
            "n": float(len(correct_vals)),
            "mean": _mean(correct_vals),
            "p50": _quantile(correct_vals, 0.5),
        },
        "incorrect": {
            "n": float(len(incorrect_vals)),
            "mean": _mean(incorrect_vals),
            "p50": _quantile(incorrect_vals, 0.5),
        },
        "by_band": by_band,
    }
