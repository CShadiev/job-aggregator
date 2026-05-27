from pydantic_ai.models.test import TestModel

from agents.deduplication import DeduplicationAgent
from ..helpers.job_posting import make_job_posting, make_normalized_batch
from models.deduplication import NormalizedBatch, NormalizedJobEntry


def get_agent() -> DeduplicationAgent:
    return DeduplicationAgent(model=TestModel())


class TestReconcile:

    def test_happy_path(self):
        agent = get_agent()
        postings = [
            make_job_posting(uid="test:0", title="Sr. Engineer", company="Google Inc."),
            make_job_posting(uid="test:1", title="Dev.", company="Meta LLC"), ]
        temp_map = {str(i): posting for i, posting in enumerate(postings)}
        normalized = make_normalized_batch([
            ("0", "senior engineer", "google"),
            ("1", "developer", "meta"), ])

        processed_jobs, failed_jobs = agent._reconcile(temp_map, normalized)

        assert len(processed_jobs) == 2
        assert failed_jobs == []

        for processed, normalized in zip(processed_jobs, normalized.jobs):
            assert processed.uid == f"test:{normalized.id}"
            assert processed.title_normalized == normalized.title
            assert processed.company_normalized == normalized.company

    def test_missing_entry_returns_partial_response(self):
        agent = get_agent()
        postings = [
            make_job_posting(uid="test:0"),
            make_job_posting(uid="test:1"), ]
        temp_map = {str(i): posting for i, posting in enumerate(postings)}
        normalized = make_normalized_batch([("0", "engineer", "acme")])

        processed, failed = agent._reconcile(temp_map, normalized)

        assert len(processed) == 1
        assert processed[0].uid == "test:0"
        assert len(failed) == 1
        assert failed[0].posting.uid == "test:1"

    def test_unknown_id_ignored(self):
        agent = get_agent()
        posting = make_job_posting(uid="test:0")
        temp_map = {"0": posting}
        normalized = make_normalized_batch([
            ("0", "engineer", "acme"),
            ("99", "other", "unknown"), ])

        processed, failed = agent._reconcile(temp_map, normalized)

        assert len(processed) == 1
        assert processed[0].uid == "test:0"
        assert failed == []

    def test_duplicate_id_first_wins(self):
        agent = get_agent()
        posting = make_job_posting(uid="test:0", title="Original Title")
        temp_map = {"0": posting}
        normalized = NormalizedBatch(
            jobs=[
                NormalizedJobEntry(id="0", title="first", company="first-co"),
                NormalizedJobEntry(id="0", title="second", company="second-co"), ])

        processed, failed = agent._reconcile(temp_map, normalized)

        assert len(processed) == 1
        assert processed[0].title_normalized == "first"
        assert processed[0].company_normalized == "first-co"
        assert failed == []

    def test_empty_batch_output(self):
        agent = get_agent()
        postings = [
            make_job_posting(uid="test:0"),
            make_job_posting(uid="test:1"), ]
        temp_map = {str(i): posting for i, posting in enumerate(postings)}

        processed, failed = agent._reconcile(temp_map, make_normalized_batch([]))

        assert processed == []
        assert len(failed) == 2

    def test_field_mapping_preserves_original_fields(self):
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
