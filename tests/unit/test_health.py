"""Unit tests for the health check endpoints (/healthz and /readyz)."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from api.deps import get_jobs_repository, get_search_service
from main import app
from repository.mongo_jobs_repository import MongoJobsRepository
from search.search_service import SearchService


@pytest.fixture
def client():
    """Create a FastAPI TestClient instance for probing API endpoints."""
    return TestClient(app, raise_server_exceptions=False)


def test_healthz_endpoint(client):
    """Verify that liveness probe /healthz returns 200 OK status."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_endpoint_healthy(client):
    """Verify readiness probe /readyz returns 200 when all backend services are healthy."""
    mock_repo = AsyncMock(spec=MongoJobsRepository)
    mock_repo.ping.return_value = True
    mock_search = AsyncMock(spec=SearchService)
    mock_search.ping.return_value = True

    app.dependency_overrides[get_jobs_repository] = lambda: mock_repo
    app.dependency_overrides[get_search_service] = lambda: mock_search
    try:
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "checks": {"mongodb": "ok", "opensearch": "ok"},
        }
    finally:
        app.dependency_overrides.clear()


def test_readyz_endpoint_unhealthy(client):
    """Verify readiness probe /readyz returns 503 when MongoDB is unreachable."""
    mock_repo = AsyncMock(spec=MongoJobsRepository)
    mock_repo.ping.return_value = False
    mock_search = AsyncMock(spec=SearchService)
    mock_search.ping.return_value = True

    app.dependency_overrides[get_jobs_repository] = lambda: mock_repo
    app.dependency_overrides[get_search_service] = lambda: mock_search
    try:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {
            "status": "unready",
            "checks": {"mongodb": "unreachable", "opensearch": "ok"},
        }
    finally:
        app.dependency_overrides.clear()


def test_readyz_endpoint_opensearch_unhealthy(client):
    """Verify readiness probe /readyz returns 503 when OpenSearch is unreachable."""
    mock_repo = AsyncMock(spec=MongoJobsRepository)
    mock_repo.ping.return_value = True
    mock_search = AsyncMock(spec=SearchService)
    mock_search.ping.return_value = False

    app.dependency_overrides[get_jobs_repository] = lambda: mock_repo
    app.dependency_overrides[get_search_service] = lambda: mock_search
    try:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {
            "status": "unready",
            "checks": {"mongodb": "ok", "opensearch": "unreachable"},
        }
    finally:
        app.dependency_overrides.clear()
