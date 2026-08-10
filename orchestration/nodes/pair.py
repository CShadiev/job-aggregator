"""Per-(username, job) subgraph nodes."""

from pathlib import Path
from typing import Any

from logger_provider import LoggerProvider
from models.collection_service import JobPosting
from models.failed_tasks import FailedTask, NodeName
from models.fit_assessment import FitAssessment
from models.jobs_api import UpdateJobStatusRequest
from orchestration.deps import PipelineDeps
from orchestration.routing import route_after_assess, route_after_screen
from orchestration.state import PairState, pair_result_summary

log = LoggerProvider.get_logger()


def make_pair_nodes(deps: PipelineDeps) -> dict[str, Any]:
    repository = deps.repository
    object_storage = deps.object_storage
    screening_agent = deps.screening_agent
    fit_assessment_agent = deps.fit_assessment_agent
    cover_letter_agent = deps.cover_letter_agent
    screening_model = deps.screening_model
    thread_id = deps.thread_id
    min_cv_score = deps.cover_letter_min_cv_score

    async def _fail_pair(
        state: PairState,
        *,
        node: NodeName,
        error: Exception,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = state["job"]
        username = state["username"]
        payload = {
            "username": username,
            "job_uid": job.get("uid"),
            **(extra_payload or {}),
        }
        await repository.store_failed_task(
            FailedTask(
                node=node,
                thread_id=thread_id,
                cycle_id=state["cycle_id"],
                error=str(error),
                payload=payload,
            )
        )
        log.exception(
            "Pair node {node} failed for {username}/{job_uid}",
            event="pipeline_pair_error",
            node=node,
            username=username,
            job_uid=job.get("uid"),
            exc_info=True,
        )
        return {"skipped_reason": f"{node}_error: {error}"}

    async def screen(state: PairState) -> dict[str, Any]:
        username = state["username"]
        job = JobPosting.model_validate(state["job"])
        _log = log.bind(event="pipeline_screen", username=username, job_uid=job.uid)

        existing = await repository.get_screening(username, job.uid)
        if existing is not None:
            _log.info("Reusing stored screening")
            return {"screening": existing.model_dump(mode="json")}

        try:
            cv = object_storage.get_user_cv(username)
            result = await screening_agent.screen(cv=cv, job=job)
            await repository.store_screening(
                username=username,
                job_uid=job.uid,
                result=result,
                model=screening_model,
            )
            _log.info(
                "Screened job worth_full_assessment={worth}",
                worth=result.worth_full_assessment,
            )
            return {"screening": result.model_dump(mode="json")}
        except Exception as exc:
            return await _fail_pair(state, node="screen", error=exc)

    async def assess(state: PairState) -> dict[str, Any]:
        username = state["username"]
        job = JobPosting.model_validate(state["job"])
        _log = log.bind(event="pipeline_assess", username=username, job_uid=job.uid)

        existing = await repository.get_assessment(username, job.uid)
        if existing is not None:
            _log.info("Reusing stored assessment")
            return {"assessment": existing.model_dump(mode="json")}

        try:
            profile = await repository.get_user_profile(username)
            if profile is None:
                raise ValueError(f"User profile not found: {username}")
            cv = object_storage.get_user_cv(username)
            assessment = await fit_assessment_agent.assess(
                user_profile=profile, cv=cv, job=job,
            )
            await repository.store_assessment(assessment, username, job.uid)
            _log.info(
                "Assessed job cv_ats_match_score={score}",
                score=assessment.cv_ats_match_score,
            )
            return {"assessment": assessment.model_dump(mode="json")}
        except Exception as exc:
            return await _fail_pair(state, node="assess", error=exc)

    async def cover_letter(state: PairState) -> dict[str, Any]:
        username = state["username"]
        job = JobPosting.model_validate(state["job"])
        _log = log.bind(event="pipeline_cover_letter", username=username, job_uid=job.uid)

        existing_key = await repository.get_application_cover_letter_key(username, job.uid)
        if existing_key:
            _log.info("Reusing existing cover letter")
            return {"cover_letter_key": existing_key}

        assessment_data = state.get("assessment")
        if assessment_data is None:
            stored = await repository.get_assessment(username, job.uid)
            if stored is None:
                return await _fail_pair(
                    state,
                    node="cover_letter",
                    error=ValueError("assessment missing for cover letter"),
                )
            assessment = stored
        else:
            assessment = FitAssessment.model_validate(assessment_data)

        file_path = Path("tmp") / Path(username) / f"{job.uid}.json"
        try:
            profile = await repository.get_user_profile(username)
            if profile is None:
                raise ValueError(f"User profile not found: {username}")

            _log.info("Generating cover letter")
            content = await cover_letter_agent.generate(profile, job, assessment)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content.model_dump_json(indent=2))
            object_key = object_storage.upload_coverletter_json(
                username=username, job_id=job.uid, file_path=str(file_path),
            )
            await repository.update_job_application_status(
                job_uid=job.uid,
                username=username,
                request=UpdateJobStatusRequest(cover_letter_key=object_key),
            )
            _log.info("Cover letter stored")
            return {"cover_letter_key": object_key}
        except Exception as exc:
            return await _fail_pair(state, node="cover_letter", error=exc)
        finally:
            if file_path.exists():
                file_path.unlink()

    async def emit_pair_result(state: PairState) -> dict[str, Any]:
        return {"pair_results": [pair_result_summary(state)]}

    def route_screen(state: PairState) -> str:
        return route_after_screen(state)

    def route_assess(state: PairState) -> str:
        return route_after_assess(state, min_cv_score=min_cv_score)

    return {
        "screen": screen,
        "assess": assess,
        "cover_letter": cover_letter,
        "emit_pair_result": emit_pair_result,
        "route_screen": route_screen,
        "route_assess": route_assess,
    }
