import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Create test client with mocked settings."""
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_ID", "test_client")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv(
        "FANVUE_WEBAPP_OAUTH_REDIRECT_URI", "http://localhost:8000/api/oauth/callback"
    )
    monkeypatch.setenv("FANVUE_WEBAPP_SESSION_SECRET", "test_session_secret_16")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_BASE_URL", "http://localhost:8000")

    from fanvue_fastapi.config import get_settings

    get_settings.cache_clear()

    from main import app

    return TestClient(app)


def test_home_shows_login_link(client):
    """Home page should show login link when not authenticated."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "Login with Fanvue" in response.text


def test_login_redirects_to_fanvue(client):
    """Login endpoint should redirect to Fanvue auth."""
    response = client.get("/api/oauth/login", follow_redirects=False)

    assert response.status_code == 302
    assert "auth.fanvue.com" in response.headers["location"]
    assert "oauth_state" in response.cookies
    assert "oauth_verifier" in response.cookies


def test_callback_rejects_invalid_state(client):
    """Callback should reject mismatched state."""
    # Set a state cookie
    client.cookies.set("oauth_state", "valid_state")
    client.cookies.set("oauth_verifier", "verifier")

    # Call with different state
    response = client.get(
        "/api/oauth/callback?code=test&state=wrong_state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "error=oauth_state_mismatch" in response.headers["location"]


def test_user_endpoint_requires_auth(client):
    """User endpoint should return 401 without session."""
    response = client.get("/api/user")
    assert response.status_code == 401


def test_logout_endpoint_clears_session(client):
    """Logout endpoint should delete session cookie."""
    response = client.post("/api/oauth/logout", follow_redirects=False)

    assert response.status_code == 302
    assert "fvsession" not in response.cookies
    assert response.headers.get("location") == "http://localhost:8000/"
