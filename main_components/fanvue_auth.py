import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger


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

    def authenticate_profile(self, port: int, timeout: int = 120) -> None:
        """Open browser in an isolated temporary profile for OAuth."""
        auth_url = (
            f"http://localhost:{port}/api/oauth/login?profile={self.profile_name}"
        )

        # Snapshot mtime before browser opens
        mtime_before = (
            self.token_path.stat().st_mtime if self.token_path.exists() else None
        )

        logger.debug("Opening incognito browser for profile {}...", self.profile_name)
        browser_proc, profile_dir = _open_incognito(auth_url)

        try:
            self._wait_for_file(mtime_before, timeout)
        finally:
            logger.debug(
                "Cleaning up incognito browser/profile for profile {}...",
                self.profile_name,
            )
            try:
                browser_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Browser did not exit within 10s for profile {}", self.profile_name
                )
            finally:
                shutil.rmtree(profile_dir, ignore_errors=True)

        logger.success("Profile {} authenticated", self.profile_name)

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

    def _wait_for_file(self, mtime_before: Optional[float], timeout: int = 120) -> None:
        """Poll until tokens.json is created or rewritten by the OAuth callback."""
        start = time.time()
        while time.time() - start < timeout:
            if self.token_path.exists():
                if mtime_before is None:
                    return  # File didn't exist before → first auth done
                if self.token_path.stat().st_mtime > mtime_before:
                    # Copilot suggested me to do this mtime check to account for edge cases
                    # like re-auth after revocation, and re-auth after scope changes
                    return  # File rewritten → re-auth done
            time.sleep(0.5)

        raise TimeoutError(
            f"OAuth timeout: {self.token_path} not created/updated within {timeout}s. "
            f"Please complete the OAuth flow in your browser."
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

    from fanvue_fastapi.oauth import refresh_access_token as oauth_refresh

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


def _open_incognito(url: str) -> tuple[subprocess.Popen, Path]:
    """Open URL in a fresh browser profile to isolate OAuth cookies."""
    # Try Chrome/Chromium first
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        if path := shutil.which(name):
            profile_dir = Path(tempfile.mkdtemp(prefix="fanvue-chromium-"))
            logger.debug(
                "Launching {} with temporary profile {}",
                name,
                profile_dir,
            )
            process = subprocess.Popen(
                [
                    path,
                    f"--user-data-dir={profile_dir}",
                    "--new-window",
                    "--no-first-run",
                    "--no-default-browser-check",
                    url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return process, profile_dir

    # Try Firefox
    for name in ("firefox", "firefox-esr"):
        if path := shutil.which(name):
            profile_dir = Path(tempfile.mkdtemp(prefix="fanvue-firefox-"))
            logger.debug(
                "Launching {} with temporary profile {}",
                name,
                profile_dir,
            )
            process = subprocess.Popen(
                [
                    path,
                    "--no-remote",
                    "--profile",
                    str(profile_dir),
                    "--new-window",
                    url,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return process, profile_dir

    raise AuthError(
        "No supported browser found for isolated Fanvue OAuth login. "
        "Install one of: google-chrome, google-chrome-stable, chromium, "
        "chromium-browser, firefox, firefox-esr. "
        "Fallback to the default browser is disabled because it reuses cookies "
        "across profiles."
    )
