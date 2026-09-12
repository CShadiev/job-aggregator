"""Unit tests for the manual cover-letter generation endpoint and its background task."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agents.cover_letter_generation import CoverLetterGenerationAgent
from api.deps import get_cover_letter_agent, get_jobs_repository, get_object_storage
from cover_letter_service import run_cover_letter_generation_task
from main import app
from models.cover_letter_task import CoverLetterTask, CoverLetterTaskStatus
from models.fit_assessment import CoverLetterContent, CoverLetterSection
from orchestration.nodes.pair import make_pair_nodes
from orchestration.state import new_pair_state
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage
from tests.datasets.cover_letter_sample import (
    make_sample_fit_assessment,
    make_sample_job_posting,
    make_sample_user_profile,
)

# api.deps.get_current_user is hardcoded to this user.
_USERNAME = "cshadiev"
_JOB_UID = make_sample_job_posting().uid
_URL = f"/jobs/{_JOB_UID}/cover-letter/generate"
_OBJECT_KEY = f"job-aggregator/{_USERNAME}/cover_letters/{_JOB_UID}.json"


def _sample_content() -> CoverLetterContent:
    """Build a minimal generated cover letter."""
    return CoverLetterContent(
        name="Ada Lindqvist",
        title="Senior Backend Engineer",
        email="ada.lindqvist@example.com",
        linkedin={"label": "LinkedIn", "url": "https://linkedin.com/in/adalindqvist"},
        website={"label": "Website", "url": "https://ada.dev"},
        sections=[CoverLetterSection(title="Why me", content=["Because."])],
    )


def _task(status: CoverLetterTaskStatus, *, expires_in_seconds: float) -> CoverLetterTask:
    """Build a stored task in *status* whose claim expires *expires_in_seconds* from now."""
    return CoverLetterTask(
        username=_USERNAME,
        job_uid=_JOB_UID,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    )


def _repository(
    *,
    cover_letter_key: str | None = None,
    task: CoverLetterTask | None = None,
    job=None,
    profile=None,
) -> AsyncMock:
    """Build a repository whose eligibility lookups resolve to the given state."""
    repository = AsyncMock(spec=MongoJobsRepository)
    repository.get_assessment.return_value = make_sample_fit_assessment()
    repository.get_application_cover_letter_key.return_value = cover_letter_key
    repository.get_cover_letter_task.return_value = task
    repository.get_job.return_value = job if job is not None else make_sample_job_posting()
    repository.get_user_profile.return_value = (
        profile if profile is not None else make_sample_user_profile()
    )
    repository.claim_pending_cover_letter_task.return_value = _task(
        CoverLetterTaskStatus.PENDING, expires_in_seconds=90
    )
    return repository


@pytest.fixture
def scheduled(monkeypatch) -> AsyncMock:
    """Replace the background generation task so scheduling can be asserted without running it."""
    task = AsyncMock()
    monkeypatch.setattr("api.routes.jobs.run_cover_letter_generation_task", task)
    return task


@pytest.fixture
def client():
    """Serve the app with storage and agent mocked; each test overrides the repository itself."""
    app.dependency_overrides[get_object_storage] = lambda: MagicMock(spec=ObjectStorage)
    app.dependency_overrides[get_cover_letter_agent] = lambda: AsyncMock(
        spec=CoverLetterGenerationAgent
    )
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


class TestGenerateCoverLetterEligibility:
    """Requests are rejected or short-circuited before any task is claimed."""

    def test_unassessed_job_is_not_found(self, client, scheduled):
        """A job without a stored fit assessment cannot have a cover letter generated."""
        repository = _repository()
        repository.get_assessment.return_value = None
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.status_code == 404
        repository.claim_pending_cover_letter_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_existing_cover_letter_reports_complete_without_scheduling(self, client, scheduled):
        """A letter the pipeline already generated is reported complete and never regenerated."""
        repository = _repository(cover_letter_key=_OBJECT_KEY)
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.status_code == 200
        assert response.json() == {"status": "complete"}
        repository.get_cover_letter_task.assert_not_awaited()
        repository.claim_pending_cover_letter_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_missing_job_is_not_found(self, client, scheduled):
        """A deleted posting fails the request instead of claiming a task that cannot succeed."""
        repository = _repository()
        repository.get_job.return_value = None
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.status_code == 404
        repository.claim_pending_cover_letter_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_missing_profile_is_not_found(self, client, scheduled):
        """The agent needs a profile, so a missing one fails before scheduling."""
        repository = _repository()
        repository.get_user_profile.return_value = None
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.status_code == 404
        repository.claim_pending_cover_letter_task.assert_not_awaited()
        scheduled.assert_not_awaited()


class TestGenerateCoverLetterTaskState:
    """The stored task decides whether the request starts a run or reports one."""

    def test_first_request_claims_and_schedules(self, client, scheduled):
        """With no task on record the request claims one and schedules generation."""
        repository = _repository(task=None)
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.status_code == 200
        assert response.json() == {"status": "pending"}
        repository.claim_pending_cover_letter_task.assert_awaited_once()
        assert scheduled.await_args.kwargs["username"] == _USERNAME
        assert scheduled.await_args.kwargs["job_uid"] == _JOB_UID

    def test_live_pending_task_is_reported_without_rescheduling(self, client, scheduled):
        """A run still within its claim window is reported, not restarted."""
        repository = _repository(task=_task(CoverLetterTaskStatus.PENDING, expires_in_seconds=60))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.json() == {"status": "pending"}
        repository.claim_pending_cover_letter_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_expired_pending_task_is_claimed_again(self, client, scheduled):
        """A pending task past its expiry belonged to a process that is gone; restart it."""
        repository = _repository(task=_task(CoverLetterTaskStatus.PENDING, expires_in_seconds=-1))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.json() == {"status": "pending"}
        repository.claim_pending_cover_letter_task.assert_awaited_once()
        scheduled.assert_awaited_once()

    def test_failed_task_restarts_generation(self, client, scheduled):
        """A failed run retries on the next request and the client only ever sees pending."""
        repository = _repository(task=_task(CoverLetterTaskStatus.FAILED, expires_in_seconds=-1))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.json() == {"status": "pending"}
        repository.claim_pending_cover_letter_task.assert_awaited_once()
        scheduled.assert_awaited_once()

    def test_complete_task_is_reported(self, client, scheduled):
        """A finished run reports complete even before the client fetches the letter."""
        repository = _repository(task=_task(CoverLetterTaskStatus.COMPLETE, expires_in_seconds=-1))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.json() == {"status": "complete"}
        repository.claim_pending_cover_letter_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_lost_claim_reports_the_winning_task(self, client, scheduled):
        """When a concurrent request wins the claim, this one reports without scheduling."""
        repository = _repository(task=None)
        repository.claim_pending_cover_letter_task.return_value = None
        repository.get_cover_letter_task.side_effect = [
            None,
            _task(CoverLetterTaskStatus.PENDING, expires_in_seconds=90),
        ]
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL)

        assert response.json() == {"status": "pending"}
        scheduled.assert_not_awaited()


class TestOpenApiContract:
    """The generation trigger is part of the published API surface."""

    def test_generate_path_is_a_post_endpoint(self):
        """Verify OpenAPI exposes POST /jobs/{job_uid}/cover-letter/generate."""
        schema = app.openapi()
        assert "post" in schema["paths"]["/jobs/{job_uid}/cover-letter/generate"]

    def test_response_status_never_advertises_failed(self):
        """The client-facing status enum stays pending/complete; failures retry silently."""
        schema = app.openapi()
        status_enum = schema["components"]["schemas"]["CoverLetterGenerationStatus"]["enum"]
        assert set(status_enum) == {"pending", "complete"}


class TestBackgroundGenerationTask:
    """The background run records its own outcome on the task document."""

    async def test_success_persists_key_and_completes_task(self):
        """A successful run uploads the letter, sets the key, and marks the task complete."""
        repository = AsyncMock(spec=MongoJobsRepository)
        repository.get_job.return_value = make_sample_job_posting()
        repository.get_user_profile.return_value = make_sample_user_profile()
        repository.get_assessment.return_value = make_sample_fit_assessment()
        agent = AsyncMock(spec=CoverLetterGenerationAgent)
        agent.generate.return_value = _sample_content()
        storage = MagicMock(spec=ObjectStorage)
        storage.upload_coverletter_json.return_value = _OBJECT_KEY

        await run_cover_letter_generation_task(
            username=_USERNAME,
            job_uid=_JOB_UID,
            repository=repository,
            object_storage=storage,
            agent=agent,
        )

        update = repository.update_job_application_status.await_args.kwargs
        assert update["request"].cover_letter_key == _OBJECT_KEY
        repository.complete_cover_letter_task.assert_awaited_once_with(_USERNAME, _JOB_UID)
        repository.fail_cover_letter_task.assert_not_awaited()

    async def test_generation_error_is_recorded_on_the_task(self):
        """A failing agent leaves the error on the task instead of raising out of the run."""
        repository = AsyncMock(spec=MongoJobsRepository)
        repository.get_job.return_value = make_sample_job_posting()
        repository.get_user_profile.return_value = make_sample_user_profile()
        repository.get_assessment.return_value = make_sample_fit_assessment()
        agent = AsyncMock(spec=CoverLetterGenerationAgent)
        agent.generate.side_effect = RuntimeError("llm unavailable")

        await run_cover_letter_generation_task(
            username=_USERNAME,
            job_uid=_JOB_UID,
            repository=repository,
            object_storage=MagicMock(spec=ObjectStorage),
            agent=agent,
        )

        repository.fail_cover_letter_task.assert_awaited_once_with(
            _USERNAME, _JOB_UID, error="llm unavailable"
        )
        repository.complete_cover_letter_task.assert_not_awaited()

    async def test_deleted_assessment_fails_the_task(self):
        """State can change between the request and the run; the task records why it stopped."""
        repository = AsyncMock(spec=MongoJobsRepository)
        repository.get_job.return_value = make_sample_job_posting()
        repository.get_user_profile.return_value = make_sample_user_profile()
        repository.get_assessment.return_value = None

        await run_cover_letter_generation_task(
            username=_USERNAME,
            job_uid=_JOB_UID,
            repository=repository,
            object_storage=MagicMock(spec=ObjectStorage),
            agent=AsyncMock(spec=CoverLetterGenerationAgent),
        )

        assert (
            "Assessment not found" in repository.fail_cover_letter_task.await_args.kwargs["error"]
        )
        repository.complete_cover_letter_task.assert_not_awaited()


async def test_pair_cover_letter_node_uses_shared_helper(monkeypatch):
    """The pipeline node delegates generation to the helper the API also uses."""
    job = make_sample_job_posting()
    deps = MagicMock()
    deps.repository = AsyncMock()
    deps.repository.get_application_cover_letter_key.return_value = None
    deps.repository.get_user_profile.return_value = make_sample_user_profile()
    helper = AsyncMock(return_value=_OBJECT_KEY)
    monkeypatch.setattr(
        "orchestration.nodes.pair.generate_and_persist_cover_letter",
        helper,
    )

    nodes = make_pair_nodes(deps)
    result = await nodes["cover_letter"](
        new_pair_state(
            cycle_id="c1",
            username=_USERNAME,
            job=job.model_dump(mode="json"),
            assessment=make_sample_fit_assessment().model_dump(mode="json"),
        )
    )

    assert result == {"cover_letter_key": _OBJECT_KEY}
    call = helper.await_args_list[0].kwargs
    assert call["job"].uid == job.uid
    assert call["agent"] is deps.cover_letter_agent
