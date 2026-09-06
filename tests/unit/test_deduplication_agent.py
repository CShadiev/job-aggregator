"""Unit tests for the DeduplicationAgent reconciliation logic."""

from pydantic_ai.models.test import TestModel

from agents.deduplication import DeduplicationAgent
from models.deduplication import NormalizedBatch, NormalizedJobEntry

from ..helpers.job_posting import make_job_posting, make_normalized_batch


def get_agent() -> DeduplicationAgent:
    """Create a DeduplicationAgent instance backed by a dummy TestModel."""
    return DeduplicationAgent(model=TestModel())


class TestReconcile:
    """Test suite for DeduplicationAgent._reconcile output mapping."""

    def test_happy_path(self):
        """Verify normal reconciliation of LLM response with original raw postings."""
        agent = get_agent()
        postings = [
            make_job_posting(uid="test:0", title="Sr. Engineer", company="Google Inc."),
            make_job_posting(uid="test:1", title="Dev.", company="Meta LLC"),
        ]
        temp_map = {str(i): posting for i, posting in enumerate(postings)}
        normalized = make_normalized_batch(
            [
                ("0", "senior engineer", "google"),
                ("1", "developer", "meta"),
            ]
        )

        processed_jobs, failed_jobs = agent._reconcile(temp_map, normalized)

        assert len(processed_jobs) == 2
        assert failed_jobs == []

        for processed, entry in zip(processed_jobs, normalized.jobs, strict=True):
            assert processed.uid == f"test:{entry.id}"
            assert processed.title_normalized == entry.title
            assert processed.company_normalized == entry.company

    def test_missing_entry_returns_partial_response(self):
        """Verify that jobs missing from the LLM output are returned as failed jobs."""
        agent = get_agent()
        postings = [
            make_job_posting(uid="test:0"),
            make_job_posting(uid="test:1"),
        ]
        temp_map = {str(i): posting for i, posting in enumerate(postings)}
        normalized = make_normalized_batch([("0", "engineer", "acme")])

        processed, failed = agent._reconcile(temp_map, normalized)

        assert len(processed) == 1
        assert processed[0].uid == "test:0"
        assert len(failed) == 1
        assert failed[0].posting.uid == "test:1"

    def test_unknown_id_ignored(self):
        """Verify that unrecognized job IDs returned by the LLM are safely ignored."""
        agent = get_agent()
        posting = make_job_posting(uid="test:0")
        temp_map = {"0": posting}
        normalized = make_normalized_batch(
            [
                ("0", "engineer", "acme"),
                ("99", "other", "unknown"),
            ]
        )

        processed, failed = agent._reconcile(temp_map, normalized)

        assert len(processed) == 1
        assert processed[0].uid == "test:0"
        assert failed == []

    def test_duplicate_id_first_wins(self):
        """Verify that when an ID is repeated in the LLM output, the first entry wins."""
        agent = get_agent()
        posting = make_job_posting(uid="test:0", title="Original Title")
        temp_map = {"0": posting}
        normalized = NormalizedBatch(
            jobs=[
                NormalizedJobEntry(id="0", title="first", company="first-co"),
                NormalizedJobEntry(id="0", title="second", company="second-co"),
            ]
        )

        processed, failed = agent._reconcile(temp_map, normalized)

        assert len(processed) == 1
        assert processed[0].title_normalized == "first"
        assert processed[0].company_normalized == "first-co"
        assert failed == []

    def test_empty_batch_output(self):
        """Verify handling when the LLM returns an empty list of normalized jobs."""
        agent = get_agent()
        postings = [
            make_job_posting(uid="test:0"),
            make_job_posting(uid="test:1"),
        ]
        temp_map = {str(i): posting for i, posting in enumerate(postings)}

        processed, failed = agent._reconcile(temp_map, make_normalized_batch([]))

        assert processed == []
        assert len(failed) == 2

    def test_field_mapping_preserves_original_fields(self):
        """Verify that raw posting metadata and timestamps are preserved during reconciliation."""
        agent = get_agent()
        posting = make_job_posting(
            uid="test:42",
            title="Sr. Software Engineer (m/w/d)",
            company="Google Inc.",
            location="Berlin",
            remote=True,
        )
        temp_map = {"0": posting}
        normalized = make_normalized_batch([("0", "senior software engineer", "google")])

        processed, failed = agent._reconcile(temp_map, normalized)

        assert failed == []
        assert len(processed) == 1
        result = processed[0]
        assert result.uid == posting.uid
        assert result.title == posting.title
        assert result.company == posting.company
        assert result.location == posting.location
        assert result.remote is posting.remote
        assert result.title_normalized == normalized.jobs[0].title
        assert result.company_normalized == normalized.jobs[0].company
