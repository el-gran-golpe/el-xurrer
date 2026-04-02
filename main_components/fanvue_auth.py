import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

from loguru import logger

from fanvue_fastapi.oauth import refresh_access_token as oauth_refresh


class AuthError(Exception):
    """Raised when authentication operations fail."""

    pass


class FanvueTokenManager:
    """Manages OAuth tokens for a Fanvue profile."""

    def __init__(self, profile_name: str):
        self.profile_name = profile_name
        project_root = Path(__file__).parent.parent
        self.token_path = (
            project_root / "resources" / profile_name / "fanvue" / "tokens.json"
        )

    def save_tokens(self, token_response: dict[str, Any]) -> None:
        """Save OAuth tokens to profile directory.

        Args:
            token_response: Token response from OAuth exchange
                Must contain: access_token, refresh_token, expires_in
        """
        # Ensure directory exists
        self.token_path.parent.mkdir(parents=True, exist_ok=True)

        # Calculate expiry timestamp
        now = int(time.time())
        expires_at = now + token_response["expires_in"]

        # Build token data
        token_data = {
            "access_token": token_response["access_token"],
            "refresh_token": token_response["refresh_token"],
            "expires_at": expires_at,
            "token_type": token_response.get("token_type", "Bearer"),
            "scope": token_response.get("scope", ""),
            "created_at": now,
        }

        # Write to file with restrictive permissions
        self.token_path.write_text(json.dumps(token_data, indent=2))
        os.chmod(self.token_path, 0o600)  # Owner read/write only

    def load_tokens(self) -> dict[str, Any] | None:
        """Load OAuth tokens from profile directory.

        Returns:
            Token data dict or None if file doesn't exist
        """
        if not self.token_path.exists():
            return None

        with open(self.token_path) as f:
            return json.load(f)

    def is_expired(self) -> bool:
        """Check if access token is expired.

        Returns:
            True if expired or tokens don't exist
        """
        tokens = self.load_tokens()
        if not tokens:
            return True

        # Add 60s buffer
        return time.time() >= (tokens["expires_at"] - 60)

    async def ensure_valid_token(self) -> str:
        """Get valid access token, refreshing if needed.

        Returns:
            Valid access_token

        Raises:
            AuthError: If refresh fails or tokens don't exist
        """
        tokens = self.load_tokens()
        if not tokens:
            raise AuthError(
                f"Profile '{self.profile_name}' not authenticated.\n"
                f"Expected token file: {self.token_path}\n"
                f"Run: ./.venv/bin/python main.py fanvue auth --profile-names {self.profile_name}"
            )

        # Check if access token is expired (with 60s buffer)
        if time.time() < (tokens["expires_at"] - 60):
            return tokens["access_token"]

        # Attempt refresh
        try:
            logger.debug(f"Refreshing token for profile '{self.profile_name}'...")
            new_tokens = await refresh_access_token(tokens["refresh_token"])
            self.save_tokens(new_tokens)
            return new_tokens["access_token"]

        except Exception as e:
            raise AuthError(
                f"Token refresh failed for profile '{self.profile_name}': {e}\n"
                f"Expected token file: {self.token_path}\n"
                f"Please re-authenticate: ./.venv/bin/python main.py fanvue auth --profile-names {self.profile_name}"
            )


# ── OAuth Helpers ─────────────────────────────────────────────────────────────


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Refresh access token using OAuth refresh flow.

    Args:
        refresh_token: The refresh token

    Returns:
        New token response

    Raises:
        Exception: If refresh fails
    """

    # Add fanvue-fastapi to path
    fastapi_path = Path(__file__).parent.parent / "fanvue-fastapi"
    logger.debug(f"Fastapi PATH: {fastapi_path}")
    if str(fastapi_path) not in sys.path:
        logger.debug(f"Adding {fastapi_path} to sys.path")
        sys.path.insert(0, str(fastapi_path))

    result = await oauth_refresh(refresh_token)
    return dict(result)  # Convert TypedDict to dict for type safety


# ── Server & Browser ─────────────────────────────────────────────────────────


def start_fastapi_server() -> tuple[subprocess.Popen, int]:
    """Start FastAPI server on dynamic port.

    Returns:
        Tuple of (process, port)
    """
    port = 8000  # FIXME: Fanvue has a callback url in the fanvue_fastapi settings the port is fixed there

    # Get project root
    project_root = Path(__file__).parent.parent
    fastapi_dir = project_root / "fanvue-fastapi"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(fastapi_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    logger.info(f"Started FastAPI server on port {port}")
    return process, port


def authenticate_profile(profile_name: str, port: int, timeout: int = 120) -> None:
    """Open browser in incognito mode for OAuth and wait for token file.

    Raises:
        TimeoutError: If OAuth not completed within timeout
    """
    auth_url = f"http://localhost:{port}/api/oauth/login?profile={profile_name}"
    logger.debug("Opening incognito browser for profile {}...", profile_name)
    _open_incognito(auth_url)

    # Wait for tokens.json to be created (polling)
    project_root = Path(__file__).parent.parent
    token_path = project_root / "resources" / profile_name / "fanvue" / "tokens.json"
    _wait_for_file(token_path, timeout=timeout)

    logger.success("Profile {} authenticated", profile_name)


# ── Browser-based OAuth Flow ─────────────────────────────────────────────────
# _open_incognito and _wait_for_file are internal helpers for authenticate_profile.


def _open_incognito(url: str) -> None:
    """Open URL in an incognito/private browser window."""
    import shutil

    # Try Chrome/Chromium first
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        path = shutil.which(name)
        if path:
            subprocess.Popen(
                [path, "--incognito", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

    # Try Firefox
    for name in ("firefox", "firefox-esr"):
        path = shutil.which(name)
        if path:
            subprocess.Popen(
                [path, "--private-window", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

    # Fallback: default browser (no incognito guarantee)
    logger.warning(
        "No supported browser found for incognito mode, using default browser"
    )
    webbrowser.open(url)


def _wait_for_file(file_path: Path, timeout: int = 120) -> None:
    """Poll for file existence with timeout.

    Args:
        file_path: Path to wait for
        timeout: Max seconds to wait

    Raises:
        TimeoutError: If file not created within timeout
    """
    start = time.time()
    while time.time() - start < timeout:
        if file_path.exists():
            return
        time.sleep(0.5)

    raise TimeoutError(
        f"OAuth timeout: {file_path} not created within {timeout}s. "
        f"Please complete the OAuth flow in your browser."
    )
