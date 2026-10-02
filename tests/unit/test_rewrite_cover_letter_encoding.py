"""Unit tests for the cover-letter encoding rewrite planner."""

import json

from scripts.rewrite_cover_letter_encoding import (
    candidate_encodings,
    plan_cover_letter_rewrite,
)

_ENCODINGS = ("cp1252", "cp1251")


def _letter(paragraph: str) -> dict:
    return {
        "name": "Mira Halberg",
        "title": "Engineer",
        "email": "mira@example.com",
        "linkedin": {"display": "linkedin.com/in/mira"},
        "website": {"display": "mira.example"},
        "sections": [{"title": "", "content": [paragraph]}],
    }


def _dump(paragraph: str) -> str:
    return json.dumps(_letter(paragraph), ensure_ascii=False)


def test_utf8_cover_letter_is_left_unchanged():
    raw = _dump("I’m applying").encode("utf-8")

    plan = plan_cover_letter_rewrite(raw, encodings=_ENCODINGS)

    assert b"\xe2\x80\x99" in raw
    assert plan.action == "unchanged"
    assert plan.body is None


def test_windows_code_page_letter_is_rewritten_as_utf8():
    raw = _dump("I’m applying").encode("cp1252")

    plan = plan_cover_letter_rewrite(raw, encodings=_ENCODINGS)

    assert raw[raw.find(b"I") + 1] == 0x92
    assert plan.action == "rewrite"
    assert plan.body is not None
    assert plan.body.decode("utf-8")
    text = json.loads(plan.body)["sections"][0]["content"][0]
    assert text == "I’m applying"


def test_disagreeing_code_pages_are_skipped():
    raw = _dump("Привет").encode("cp1251")

    plan = plan_cover_letter_rewrite(raw, encodings=_ENCODINGS)

    assert plan.action == "skip"
    assert plan.body is None
    assert "ambiguous" in plan.reason


def test_undecodable_bytes_are_skipped():
    plan = plan_cover_letter_rewrite(b"\xff\xfe not json", encodings=_ENCODINGS)

    assert plan.action == "skip"
    assert plan.body is None


def test_candidate_encodings_prefer_locale_and_drop_utf8():
    assert candidate_encodings("cp1251") == ("cp1251", "cp1252")
    assert candidate_encodings("utf-8") == ("cp1252", "cp1251")
    assert candidate_encodings("UTF8") == ("cp1252", "cp1251")
