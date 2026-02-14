import json
import socket

import pytest

from main_components.fanvue_auth import (
    AuthError,
    FanvueTokenManager,
    find_free_port,
    start_fastapi_server,
)


@pytest.fixture
def temp_profile_dir(tmp_path):
    """Create temporary profile directory structure."""
    profile_dir = tmp_path / "resources" / "test_profile" / "fanvue"
    profile_dir.mkdir(parents=True)
    return tmp_path


def test_save_tokens_creates_file(temp_profile_dir):
    """Test that save_tokens creates tokens.json file."""
    # Change to temp directory for test
    import os

    os.chdir(temp_profile_dir)

    manager = FanvueTokenManager("test_profile")

    token_response = {
        "access_token": "test_access",
        "refresh_token": "test_refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid offline",
    }

    manager.save_tokens(token_response)

    assert manager.token_path.exists()
    assert manager.token_path.is_file()


def test_save_tokens_correct_schema(temp_profile_dir):
    """Test that tokens are saved with correct schema."""
    import os

    os.chdir(temp_profile_dir)

    manager = FanvueTokenManager("test_profile")

    token_response = {
        "access_token": "test_access",
        "refresh_token": "test_refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid offline",
    }

    manager.save_tokens(token_response)

    with open(manager.token_path) as f:
        saved = json.load(f)

    assert saved["access_token"] == "test_access"
    assert saved["refresh_token"] == "test_refresh"
    assert saved["token_type"] == "Bearer"
    assert saved["scope"] == "openid offline"
    assert "expires_at" in saved
    assert "created_at" in saved


def test_load_tokens_returns_none_if_not_exists(temp_profile_dir):
    """Test that load_tokens returns None if file doesn't exist."""
    import os

    os.chdir(temp_profile_dir)

    manager = FanvueTokenManager("test_profile")
    assert manager.load_tokens() is None


def test_load_tokens_returns_saved_data(temp_profile_dir):
    """Test that load_tokens returns previously saved tokens."""
    import os

    os.chdir(temp_profile_dir)

    manager = FanvueTokenManager("test_profile")

    token_response = {
        "access_token": "test_access",
        "refresh_token": "test_refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid offline",
    }

    manager.save_tokens(token_response)
    loaded = manager.load_tokens()

    assert loaded is not None
    assert loaded["access_token"] == "test_access"
    assert loaded["refresh_token"] == "test_refresh"


@pytest.mark.asyncio
async def test_ensure_valid_token_raises_if_no_tokens(temp_profile_dir):
    """Test that ensure_valid_token raises AuthError if tokens don't exist."""
    import os

    os.chdir(temp_profile_dir)

    manager = FanvueTokenManager("test_profile")

    with pytest.raises(AuthError, match="not authenticated"):
        await manager.ensure_valid_token()


@pytest.mark.asyncio
async def test_ensure_valid_token_returns_valid_token(temp_profile_dir):
    """Test that ensure_valid_token returns token if not expired."""
    import os

    os.chdir(temp_profile_dir)

    manager = FanvueTokenManager("test_profile")

    # Save token that expires in 1 hour
    token_response = {
        "access_token": "test_access",
        "refresh_token": "test_refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid offline",
    }
    manager.save_tokens(token_response)

    # Should return access token without refresh
    token = await manager.ensure_valid_token()
    assert token == "test_access"


@pytest.mark.asyncio
async def test_ensure_valid_token_refreshes_expired(temp_profile_dir, monkeypatch):
    """Test that ensure_valid_token refreshes expired tokens."""
    import os

    os.chdir(temp_profile_dir)

    manager = FanvueTokenManager("test_profile")

    # Save expired token
    token_response = {
        "access_token": "old_access",
        "refresh_token": "test_refresh",
        "expires_in": -100,  # Already expired
        "token_type": "Bearer",
        "scope": "openid offline",
    }
    manager.save_tokens(token_response)

    # Mock refresh_access_token
    async def mock_refresh(refresh_token):
        return {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    # Monkeypatch the import
    import main_components.fanvue_auth as auth_module

    monkeypatch.setattr(auth_module, "refresh_access_token", mock_refresh)

    # Should refresh and return new token
    token = await manager.ensure_valid_token()
    assert token == "new_access"

    # Verify new token was saved
    loaded = manager.load_tokens()
    assert loaded["access_token"] == "new_access"
    assert loaded["refresh_token"] == "new_refresh"


def test_find_free_port_returns_valid_port():
    """Test that find_free_port returns a valid free port."""
    port = find_free_port()

    assert isinstance(port, int)
    assert 1024 <= port <= 65535

    # Verify port is actually free
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        result = s.connect_ex(("127.0.0.1", port))
        assert result != 0  # Port should not be in use


def test_start_fastapi_server_returns_process_and_port(tmp_path, monkeypatch):
    """Test that start_fastapi_server starts server subprocess."""

    # Mock subprocess.Popen
    class MockPopen:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.stdout = None
            self.stderr = None

    import subprocess

    # Create a variable to capture the instance
    captured_instance = None

    def mock_popen(*args, **kwargs):
        nonlocal captured_instance
        captured_instance = MockPopen(*args, **kwargs)
        return captured_instance

    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    # Mock find_free_port
    monkeypatch.setattr("main_components.fanvue_auth.find_free_port", lambda: 8765)

    process, port = start_fastapi_server()

    assert port == 8765
    assert process is captured_instance
    assert "uvicorn" in captured_instance.args[0]
