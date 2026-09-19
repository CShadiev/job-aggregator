"""Unit tests for the manual job submission endpoint and its background task."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid1, uuid4

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agents.cover_letter_generation import CoverLetterGenerationAgent
from agents.cv_text_extraction import CVTextExtractionAgent
from agents.deduplication import DeduplicationAgent
from agents.fit_assessment import FitAssessmentAgent
from api.deps import (
    get_cover_letter_agent,
    get_current_user,
    get_cv_text_extraction_agent,
    get_deduplication_agent,
    get_fit_assessment_agent,
    get_jobs_repository,
    get_object_storage,
)
from job_submit_service import (
    MANUAL_JOB_SOURCE,
    posting_from_submit_request,
    run_manual_job_submit_task,
)
from main import app
from models.deduplication import FailedJobPosting, NormalizationResult
from models.jobs_api import CoverLetterGenerationStatus, ManualJobSubmitRequest
from models.manual_job_task import ManualJobTask, ManualJobTaskStatus
from models.users import CVTextArtifact, User
from repository.mongo_jobs_repository import MongoJobsRepository
from repository.object_storage import ObjectStorage
from tests.datasets.cover_letter_sample import (
    make_sample_fit_assessment,
    make_sample_user_profile,
)

_USERNAME = "cshadiev"
_JOB_UID = str(uuid4())
_OTHER_JOB_UID = str(uuid4())
_URL = "/jobs/submit"
_OBJECT_KEY = f"job-aggregator/{_USERNAME}/cover_letters/{_JOB_UID}.json"
_CV_DIGEST = "a" * 64


def _payload(**overrides) -> dict:
    """JSON body for POST /jobs/submit with optional field overrides."""
    body = {
        "job_uid": _JOB_UID,
        "title": "Senior Engineer",
        "company": "Acme",
        "description_raw": "Build things.",
        "url": "https://example.com/jobs/1",
    }
    body.update(overrides)
    return body


def _request(**overrides) -> ManualJobSubmitRequest:
    """Build a validated submit request."""
    return ManualJobSubmitRequest.model_validate(_payload(**overrides))


def _task(status: ManualJobTaskStatus, *, expires_in_seconds: float) -> ManualJobTask:
    """Build a stored task in *status* whose claim expires *expires_in_seconds* from now."""
    return ManualJobTask(
        username=_USERNAME,
        job_uid=_JOB_UID,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    )


def _repository(
    *,
    cover_letter_key: str | None = None,
    task: ManualJobTask | None = None,
    assessment=None,
    profile=None,
) -> AsyncMock:
    """Build a repository whose eligibility lookups resolve to the given state."""
    repository = AsyncMock(spec=MongoJobsRepository)
    repository.get_assessment.return_value = assessment
    repository.get_application_cover_letter_key.return_value = cover_letter_key
    repository.get_manual_job_task.return_value = task
    repository.get_user_profile.return_value = (
        profile if profile is not None else make_sample_user_profile()
    )
    repository.claim_pending_manual_job_task.return_value = _task(
        ManualJobTaskStatus.PENDING, expires_in_seconds=180
    )
    return repository


def _missing_cv_error() -> ClientError:
    """S3 error raised when the candidate has no uploaded CV."""
    return ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
        "GetObject",
    )


@pytest.fixture
def scheduled(monkeypatch) -> AsyncMock:
    """Replace the background submit task so scheduling can be asserted without running it."""
    task = AsyncMock()
    monkeypatch.setattr("api.routes.jobs.run_manual_job_submit_task", task)
    return task


@pytest.fixture
def client():
    """Serve the app as a signed-in user, with storage and agents mocked.

    Each test overrides the repository itself to set up the state under test.
    """
    storage = MagicMock(spec=ObjectStorage)
    storage.get_user_cv.return_value = b"%PDF"
    app.dependency_overrides[get_current_user] = lambda: User(username=_USERNAME, sub="test")
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_cover_letter_agent] = lambda: AsyncMock(
        spec=CoverLetterGenerationAgent
    )
    app.dependency_overrides[get_deduplication_agent] = lambda: AsyncMock(spec=DeduplicationAgent)
    app.dependency_overrides[get_fit_assessment_agent] = lambda: AsyncMock(spec=FitAssessmentAgent)
    app.dependency_overrides[get_cv_text_extraction_agent] = lambda: AsyncMock(
        spec=CVTextExtractionAgent
    )
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


class TestSubmitRequestModel:
    """Pydantic validation of the submit payload, independent of HTTP."""

    def test_uuid4_is_accepted(self):
        """A client-generated uuid4 is the supported job identity."""
        request = _request()
        assert str(request.job_uid) == _JOB_UID

    def test_non_uuid4_is_rejected(self):
        """UUID versions other than 4 are rejected so scraped uids cannot be overwritten."""
        with pytest.raises(ValidationError):
            ManualJobSubmitRequest.model_validate(_payload(job_uid=str(uuid1())))

    def test_collector_shaped_uid_is_rejected(self):
        """A ``{source}:{id}`` string is not a UUID and must 422 at the HTTP layer."""
        with pytest.raises(ValidationError):
            ManualJobSubmitRequest.model_validate(_payload(job_uid="linkedin:abc"))


class TestSubmitJobEligibility:
    """Requests are rejected or short-circuited before any task is claimed."""

    def test_missing_required_fields_are_unprocessable(self, client, scheduled):
        """Schema validation fails before any repository call."""
        repository = _repository()
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json={"job_uid": _JOB_UID})

        assert response.status_code == 422
        repository.claim_pending_manual_job_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_collector_shaped_uid_is_unprocessable(self, client, scheduled):
        """A scraped-style uid is rejected so upsert cannot overwrite a corpus row."""
        repository = _repository()
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload(job_uid="linkedin:abc"))

        assert response.status_code == 422
        repository.claim_pending_manual_job_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_missing_profile_is_not_found(self, client, scheduled):
        """The agents need a profile, so a missing one fails before scheduling."""
        repository = _repository()
        repository.get_user_profile.return_value = None
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.status_code == 404
        repository.claim_pending_manual_job_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_missing_cv_is_not_found(self, client, scheduled):
        """A missing S3 CV fails before claiming a task that cannot succeed."""
        repository = _repository()
        app.dependency_overrides[get_jobs_repository] = lambda: repository
        storage = MagicMock(spec=ObjectStorage)
        storage.get_user_cv.side_effect = _missing_cv_error()
        app.dependency_overrides[get_object_storage] = lambda: storage

        response = client.post(_URL, json=_payload())

        assert response.status_code == 404
        repository.claim_pending_manual_job_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_existing_assessment_and_letter_report_complete_without_scheduling(
        self, client, scheduled
    ):
        """A finished evaluation whose task row was lost still reports complete."""
        repository = _repository(
            assessment=make_sample_fit_assessment(), cover_letter_key=_OBJECT_KEY
        )
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.status_code == 200
        assert response.json() == {"job_uid": _JOB_UID, "status": "complete"}
        repository.claim_pending_manual_job_task.assert_not_awaited()
        scheduled.assert_not_awaited()


class TestSubmitJobTaskState:
    """The stored task decides whether the request starts a run or reports one."""

    def test_first_request_claims_and_schedules(self, client, scheduled):
        """With no task on record the request claims one and schedules evaluation."""
        repository = _repository(task=None)
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.status_code == 200
        assert response.json() == {"job_uid": _JOB_UID, "status": "pending"}
        repository.claim_pending_manual_job_task.assert_awaited_once()
        assert scheduled.await_args.kwargs["username"] == _USERNAME
        assert str(scheduled.await_args.kwargs["request"].job_uid) == _JOB_UID

    def test_live_pending_task_is_reported_without_rescheduling(self, client, scheduled):
        """A run still within its claim window is reported, not restarted."""
        repository = _repository(task=_task(ManualJobTaskStatus.PENDING, expires_in_seconds=60))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.json() == {"job_uid": _JOB_UID, "status": "pending"}
        repository.claim_pending_manual_job_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_expired_pending_task_is_claimed_again(self, client, scheduled):
        """A pending task past its expiry belonged to a process that is gone; restart it."""
        repository = _repository(task=_task(ManualJobTaskStatus.PENDING, expires_in_seconds=-1))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.json() == {"job_uid": _JOB_UID, "status": "pending"}
        repository.claim_pending_manual_job_task.assert_awaited_once()
        scheduled.assert_awaited_once()

    def test_failed_task_restarts_evaluation(self, client, scheduled):
        """A failed run retries on the next request and the client only ever sees pending."""
        repository = _repository(task=_task(ManualJobTaskStatus.FAILED, expires_in_seconds=-1))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.json() == {"job_uid": _JOB_UID, "status": "pending"}
        repository.claim_pending_manual_job_task.assert_awaited_once()
        scheduled.assert_awaited_once()

    def test_complete_task_is_reported(self, client, scheduled):
        """A finished run reports complete even before the client fetches the letter."""
        repository = _repository(task=_task(ManualJobTaskStatus.COMPLETE, expires_in_seconds=-1))
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.json() == {"job_uid": _JOB_UID, "status": "complete"}
        repository.claim_pending_manual_job_task.assert_not_awaited()
        scheduled.assert_not_awaited()

    def test_lost_claim_reports_the_winning_task(self, client, scheduled):
        """When a concurrent request wins the claim, this one reports without scheduling."""
        repository = _repository(task=None)
        repository.claim_pending_manual_job_task.return_value = None
        repository.get_manual_job_task.side_effect = [
            None,
            _task(ManualJobTaskStatus.PENDING, expires_in_seconds=180),
        ]
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        response = client.post(_URL, json=_payload())

        assert response.json() == {"job_uid": _JOB_UID, "status": "pending"}
        scheduled.assert_not_awaited()

    def test_two_uuids_both_schedule(self, client, scheduled):
        """A new uuid is a new job; duplicate-JD detection is out of scope."""
        repository = _repository(task=None)
        app.dependency_overrides[get_jobs_repository] = lambda: repository

        first = client.post(_URL, json=_payload())
        second = client.post(_URL, json=_payload(job_uid=_OTHER_JOB_UID))

        assert first.json()["job_uid"] == _JOB_UID
        assert second.json()["job_uid"] == _OTHER_JOB_UID
        assert scheduled.await_count == 2


class TestOpenApiContract:
    """The submit trigger is part of the published API surface."""

    def test_submit_path_is_a_post_endpoint(self):
        """Verify OpenAPI exposes POST /jobs/submit."""
        schema = app.openapi()
        assert "post" in schema["paths"]["/jobs/submit"]

    def test_response_status_never_advertises_failed(self):
        """The client-facing status enum stays pending/complete; failures retry silently."""
        schema = app.openapi()
        status_enum = schema["components"]["schemas"]["CoverLetterGenerationStatus"]["enum"]
        assert set(status_enum) == {
            CoverLetterGenerationStatus.PENDING.value,
            CoverLetterGenerationStatus.COMPLETE.value,
        }


class TestPostingFromSubmitRequest:
    """Server-owned JobPosting fields are filled from the request, not the client."""

    def test_source_is_manual_and_uid_is_the_uuid_string(self):
        """Origin lives on source; the uid is the client uuid with no prefix."""
        posting = posting_from_submit_request(_request())
        assert posting.source == MANUAL_JOB_SOURCE
        assert posting.uid == _JOB_UID
        assert posting.title_normalized is None
        assert posting.company_normalized is None


class TestBackgroundSubmitTask:
    """The background run records its own outcome on the task document."""

    async def test_success_persists_job_assessment_and_letter(self, monkeypatch):
        """A successful run upserts the job, stores the assessment, and completes the task."""
        request = _request()
        repository = AsyncMock(spec=MongoJobsRepository)
        repository.get_assessment.return_value = None
        repository.get_user_profile.return_value = make_sample_user_profile()
        repository.get_application_cover_letter_key.return_value = None
        normalized = posting_from_submit_request(request).model_copy(
            update={"title_normalized": "senior engineer", "company_normalized": "acme"}
        )
        dedupe = AsyncMock(spec=DeduplicationAgent)
        dedupe.normalize.return_value = NormalizationResult(processed=[normalized], failed=[])
        assessor = AsyncMock(spec=FitAssessmentAgent)
        assessor.assess.return_value = make_sample_fit_assessment()
        monkeypatch.setattr(
            "job_submit_service.ensure_cv_text",
            AsyncMock(return_value=CVTextArtifact(cv_text="cv", source_sha256=_CV_DIGEST)),
        )
        helper = AsyncMock(return_value=_OBJECT_KEY)
        monkeypatch.setattr("job_submit_service.generate_and_persist_cover_letter", helper)

        await run_manual_job_submit_task(
            username=_USERNAME,
            request=request,
            repository=repository,
            object_storage=MagicMock(spec=ObjectStorage),
            deduplication_agent=dedupe,
            fit_assessment_agent=assessor,
            cv_text_extraction_agent=AsyncMock(spec=CVTextExtractionAgent),
            cover_letter_agent=AsyncMock(spec=CoverLetterGenerationAgent),
        )

        upserted = repository.upsert_jobs.await_args.args[0][0]
        assert upserted.source == MANUAL_JOB_SOURCE
        assert upserted.uid == _JOB_UID
        assert upserted.title_normalized == "senior engineer"
        store = repository.store_assessment.await_args
        assert store.args[2] == _JOB_UID
        assert store.kwargs["job"].uid == _JOB_UID
        helper.assert_awaited_once()
        repository.complete_manual_job_task.assert_awaited_once_with(_USERNAME, _JOB_UID)
        repository.fail_manual_job_task.assert_not_awaited()

    async def test_normalize_failure_does_not_persist(self, monkeypatch):
        """A normalisation miss fails the task and never writes a job or assessment."""
        request = _request()
        posting = posting_from_submit_request(request)
        repository = AsyncMock(spec=MongoJobsRepository)
        dedupe = AsyncMock(spec=DeduplicationAgent)
        dedupe.normalize.return_value = NormalizationResult(
            processed=[],
            failed=[FailedJobPosting(posting=posting, error="no result")],
        )
        monkeypatch.setattr("job_submit_service.generate_and_persist_cover_letter", AsyncMock())

        await run_manual_job_submit_task(
            username=_USERNAME,
            request=request,
            repository=repository,
            object_storage=MagicMock(spec=ObjectStorage),
            deduplication_agent=dedupe,
            fit_assessment_agent=AsyncMock(spec=FitAssessmentAgent),
            cv_text_extraction_agent=AsyncMock(spec=CVTextExtractionAgent),
            cover_letter_agent=AsyncMock(spec=CoverLetterGenerationAgent),
        )

        repository.upsert_jobs.assert_not_awaited()
        repository.store_assessment.assert_not_awaited()
        repository.fail_manual_job_task.assert_awaited_once_with(
            _USERNAME, _JOB_UID, error="no result"
        )
        repository.complete_manual_job_task.assert_not_awaited()

    async def test_existing_assessment_skips_the_assessor(self, monkeypatch):
        """Retry after a persisted assessment must not insert a second row."""
        request = _request()
        repository = AsyncMock(spec=MongoJobsRepository)
        repository.get_assessment.return_value = make_sample_fit_assessment()
        repository.get_user_profile.return_value = make_sample_user_profile()
        repository.get_application_cover_letter_key.return_value = None
        normalized = posting_from_submit_request(request)
        dedupe = AsyncMock(spec=DeduplicationAgent)
        dedupe.normalize.return_value = NormalizationResult(processed=[normalized], failed=[])
        assessor = AsyncMock(spec=FitAssessmentAgent)
        helper = AsyncMock(return_value=_OBJECT_KEY)
        monkeypatch.setattr("job_submit_service.generate_and_persist_cover_letter", helper)
        monkeypatch.setattr("job_submit_service.ensure_cv_text", AsyncMock())

        await run_manual_job_submit_task(
            username=_USERNAME,
            request=request,
            repository=repository,
            object_storage=MagicMock(spec=ObjectStorage),
            deduplication_agent=dedupe,
            fit_assessment_agent=assessor,
            cv_text_extraction_agent=AsyncMock(spec=CVTextExtractionAgent),
            cover_letter_agent=AsyncMock(spec=CoverLetterGenerationAgent),
        )

        assessor.assess.assert_not_awaited()
        repository.store_assessment.assert_not_awaited()
        helper.assert_awaited_once()
        repository.complete_manual_job_task.assert_awaited_once()

    async def test_existing_cover_letter_key_skips_generation(self, monkeypatch):
        """A letter already on the application is not regenerated."""
        request = _request()
        repository = AsyncMock(spec=MongoJobsRepository)
        repository.get_assessment.return_value = make_sample_fit_assessment()
        repository.get_application_cover_letter_key.return_value = _OBJECT_KEY
        normalized = posting_from_submit_request(request)
        dedupe = AsyncMock(spec=DeduplicationAgent)
        dedupe.normalize.return_value = NormalizationResult(processed=[normalized], failed=[])
        helper = AsyncMock()
        monkeypatch.setattr("job_submit_service.generate_and_persist_cover_letter", helper)

        await run_manual_job_submit_task(
            username=_USERNAME,
            request=request,
            repository=repository,
            object_storage=MagicMock(spec=ObjectStorage),
            deduplication_agent=dedupe,
            fit_assessment_agent=AsyncMock(spec=FitAssessmentAgent),
            cv_text_extraction_agent=AsyncMock(spec=CVTextExtractionAgent),
            cover_letter_agent=AsyncMock(spec=CoverLetterGenerationAgent),
        )

        helper.assert_not_awaited()
        repository.complete_manual_job_task.assert_awaited_once_with(_USERNAME, _JOB_UID)

    async def test_agent_error_is_recorded_on_the_task(self, monkeypatch):
        """A failing agent leaves the error on the task instead of raising out of the run."""
        request = _request()
        repository = AsyncMock(spec=MongoJobsRepository)
        dedupe = AsyncMock(spec=DeduplicationAgent)
        dedupe.normalize.side_effect = RuntimeError("llm unavailable")
        monkeypatch.setattr("job_submit_service.generate_and_persist_cover_letter", AsyncMock())

        await run_manual_job_submit_task(
            username=_USERNAME,
            request=request,
            repository=repository,
            object_storage=MagicMock(spec=ObjectStorage),
            deduplication_agent=dedupe,
            fit_assessment_agent=AsyncMock(spec=FitAssessmentAgent),
            cv_text_extraction_agent=AsyncMock(spec=CVTextExtractionAgent),
            cover_letter_agent=AsyncMock(spec=CoverLetterGenerationAgent),
        )

        repository.fail_manual_job_task.assert_awaited_once_with(
            _USERNAME, _JOB_UID, error="llm unavailable"
        )
        repository.complete_manual_job_task.assert_not_awaited()
        repository.upsert_jobs.assert_not_awaited()
