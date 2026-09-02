from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient

from api.deps import get_jobs_repository
from main import app
from repository.mongo_jobs_repository import MongoJobsRepository


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_healthz_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_endpoint_healthy(client):
    mock_repo = AsyncMock(spec=MongoJobsRepository)
    mock_repo.ping.return_value = True

    app.dependency_overrides[get_jobs_repository] = lambda: mock_repo
    try:
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "checks": {"mongodb": "ok"}}
    finally:
        app.dependency_overrides.clear()


def test_readyz_endpoint_unhealthy(client):
    mock_repo = AsyncMock(spec=MongoJobsRepository)
    mock_repo.ping.return_value = False

    app.dependency_overrides[get_jobs_repository] = lambda: mock_repo
    try:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {"status": "unready", "checks": {"mongodb": "unreachable"}}
    finally:
        app.dependency_overrides.clear()
