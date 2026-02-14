import json

import pytest

from main_components.fanvue_auth import FanvueTokenManager


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
