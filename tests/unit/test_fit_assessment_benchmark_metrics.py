"""Unit tests for fit-assessment benchmark category and metric helpers."""

import pytest

from benchmarks.fit_assessment.categories import FitCategory, score_to_category
from benchmarks.fit_assessment.metrics import (
    ERROR_LABEL,
    adjacent_accuracy,
    confusion_matrix,
    exact_accuracy,
    per_class_prf,
)


class TestScoreToCategory:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.0, FitCategory.LOW),
            (49.999, FitCategory.LOW),
            (50.0, FitCategory.MODERATE),
            (69.999, FitCategory.MODERATE),
            (70.0, FitCategory.GOOD),
            (100.0, FitCategory.GOOD),
        ],
    )
    def test_boundaries(self, score: float, expected: FitCategory):
        assert score_to_category(score) is expected


class TestExactAccuracy:
    def test_all_correct(self):
        gold = [FitCategory.LOW, FitCategory.MODERATE, FitCategory.GOOD]
        pred: list[FitCategory | None] = list(gold)
        assert exact_accuracy(gold, pred) == 1.0

    def test_none_never_matches(self):
        gold = [FitCategory.LOW, FitCategory.MODERATE]
        pred = [None, FitCategory.MODERATE]
        assert exact_accuracy(gold, pred) == 0.5

    def test_empty(self):
        assert exact_accuracy([], []) == 0.0

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            exact_accuracy([FitCategory.LOW], [])


class TestAdjacentAccuracy:
    def test_exact_and_neighbors(self):
        gold = [
            FitCategory.LOW,
            FitCategory.LOW,
            FitCategory.LOW,
            FitCategory.MODERATE,
        ]
        pred = [
            FitCategory.LOW,  # exact
            FitCategory.MODERATE,  # adjacent
            FitCategory.GOOD,  # not adjacent
            None,  # error
        ]
        assert adjacent_accuracy(gold, pred) == 0.5


class TestConfusionMatrix:
    def test_with_error_column(self):
        gold = [FitCategory.LOW, FitCategory.MODERATE, FitCategory.GOOD]
        pred = [FitCategory.LOW, None, FitCategory.MODERATE]
        matrix = confusion_matrix(gold, pred)
        assert matrix["low"]["low"] == 1
        assert matrix["moderate"][ERROR_LABEL] == 1
        assert matrix["good"]["moderate"] == 1
        assert ERROR_LABEL in matrix["low"]

    def test_without_error_column(self):
        gold = [FitCategory.LOW]
        pred: list[FitCategory | None] = [FitCategory.LOW]
        matrix = confusion_matrix(gold, pred)
        assert ERROR_LABEL not in matrix["low"]


class TestPerClassPrf:
    def test_perfect(self):
        gold = [FitCategory.LOW, FitCategory.MODERATE, FitCategory.GOOD]
        pred: list[FitCategory | None] = list(gold)
        metrics = per_class_prf(gold, pred)
        for cls in FitCategory:
            assert metrics[cls]["precision"] == 1.0
            assert metrics[cls]["recall"] == 1.0
            assert metrics[cls]["f1"] == 1.0
            assert metrics[cls]["support"] == 1.0

    def test_none_counts_as_false_negative(self):
        gold = [FitCategory.GOOD, FitCategory.GOOD]
        pred: list[FitCategory | None] = [FitCategory.GOOD, None]
        metrics = per_class_prf(gold, pred)
        assert metrics[FitCategory.GOOD]["recall"] == 0.5
        assert metrics[FitCategory.GOOD]["support"] == 2.0
