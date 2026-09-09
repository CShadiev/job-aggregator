"""Gating and category-agreement metrics for the fit-assessment benchmark."""

from __future__ import annotations

from benchmarks.fit_assessment.categories import (
    FitCategory,
    category_order,
    is_adjacent,
)
from benchmarks.screening.metrics import (
    fitting_recall,
    good_recall,
    llm_calls_saved,
    moderate_recall,
    n_passed,
    naive_recall,
    reduction_rate,
)

ERROR_LABEL = "error"


def exact_accuracy(gold: list[FitCategory], pred: list[FitCategory | None]) -> float:
    """Fraction of entries where prediction equals gold. ``None`` never matches."""
    if not gold:
        return 0.0
    if len(gold) != len(pred):
        raise ValueError("gold and pred must have the same length")
    correct = sum(1 for g, p in zip(gold, pred, strict=True) if p is not None and p == g)
    return correct / len(gold)


def adjacent_accuracy(gold: list[FitCategory], pred: list[FitCategory | None]) -> float:
    """Fraction where prediction equals gold or an immediate neighbor. ``None`` never matches."""
    if not gold:
        return 0.0
    if len(gold) != len(pred):
        raise ValueError("gold and pred must have the same length")
    correct = sum(1 for g, p in zip(gold, pred, strict=True) if p is not None and is_adjacent(g, p))
    return correct / len(gold)


def confusion_matrix(
    gold: list[FitCategory],
    pred: list[FitCategory | None],
) -> dict[str, dict[str, int]]:
    """Build a gold-row × predicted-col matrix.

    Predicted columns are ``low``, ``moderate``, ``good``, plus ``error`` when
    any prediction is ``None``.
    """
    if len(gold) != len(pred):
        raise ValueError("gold and pred must have the same length")

    labels = [c.value for c in category_order()]
    include_error = any(p is None for p in pred)
    cols = labels + ([ERROR_LABEL] if include_error else [])
    matrix: dict[str, dict[str, int]] = {row: {col: 0 for col in cols} for row in labels}

    for g, p in zip(gold, pred, strict=True):
        col = ERROR_LABEL if p is None else p.value
        matrix[g.value][col] += 1
    return matrix


def per_class_prf(
    gold: list[FitCategory],
    pred: list[FitCategory | None],
) -> dict[FitCategory, dict[str, float]]:
    """Per-class precision, recall, F1, and support (gold count).

    ``None`` predictions count as false negatives for the gold class and do not
    contribute true positives for any predicted class.
    """
    if len(gold) != len(pred):
        raise ValueError("gold and pred must have the same length")

    result: dict[FitCategory, dict[str, float]] = {}
    for cls in category_order():
        tp = sum(1 for g, p in zip(gold, pred, strict=True) if g == cls and p == cls)
        fp = sum(1 for g, p in zip(gold, pred, strict=True) if g != cls and p == cls)
        fn = sum(1 for g, p in zip(gold, pred, strict=True) if g == cls and p != cls)
        support = sum(1 for g in gold if g == cls)

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        result[cls] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": float(support),
        }
    return result


def passed_at_score_threshold(
    pred_scores: list[float | None],
    threshold: float,
) -> list[bool]:
    """Pass iff predicted CV score is at least *threshold*. ``None`` never passes."""
    return [score is not None and score >= threshold for score in pred_scores]


def score_threshold_sweep(
    gold_categories: list[FitCategory],
    pred_scores: list[float | None],
    thresholds: tuple[float, ...] | list[float],
) -> list[dict[str, float]]:
    """Compute cover-letter gating metrics at each CV-score cutoff in *thresholds*."""
    if len(gold_categories) != len(pred_scores):
        raise ValueError("gold and pred must have the same length")
    n_total = len(gold_categories)
    rows: list[dict[str, float]] = []
    for threshold in thresholds:
        passed = passed_at_score_threshold(pred_scores, threshold)
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
