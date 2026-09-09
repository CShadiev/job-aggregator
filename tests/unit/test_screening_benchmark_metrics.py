"""Unit tests for screening benchmark label and metric helpers."""

from pathlib import Path

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
    cost_per_100_usd,
    fitting_recall,
    good_recall,
    llm_calls_saved,
    moderate_recall,
    n_passed,
    naive_recall,
    passed_at_threshold,
    reduction_rate,
    threshold_sweep,
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


_GOLD_CATEGORIES = [
    FitCategory.GOOD,
    FitCategory.GOOD,
    FitCategory.MODERATE,
    FitCategory.MODERATE,
    FitCategory.LOW,
]


class TestGatingRecalls:
    """Tests for good / moderate / fitting recall against a binary pass mask."""

    def test_perfect(self):
        """Verify 1.0 recall when every relevant entry passed."""
        passed: list[bool | None] = [True, True, True, True, False]
        assert good_recall(_GOLD_CATEGORIES, passed) == 1.0
        assert moderate_recall(_GOLD_CATEGORIES, passed) == 1.0
        assert fitting_recall(_GOLD_CATEGORIES, passed) == 1.0

    def test_partial_and_none_as_miss(self):
        """Verify None never counts as a pass and missed bands reduce recall."""
        passed: list[bool | None] = [True, None, True, False, True]
        assert good_recall(_GOLD_CATEGORIES, passed) == 0.5
        assert moderate_recall(_GOLD_CATEGORIES, passed) == 0.5
        assert fitting_recall(_GOLD_CATEGORIES, passed) == 0.5

    def test_empty_band_is_zero(self):
        """Verify 0.0 when the gold set has no entries in the requested band."""
        gold = [FitCategory.LOW, FitCategory.LOW]
        passed: list[bool | None] = [True, False]
        assert good_recall(gold, passed) == 0.0
        assert moderate_recall(gold, passed) == 0.0
        assert fitting_recall(gold, passed) == 0.0

    def test_length_mismatch(self):
        """Verify ValueError raised on mismatched list lengths."""
        with pytest.raises(ValueError):
            good_recall(_GOLD_CATEGORIES, [True])


class TestReductionAndNaiveRecall:
    """Tests for reduction rate, calls saved, naive recall, and pass counts."""

    def test_zero_pass(self):
        """Verify 100% reduction when nothing passes."""
        assert n_passed([False, None, False]) == 0
        assert reduction_rate(0, 300) == 1.0
        assert llm_calls_saved(0, 300) == 300
        assert naive_recall(0, 300) == 0.0

    def test_partial_pass(self):
        """Verify reduction and naive recall at a mixed operating point."""
        passed: list[bool | None] = [True, True, False, None]
        assert n_passed(passed) == 2
        assert reduction_rate(2, 4) == 0.5
        assert llm_calls_saved(2, 4) == 2
        assert naive_recall(2, 4) == 0.5

    def test_full_pass(self):
        """Verify 0% reduction when every entry passes."""
        assert reduction_rate(300, 300) == 0.0
        assert llm_calls_saved(300, 300) == 0
        assert naive_recall(300, 300) == 1.0

    def test_empty_and_over_pass(self):
        """Verify empty totals return 0.0 and over-pass is clamped."""
        assert reduction_rate(10, 0) == 0.0
        assert naive_recall(10, 0) == 0.0
        assert llm_calls_saved(350, 300) == 0
        assert reduction_rate(350, 300) == 0.0
        assert naive_recall(350, 300) == 1.0


class TestPassedAtThreshold:
    """Tests for the confidence-threshold pass rule."""

    def test_zero_matches_binary_keep(self):
        """Verify t=0.0 equals raw binary keep when confidence is recorded."""
        pred: list[bool | None] = [True, True, False, False]
        conf: list[float | None] = [0.0, 0.9, 0.99, 0.1]
        assert passed_at_threshold(pred, conf, 0.0) == [True, True, False, False]

    def test_keep_below_threshold_fails(self):
        """Verify a keep with confidence 0.8 fails at t=0.9."""
        pred: list[bool | None] = [True]
        conf: list[float | None] = [0.8]
        assert passed_at_threshold(pred, conf, 0.9) == [False]
        assert passed_at_threshold(pred, conf, 0.8) == [True]

    def test_drop_with_high_confidence_still_fails(self):
        """Verify a drop never passes, even with confidence 1.0."""
        pred: list[bool | None] = [False]
        conf: list[float | None] = [1.0]
        assert passed_at_threshold(pred, conf, 0.0) == [False]
        assert passed_at_threshold(pred, conf, 0.9) == [False]

    def test_none_never_passes(self):
        """Verify missing predictions or confidences never pass."""
        pred: list[bool | None] = [True, None, True]
        conf: list[float | None] = [None, 0.9, 0.9]
        assert passed_at_threshold(pred, conf, 0.0) == [False, False, True]

    def test_length_mismatch(self):
        """Verify ValueError raised on mismatched list lengths."""
        with pytest.raises(ValueError):
            passed_at_threshold([True], [], 0.0)


class TestThresholdSweep:
    """Tests for the multi-cutoff gating metric table."""

    def test_sweep_rows(self):
        """Verify t=0 matches binary keep and a higher cutoff drops a low-confidence keep."""
        gold = [
            FitCategory.GOOD,
            FitCategory.GOOD,
            FitCategory.MODERATE,
            FitCategory.LOW,
        ]
        pred: list[bool | None] = [True, True, True, False]
        conf: list[float | None] = [0.95, 0.8, 0.95, 0.99]
        rows = threshold_sweep(gold, pred, conf, (0.0, 0.9))
        assert len(rows) == 2

        at_zero = rows[0]
        assert at_zero["threshold"] == 0.0
        assert at_zero["n_passed"] == 3.0
        assert at_zero["good_recall"] == 1.0
        assert at_zero["moderate_recall"] == 1.0
        assert at_zero["fitting_recall"] == 1.0
        assert at_zero["reduction_rate"] == 0.25
        assert at_zero["llm_calls_saved"] == 1.0
        assert at_zero["naive_recall"] == 0.75

        at_high = rows[1]
        assert at_high["threshold"] == 0.9
        assert at_high["n_passed"] == 2.0
        assert at_high["good_recall"] == 0.5
        assert at_high["moderate_recall"] == 1.0
        assert at_high["fitting_recall"] == pytest.approx(2.0 / 3.0)
        assert at_high["reduction_rate"] == 0.5

    def test_length_mismatch(self):
        """Verify ValueError raised on mismatched list lengths."""
        with pytest.raises(ValueError):
            threshold_sweep(_GOLD_CATEGORIES, [True], [0.9], (0.0,))


class TestCostPer100:
    """Tests for USD cost normalization per 100 completed entries."""

    def test_known_rate_and_tokens(self):
        """Verify 300 completed entries scale total USD to a per-100 figure."""
        # 1M input @ $0.20/1M + 0.5M output @ $1.20/1M = $0.80
        total_usd = 0.80
        assert cost_per_100_usd(total_usd, 300) == pytest.approx(0.80 / 300 * 100)

    def test_empty_completed_is_zero(self):
        """Verify 0.0 returned when no entries completed."""
        assert cost_per_100_usd(1.0, 0) == 0.0
        assert cost_per_100_usd(0.0, 0) == 0.0


class TestRenderReport:
    """Tests for retrieval-style screening report rendering (no LLM)."""

    def test_headline_matches_t0_sweep_and_prices_luna(self, tmp_path: Path):
        """Verify t=0.0 headline recalls match the sweep and luna cost is non-zero."""
        from scripts.run_screening_benchmark import (
            BenchmarkRun,
            EntryResult,
            _render_report,
        )

        results = [
            EntryResult(
                id="0",
                job_uid="g1",
                gold_cv_score=80.0,
                gold_cv_category=FitCategory.GOOD,
                gold_worth=True,
                predicted_worth=True,
                predicted_confidence=0.95,
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            EntryResult(
                id="1",
                job_uid="g2",
                gold_cv_score=75.0,
                gold_cv_category=FitCategory.GOOD,
                gold_worth=True,
                predicted_worth=True,
                predicted_confidence=0.80,
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            EntryResult(
                id="2",
                job_uid="m1",
                gold_cv_score=60.0,
                gold_cv_category=FitCategory.MODERATE,
                gold_worth=True,
                predicted_worth=True,
                predicted_confidence=0.95,
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            EntryResult(
                id="3",
                job_uid="l1",
                gold_cv_score=10.0,
                gold_cv_category=FitCategory.LOW,
                gold_worth=False,
                predicted_worth=False,
                predicted_confidence=0.99,
                input_tokens=1_000_000,
                output_tokens=0,
            ),
        ]
        run = BenchmarkRun(
            dataset_version="testday",
            dataset_path=tmp_path,
            model="gpt-5.6-luna",
            concurrency=1,
            manifest={
                "n_entries": 4,
                "username": "tester",
                "exported_at": "2026-01-01T00:00:00+00:00",
                "stratification": {
                    "axis": "cv_category",
                    "positive_definition": "moderate or good",
                    "target_per_class": {"good": 2, "moderate": 1, "low": 1},
                    "actual_per_class": {"good": 2, "moderate": 1, "low": 1},
                },
            },
            results=results,
            timestamp="20260101_000000",
        )
        report = _render_report(run)
        assert "Unpriced model" not in report
        # 4M input tokens @ $0.20/1M = $0.80; per 100 = $20.00
        assert "| $20.0000 | 25.0% | 1 | 0.7500 | 1.0000 | 1.0000 |" in report
        assert "| 0.00 | 3 | 25.0% | 1 | 0.7500 | 1.0000 | 1.0000 | 1.0000 |" in report
        assert "| 0.90 | 2 | 50.0% | 2 | 0.5000 | 0.5000 | 1.0000 | 0.6667 |" in report
        assert "Fitting jobs: 3 (Good: 2, Moderate: 1, Low: 1)" in report
