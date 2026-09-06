"""ATS-band mapping to graded relevance (Q8)."""

from __future__ import annotations


def ats_score_to_grade(score: float | None, *, screened_through: bool) -> int:
    """Map a historical ATS score onto the 0–3 retrieval relevance scale.

    Grade 3: ATS ≥ 80 (good).
    Grade 2: ATS 60–79 (moderate).
    Grade 1: ATS < 60 but passed screening.
    Grade 0: screened out or never retrieved.
    """
    if not screened_through or score is None:
        return 0
    if score >= 80:
        return 3
    if score >= 60:
        return 2
    return 1
