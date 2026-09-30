"""Tests for POST /users/demo-login."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.deps import get_auth0_client
from auth_service import Auth0ClientWrapper
from demo import DEMO_LOGIN_BODY_REJECTED
from main import app
from models.users import LoginResponse

_TOKEN = {
    "access_token": "access",
    "id_token": "id",
    "token_type": "Bearer",
    "expires_in": 86400,
    "refresh_token": "refresh",
}


def _client(auth0: MagicMock) -> TestClient:
    """Serve the app with Auth0 replaced by *auth0* (no lifespan enter)."""
    app.dependency_overrides[get_auth0_client] = lambda: auth0
    return TestClient(app, raise_server_exceptions=False)


def test_demo_login_is_not_found_when_credentials_are_unset(monkeypatch):
    """Deployments that are not hosting the demo must not look like a failed login."""
    monkeypatch.setattr("api.routes.users._demo_login_credentials", lambda: None)
    auth0 = MagicMock(spec=Auth0ClientWrapper)
    client = _client(auth0)
    try:
        response = client.post("/users/demo-login")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    auth0.authenticate.assert_not_called()


def test_demo_login_returns_tokens_from_server_side_password_grant(monkeypatch):
    """The handler authenticates as the configured demo user, never from the client body."""
    monkeypatch.setattr(
        "api.routes.users._demo_login_credentials",
        lambda: ("demo", "server-secret"),
    )
    auth0 = MagicMock(spec=Auth0ClientWrapper)
    auth0.authenticate.return_value = _TOKEN
    client = _client(auth0)
    try:
        response = client.post("/users/demo-login")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    LoginResponse.model_validate(response.json())
    auth0.authenticate.assert_called_once_with(username="demo", password="server-secret")


def test_demo_login_rejects_a_body_that_tries_to_pass_credentials(monkeypatch):
    """The route is not an open proxy for other Auth0 users."""
    monkeypatch.setattr(
        "api.routes.users._demo_login_credentials",
        lambda: ("demo", "server-secret"),
    )
    auth0 = MagicMock(spec=Auth0ClientWrapper)
    client = _client(auth0)
    try:
        response = client.post(
            "/users/demo-login",
            json={"username": "admin", "password": "hunter2"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == DEMO_LOGIN_BODY_REJECTED
    auth0.authenticate.assert_not_called()


def test_demo_login_maps_auth_failure_to_unauthorized(monkeypatch):
    """Auth0 password-grant failures use the same 401 mapping as /users/login."""
    monkeypatch.setattr(
        "api.routes.users._demo_login_credentials",
        lambda: ("demo", "server-secret"),
    )
    auth0 = MagicMock(spec=Auth0ClientWrapper)
    auth0.authenticate.side_effect = ValueError("Wrong email or password.")
    client = _client(auth0)
    try:
        response = client.post("/users/demo-login")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_openapi_exposes_demo_login():
    """The client contract is POST /users/demo-login with a LoginResponse."""
    schema = app.openapi()
    assert "post" in schema["paths"]["/users/demo-login"]
