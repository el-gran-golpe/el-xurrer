import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Callable
import atexit

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

        logger.debug("Opening isolated browser for profile {}...", self.profile_name)
        browser_proc, profile_dir, atexit_cleanup = _open_isolated_browser(auth_url)

        try:
            self._wait_for_file(mtime_before, timeout)
        finally:
            logger.debug(
                "Cleaning up temporary browser/profile for profile {}...",
                self.profile_name,
            )
            cleaned = _cleanup_browser_and_profile(browser_proc, profile_dir)
            if cleaned:
                try:
                    atexit.unregister(atexit_cleanup)
                except Exception as e:
                    logger.debug(
                        "Could not unregister atexit cleanup for {}: {}",
                        profile_dir,
                        e,
                    )

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
    fastapi_path = Path(__file__).parent.parent / "fanvue-fastapi"

    if str(fastapi_path) not in sys.path:
        logger.debug(f"Adding {fastapi_path} to sys.path")
        sys.path.insert(0, str(fastapi_path))

    from fanvue_fastapi.oauth import refresh_access_token as oauth_refresh

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

    logger.debug(f"Started FastAPI server on port {port}")
    return process, port


def _open_isolated_browser(
    url: str,
) -> tuple[subprocess.Popen, Path, Callable[[], None]]:
    # Try Chrome/Chromium first
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        if path := shutil.which(name):
            profile_dir = Path(tempfile.mkdtemp(prefix="fanvue-chromium-"))
            atexit_cleanup = _register_profile_cleanup(profile_dir)
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
            return process, profile_dir, atexit_cleanup

    # Try Firefox
    for name in ("firefox", "firefox-esr"):
        if path := shutil.which(name):
            profile_dir = Path(tempfile.mkdtemp(prefix="fanvue-firefox-"))
            atexit_cleanup = _register_profile_cleanup(profile_dir)
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
            return process, profile_dir, atexit_cleanup

    raise AuthError(
        "No supported browser found for isolated Fanvue OAuth login. "
        "Install one of: google-chrome, google-chrome-stable, chromium, "
        "chromium-browser, firefox, firefox-esr. "
        "Fallback to the default browser is disabled because it reuses cookies "
        "across profiles."
    )


# ── Utilities ────────────────────────────────────────────────────────────────


def _register_profile_cleanup(profile_dir: Path) -> Callable[[], None]:
    """Register a fallback cleanup for the temporary browser profile."""

    def _cleanup() -> None:
        _cleanup_profile_dir(profile_dir, retries=3, initial_delay=0.5)

    # This atexit.register(_cleanup) will execute when the python interpreter exits, ensuring we
    # attempt to clean up the temp profile even if the user doesn't close the browser or if something
    # goes wrong during cleanup_browser_and_profile.
    atexit.register(_cleanup)
    return _cleanup


def _cleanup_profile_dir(
    profile_dir: Path,
    *,
    retries: int = 5,
    initial_delay: float = 0.5,
) -> bool:
    """Best-effort cleanup of a temporary browser profile directory."""
    if not profile_dir.exists():
        return True

    for attempt in range(1, retries + 1):
        try:
            shutil.rmtree(profile_dir)
            logger.debug("Removed temporary browser profile {}", profile_dir)
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            if attempt == retries:
                logger.warning(
                    "Could not remove temporary browser profile {} after {} attempts: {}",
                    profile_dir,
                    retries,
                    e,
                )
                return False

            sleep_s = initial_delay * attempt
            logger.debug(
                "Profile dir {} still in use; retrying cleanup in {:.1f}s (attempt {}/{})",
                profile_dir,
                sleep_s,
                attempt,
                retries,
            )
            time.sleep(sleep_s)

    return False


def _cleanup_browser_process(process: subprocess.Popen) -> None:
    """Best-effort shutdown of the launched browser process."""
    try:
        if process.poll() is not None:
            return

        logger.debug("Terminating browser process {}", process.pid)
        process.terminate()

        try:
            process.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            logger.debug("Browser process {} did not terminate gracefully", process.pid)

        if process.poll() is None:
            logger.debug("Killing browser process {}", process.pid)
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Browser process {} still did not exit after kill()",
                    process.pid,
                )
    except ProcessLookupError:
        pass
    except Exception as e:
        logger.debug("Ignoring browser cleanup error: {}", e)


def _cleanup_browser_and_profile(
    process: subprocess.Popen,
    profile_dir: Path,
) -> bool:
    """Best-effort cleanup for both browser process and its temp profile."""
    _cleanup_browser_process(process)
    return _cleanup_profile_dir(profile_dir)
