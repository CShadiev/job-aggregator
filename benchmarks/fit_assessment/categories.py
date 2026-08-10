"""Map ATS match scores to categorical fit bands."""

from enum import StrEnum


class FitCategory(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    GOOD = "good"


_CATEGORY_ORDER = (FitCategory.LOW, FitCategory.MODERATE, FitCategory.GOOD)

_ADJACENT: dict[FitCategory, frozenset[FitCategory]] = {
    FitCategory.LOW: frozenset({FitCategory.MODERATE}),
    FitCategory.MODERATE: frozenset({FitCategory.LOW, FitCategory.GOOD}),
    FitCategory.GOOD: frozenset({FitCategory.MODERATE}),
}


def score_to_category(score: float) -> FitCategory:
    """Map ATS score in [0, 100] to low / moderate / good.

    Boundaries: ``50.0`` and ``70.0`` belong to the higher band.
    """
    if score < 50:
        return FitCategory.LOW
    if score < 70:
        return FitCategory.MODERATE
    return FitCategory.GOOD


def is_adjacent(gold: FitCategory, pred: FitCategory) -> bool:
    """Return True if *pred* equals *gold* or an immediate neighbor band."""
    return pred == gold or pred in _ADJACENT[gold]


def category_order() -> tuple[FitCategory, ...]:
    return _CATEGORY_ORDER
