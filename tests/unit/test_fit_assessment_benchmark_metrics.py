"""Unit tests for fit-assessment benchmark category and metric helpers."""

from pathlib import Path

import pytest

from benchmarks.fit_assessment.categories import FitCategory, score_to_category
from benchmarks.fit_assessment.metrics import (
    ERROR_LABEL,
    adjacent_accuracy,
    confusion_matrix,
    exact_accuracy,
    passed_at_score_threshold,
    per_class_prf,
    score_threshold_sweep,
)


class TestScoreToCategory:
    """Tests for converting ATS score to discrete fit category."""

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
        """Verify score range boundaries for categories."""
        assert score_to_category(score) is expected


class TestExactAccuracy:
    """Tests for exact match classification accuracy."""

    def test_all_correct(self):
        """Verify 100% accuracy on perfect category match."""
        gold = [FitCategory.LOW, FitCategory.MODERATE, FitCategory.GOOD]
        pred: list[FitCategory | None] = list(gold)
        assert exact_accuracy(gold, pred) == 1.0

    def test_none_never_matches(self):
        """Verify None prediction does not match gold category."""
        gold = [FitCategory.LOW, FitCategory.MODERATE]
        pred = [None, FitCategory.MODERATE]
        assert exact_accuracy(gold, pred) == 0.5

    def test_empty(self):
        """Verify 0.0 returned on empty input lists."""
        assert exact_accuracy([], []) == 0.0

    def test_length_mismatch(self):
        """Verify ValueError raised on mismatched list lengths."""
        with pytest.raises(ValueError):
            exact_accuracy([FitCategory.LOW], [])


class TestAdjacentAccuracy:
    """Tests for relaxed adjacent-category accuracy."""

    def test_exact_and_neighbors(self):
        """Verify that neighboring category predictions count as acceptable."""
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
    """Tests for multi-class confusion matrix generation."""

    def test_with_error_column(self):
        """Verify confusion matrix with error column for failed predictions."""
        gold = [FitCategory.LOW, FitCategory.MODERATE, FitCategory.GOOD]
        pred = [FitCategory.LOW, None, FitCategory.MODERATE]
        matrix = confusion_matrix(gold, pred)
        assert matrix["low"]["low"] == 1
        assert matrix["moderate"][ERROR_LABEL] == 1
        assert matrix["good"]["moderate"] == 1
        assert ERROR_LABEL in matrix["low"]

    def test_without_error_column(self):
        """Verify confusion matrix without error column when all predictions succeed."""
        gold = [FitCategory.LOW]
        pred: list[FitCategory | None] = [FitCategory.LOW]
        matrix = confusion_matrix(gold, pred)
        assert ERROR_LABEL not in matrix["low"]


class TestPerClassPrf:
    """Tests for per-category precision, recall, and F1 calculations."""

    def test_perfect(self):
        """Verify per-class metrics on perfect predictions."""
        gold = [FitCategory.LOW, FitCategory.MODERATE, FitCategory.GOOD]
        pred: list[FitCategory | None] = list(gold)
        metrics = per_class_prf(gold, pred)
        for cls in FitCategory:
            assert metrics[cls]["precision"] == 1.0
            assert metrics[cls]["recall"] == 1.0
            assert metrics[cls]["f1"] == 1.0
            assert metrics[cls]["support"] == 1.0

    def test_none_counts_as_false_negative(self):
        """Verify None prediction counts as a false negative for recall."""
        gold = [FitCategory.GOOD, FitCategory.GOOD]
        pred: list[FitCategory | None] = [FitCategory.GOOD, None]
        metrics = per_class_prf(gold, pred)
        assert metrics[FitCategory.GOOD]["recall"] == 0.5
        assert metrics[FitCategory.GOOD]["support"] == 2.0


_GOLD_CV = [
    FitCategory.GOOD,
    FitCategory.GOOD,
    FitCategory.MODERATE,
    FitCategory.LOW,
]


class TestPassedAtScoreThreshold:
    """Tests for the CV-score cover-letter pass rule."""

    def test_at_and_above_pass(self):
        """Verify scores at or above the cutoff pass and scores below fail."""
        scores: list[float | None] = [80.0, 79.9, 90.0, None]
        assert passed_at_score_threshold(scores, 80.0) == [True, False, True, False]

    def test_none_never_passes(self):
        """Verify missing predictions never pass, even at threshold 0."""
        assert passed_at_score_threshold([None], 0.0) == [False]


class TestScoreThresholdSweep:
    """Tests for the multi-cutoff cover-letter gating table."""

    def test_sweep_rows(self):
        """Verify t=70 keeps good+adjacent-moderate and t=80 drops a 75."""
        scores: list[float | None] = [95.0, 75.0, 60.0, 10.0]
        rows = score_threshold_sweep(_GOLD_CV, scores, (70.0, 80.0))
        assert len(rows) == 2

        at_good = rows[0]
        assert at_good["threshold"] == 70.0
        assert at_good["n_passed"] == 2.0
        assert at_good["good_recall"] == 1.0
        assert at_good["moderate_recall"] == 0.0
        assert at_good["fitting_recall"] == pytest.approx(2.0 / 3.0)
        assert at_good["reduction_rate"] == 0.5
        assert at_good["llm_calls_saved"] == 2.0
        assert at_good["naive_recall"] == 0.5

        at_prod = rows[1]
        assert at_prod["threshold"] == 80.0
        assert at_prod["n_passed"] == 1.0
        assert at_prod["good_recall"] == 0.5
        assert at_prod["fitting_recall"] == pytest.approx(1.0 / 3.0)
        assert at_prod["reduction_rate"] == 0.75

    def test_length_mismatch(self):
        """Verify ValueError raised on mismatched list lengths."""
        with pytest.raises(ValueError):
            score_threshold_sweep(_GOLD_CV, [80.0], (80.0,))


class TestRenderReport:
    """Tests for retrieval-style fit-assessment report rendering (no LLM)."""

    def test_headline_uses_production_threshold_and_prices_luna(self, tmp_path: Path):
        """Verify t=80 headline matches the sweep and luna cost is non-zero."""
        from scripts.run_fit_assessment_benchmark import (
            BenchmarkRun,
            EntryResult,
            _render_report,
        )

        results = [
            EntryResult(
                id="0",
                job_uid="g1",
                gold_cv_score=95.0,
                gold_profile_score=90.0,
                gold_cv_category=FitCategory.GOOD,
                gold_profile_category=FitCategory.GOOD,
                predicted_cv_score=95.0,
                predicted_profile_score=90.0,
                predicted_cv_category=FitCategory.GOOD,
                predicted_profile_category=FitCategory.GOOD,
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            EntryResult(
                id="1",
                job_uid="g2",
                gold_cv_score=75.0,
                gold_profile_score=70.0,
                gold_cv_category=FitCategory.GOOD,
                gold_profile_category=FitCategory.GOOD,
                predicted_cv_score=75.0,
                predicted_profile_score=70.0,
                predicted_cv_category=FitCategory.GOOD,
                predicted_profile_category=FitCategory.GOOD,
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            EntryResult(
                id="2",
                job_uid="m1",
                gold_cv_score=60.0,
                gold_profile_score=55.0,
                gold_cv_category=FitCategory.MODERATE,
                gold_profile_category=FitCategory.MODERATE,
                predicted_cv_score=60.0,
                predicted_profile_score=55.0,
                predicted_cv_category=FitCategory.MODERATE,
                predicted_profile_category=FitCategory.MODERATE,
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            EntryResult(
                id="3",
                job_uid="l1",
                gold_cv_score=10.0,
                gold_profile_score=20.0,
                gold_cv_category=FitCategory.LOW,
                gold_profile_category=FitCategory.LOW,
                predicted_cv_score=10.0,
                predicted_profile_score=20.0,
                predicted_cv_category=FitCategory.LOW,
                predicted_profile_category=FitCategory.LOW,
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
                    "axis": "profile_category",
                    "target_per_class": {"good": 2, "moderate": 1, "low": 1},
                    "actual_per_class": {"good": 2, "moderate": 1, "low": 1},
                },
            },
            results=results,
            timestamp="20260101_000000",
        )
        report = _render_report(run)
        assert "Unpriced model" not in report
        # 4M input @ $0.20/1M = $0.80; per 100 = $20.00. Headline is t=80.
        assert "| $20.0000 | 75.0% | 3 | 0.2500 | 0.5000 | 0.3333 |" in report
        assert "| 80 | 1 | 75.0% | 3 | 0.2500 | 0.5000 | 0.0000 | 0.3333 |" in report
        assert "| 50 | 3 | 25.0% | 1 | 0.7500 | 1.0000 | 1.0000 | 1.0000 |" in report
        assert "Fitting jobs (gold CV): 3 (Good: 2, Moderate: 1, Low: 1)" in report
        assert "Production CV threshold: 80" in report
