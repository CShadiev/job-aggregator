from typing import Any
from fastapi import APIRouter, Response, status

from api.deps import AppJobsRepository
from logger_provider import LoggerProvider

router = APIRouter(tags=["health"])
log = LoggerProvider.get_logger()


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz() -> dict[str, str]:
    """
    Liveness probe endpoint.
    Returns 200 OK immediately if the FastAPI process is responsive.
    """
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(jobs_repository: AppJobsRepository, response: Response) -> dict[str, Any]:
    """
    Readiness probe endpoint.
    Verifies that required backend dependencies (e.g. MongoDB) are healthy and ready to accept traffic.
    """
    mongo_healthy = await jobs_repository.ping()
    checks = {
        "mongodb": "ok" if mongo_healthy else "unreachable",
    }
    all_ready = all(check_status == "ok" for check_status in checks.values())

    if not all_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "checks": checks}

    return {"status": "ready", "checks": checks}
