"""Unit tests for screening benchmark label and metric helpers."""

import pytest

from benchmarks.fit_assessment.categories import FitCategory
from benchmarks.screening.labels import category_to_worth, score_to_worth
from benchmarks.screening.metrics import (
    ERROR_LABEL,
    band_binary_accuracy,
    binary_accuracy,
    binary_confusion_matrix,
    binary_precision_recall_f1,
    confidence_summary,
)


class TestCategoryToWorth:
    """Tests for converting fit category to binary screening worth."""

    @pytest.mark.parametrize(
        ("category", "expected"),
        [
            (FitCategory.LOW, False),
            (FitCategory.MODERATE, True),
            (FitCategory.GOOD, True),
        ],
    )
    def test_mapping(self, category: FitCategory, expected: bool):
        """Verify category to boolean worth mapping."""
        assert category_to_worth(category) is expected


class TestScoreToWorth:
    """Tests for converting ATS score to binary screening worth threshold."""

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.0, False),
            (49.9, False),
            (50.0, True),
            (69.9, True),
            (70.0, True),
            (100.0, True),
        ],
    )
    def test_boundaries(self, score: float, expected: bool):
        """Verify ATS score boundary conditions for worth threshold."""
        assert score_to_worth(score) is expected


class TestBinaryPrecisionRecallF1:
    """Tests for binary precision, recall, and F1 calculations."""

    def test_perfect_positive(self):
        """Verify metrics for perfect predictions."""
        gold = [True, True, False, False]
        pred: list[bool | None] = [True, True, False, False]
        metrics = binary_precision_recall_f1(gold, pred)
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0
        assert metrics["f1"] == 1.0
        assert metrics["support"] == 2.0

    def test_none_counts_as_false_negative(self):
        """Verify that None predictions are treated as misses."""
        gold = [True, True]
        pred: list[bool | None] = [True, None]
        metrics = binary_precision_recall_f1(gold, pred)
        assert metrics["recall"] == 0.5
        assert metrics["support"] == 2.0

    def test_always_negative_zero_precision_recall(self):
        """Verify zero precision/recall when model predicts all negative."""
        gold = [True, False, False]
        pred: list[bool | None] = [False, False, False]
        metrics = binary_precision_recall_f1(gold, pred)
        assert metrics["precision"] == 0.0
        assert metrics["recall"] == 0.0
        assert metrics["f1"] == 0.0

    def test_length_mismatch(self):
        """Verify ValueError raised on mismatched list lengths."""
        with pytest.raises(ValueError):
            binary_precision_recall_f1([True], [])


class TestBinaryAccuracy:
    """Tests for binary classification accuracy computation."""

    def test_all_correct(self):
        """Verify 100% accuracy on correct predictions."""
        gold = [True, False]
        pred: list[bool | None] = [True, False]
        assert binary_accuracy(gold, pred) == 1.0

    def test_none_never_matches(self):
        """Verify None prediction does not match gold label."""
        gold = [True, False]
        pred: list[bool | None] = [None, False]
        assert binary_accuracy(gold, pred) == 0.5

    def test_empty(self):
        """Verify 0.0 returned on empty input lists."""
        assert binary_accuracy([], []) == 0.0


class TestBinaryConfusionMatrix:
    """Tests for binary confusion matrix formatting."""

    def test_with_error_column(self):
        """Verify error column included when predictions contain None."""
        gold = [True, False, True]
        pred: list[bool | None] = [True, None, False]
        matrix = binary_confusion_matrix(gold, pred)
        assert matrix["true"]["true"] == 1
        assert matrix["true"]["false"] == 1
        assert matrix["false"][ERROR_LABEL] == 1
        assert ERROR_LABEL in matrix["true"]

    def test_without_error_column(self):
        """Verify error column omitted when no None predictions exist."""
        gold = [True]
        pred: list[bool | None] = [True]
        matrix = binary_confusion_matrix(gold, pred)
        assert ERROR_LABEL not in matrix["true"]


class TestBandBinaryAccuracy:
    """Tests for calculating accuracy per fit score band."""

    def test_per_band(self):
        """Verify accuracy broken down across low, moderate, and good bands."""
        gold_categories = [
            FitCategory.LOW,
            FitCategory.LOW,
            FitCategory.MODERATE,
            FitCategory.GOOD,
        ]
        gold_worth = [False, False, True, True]
        pred: list[bool | None] = [False, True, True, None]
        bands = band_binary_accuracy(gold_categories, gold_worth, pred)
        assert bands["low"]["n"] == 2.0
        assert bands["low"]["correct"] == 1.0
        assert bands["low"]["accuracy"] == 0.5
        assert bands["low"]["binary_gold"] == 0.0
        assert bands["moderate"]["accuracy"] == 1.0
        assert bands["moderate"]["binary_gold"] == 1.0
        assert bands["good"]["correct"] == 0.0
        assert bands["good"]["accuracy"] == 0.0


class TestConfidenceSummary:
    """Tests for model confidence distribution analysis."""

    def test_overall_and_by_correctness(self):
        """Verify aggregation of confidence scores across correct and incorrect predictions."""
        confidences: list[float | None] = [0.9, 0.5, 0.1, None]
        correct: list[bool | None] = [True, False, True, None]
        gold_categories = [
            FitCategory.GOOD,
            FitCategory.LOW,
            FitCategory.MODERATE,
            FitCategory.LOW,
        ]
        summary = confidence_summary(confidences, correct, gold_categories)
        assert summary["overall"]["n"] == 3.0
        assert summary["overall"]["mean"] == pytest.approx(0.5)
        assert summary["correct"]["n"] == 2.0
        assert summary["correct"]["mean"] == pytest.approx(0.5)
        assert summary["incorrect"]["n"] == 1.0
        assert summary["incorrect"]["mean"] == pytest.approx(0.5)
        assert summary["by_band"]["good"]["n"] == 1.0
        assert summary["by_band"]["good"]["mean"] == pytest.approx(0.9)
