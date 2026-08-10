"""Map fit categories / ATS scores to binary screening gold labels."""

from benchmarks.fit_assessment.categories import FitCategory, score_to_category


def category_to_worth(category: FitCategory) -> bool:
    """True iff category is moderate or good (CV score ≥ 50)."""
    return category != FitCategory.LOW


def score_to_worth(score: float) -> bool:
    return category_to_worth(score_to_category(score))
