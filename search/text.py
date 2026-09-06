"""Text preparation for BM25 fields and embedding inputs."""

from __future__ import annotations

import hashlib
import re
from html import unescape

from models.users import UserProfile

_TAG_RE = re.compile(r"<[^>]+>", flags=re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def strip_html(raw: str) -> str:
    """Remove HTML tags and collapse whitespace from ``description_raw``."""
    without_tags = _TAG_RE.sub(" ", unescape(raw or ""))
    return _WS_RE.sub(" ", without_tags).strip()


def job_embedding_text(title: str, description_raw: str) -> str:
    """Flat embedding string: title plus HTML-stripped description."""
    description = strip_html(description_raw)
    return _WS_RE.sub(" ", f"{title} {description}").strip()


def flatten_profile(profile: UserProfile) -> str:
    """Flatten headline, summary, skills, and experience for embedding / BM25."""
    parts: list[str] = [
        profile.profile.title,
        profile.summary.headline,
        profile.summary.description,
    ]
    skills = profile.technicalSkills
    for group in (
        skills.backend,
        skills.frontend,
        skills.infrastructure,
        skills.databases,
        skills.aiMl,
    ):
        parts.extend(skill.name for skill in group)
    for experience in profile.experience:
        parts.append(experience.title)
        parts.append(experience.company)
        parts.extend(experience.responsibilities)
        if experience.stack:
            parts.extend(experience.stack)
    return _WS_RE.sub(" ", " ".join(part for part in parts if part)).strip()


def profile_text_hash(text: str) -> str:
    """SHA-256 hex digest used as the process-level profile embedding cache key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
