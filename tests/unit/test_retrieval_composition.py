"""Unit tests for the retrieval+screening composition replay."""

from benchmarks.retrieval.composition import ScreeningRow, compose_gate


def _row(
    uid: str,
    category: str,
    *,
    keep: bool,
    gold_fit: bool | None = None,
    input_tokens: int = 1000,
    output_tokens: int = 10,
) -> ScreeningRow:
    return ScreeningRow(
        job_uid=uid,
        cv_category=category,
        worth_full_assessment_gold=(
            category in {"good", "moderate"} if gold_fit is None else gold_fit
        ),
        predicted_keep=keep,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=0,
    )


def test_composed_recall_counts_a_miss_by_either_gate():
    """A gold job dropped by retrieval or by screening is not retained."""
    rows = [
        _row("a", "good", keep=True),
        _row("b", "good", keep=True),
        _row("c", "moderate", keep=True),
        _row("d", "low", keep=False),
    ]
    # Top-2 keeps a (screened in) and drops d. b is gold-good but not retrieved.
    # c would pass screening but retrieval ranked it outside K.
    report = compose_gate(
        ranked_uids=["a", "d", "c", "b"],
        operating_k=2,
        rows=rows,
        assessment_cost_per_call_usd=0.01,
        screening_model="gpt-5.6-luna",
    )
    assert report["n_assessed"] == 1
    assert report["good_recall"] == 0.5
    assert report["fitting_recall"] == 1 / 3
    assert report["retrieval_good_recall"] == 0.5
    assert report["reduction_rate"] == 0.75
    assert report["screening_usd"] > 0
    assert report["assessment_usd"] == 0.01
    assert report["assess_all_usd"] == 0.04
    assert report["composed_usd"] == report["screening_usd"] + 0.01


def test_screening_error_does_not_pass():
    """A retrieval hit whose screening prediction failed does not reach assessment."""
    rows = [
        ScreeningRow(
            job_uid="a",
            cv_category="good",
            worth_full_assessment_gold=True,
            predicted_keep=False,
            input_tokens=10,
            output_tokens=1,
            cache_read_tokens=0,
        )
    ]
    report = compose_gate(
        ranked_uids=["a"],
        operating_k=1,
        rows=rows,
        assessment_cost_per_call_usd=1.0,
        screening_model="gpt-5.6-luna",
    )
    assert report["n_assessed"] == 0
    assert report["good_recall"] == 0.0
