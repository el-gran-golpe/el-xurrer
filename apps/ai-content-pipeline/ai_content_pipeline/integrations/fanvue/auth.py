import shutil
import socket
import subprocess
import sys
import tempfile
import time
import os
from pathlib import Path
from typing import Any, Optional, Callable
import atexit

from loguru import logger

from ai_content_pipeline.config import settings
from ai_content_pipeline.paths import (
    FANVUE_FASTAPI_DIR,
    RESOURCES_DIR,
    SHARED_FANVUE_API_CLIENT_DIR,
)
from fanvue_api_client.oauth import refresh_access_token as refresh_fanvue_access_token
from fanvue_api_client.token_store import FanvueTokenStore


class AuthError(Exception):
    """Raised when authentication operations fail."""

    pass


class FanvueTokenManager:
    """Manages OAuth tokens for a Fanvue profile."""

    def __init__(self, profile_name: str):
        self.profile_name = profile_name
        self.token_store = FanvueTokenStore(profile_name, RESOURCES_DIR)
        self.token_path = self.token_store.token_path

    def authenticate_profile(self, port: int, timeout: int = 60) -> None:
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
        self.token_store.save_tokens(token_response)

    def load_tokens(self) -> dict[str, Any] | None:
        """Load OAuth tokens from profile directory.

        Returns:
            Token data dict or None if file doesn't exist
        """
        return self.token_store.load_tokens()

    def is_expired(self) -> bool:
        """Check if access token is expired.

        Returns:
            True if expired or tokens don't exist
        """
        return self.token_store.is_expired()

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
                "Run: uv run python apps/ai-content-pipeline/main.py fanvue auth "
                f"--profile-names {self.profile_name}"
            )

        # Check if access token is expired (with 60s buffer)
        if time.time() < (tokens["expires_at"] - 60):
            return tokens["access_token"]

        # Attempt refresh
        try:
            logger.debug(f"Refreshing token for profile '{self.profile_name}'...")
            new_tokens = await refresh_access_token(
                tokens["refresh_token"], self.profile_name
            )
            self.save_tokens(new_tokens)
            return new_tokens["access_token"]

        except Exception as e:
            raise AuthError(
                f"Token refresh failed for profile '{self.profile_name}': {e}\n"
                f"Expected token file: {self.token_path}\n"
                "Please re-authenticate: uv run python apps/ai-content-pipeline/main.py "
                f"fanvue auth --profile-names {self.profile_name}"
            )

    def _wait_for_file(self, mtime_before: Optional[float], timeout: int = 120) -> None:
        """Poll until tokens.json is created or rewritten by the OAuth callback."""
        start = time.time()
        while time.time() - start < timeout:
            if self.token_path.exists():
                if mtime_before is None:
                    return  # File didn't exist before → first auth done
                if self.token_path.stat().st_mtime > mtime_before:
                    return  # File rewritten → re-auth done
            time.sleep(0.5)

        raise TimeoutError(
            f"OAuth timeout: {self.token_path} not created/updated within {timeout}s. "
            f"Please complete the OAuth flow in your browser."
        )


# ── OAuth Helpers ─────────────────────────────────────────────────────────────


async def refresh_access_token(refresh_token: str, profile_name: str) -> dict[str, Any]:
    """Refresh access token using profile-specific Fanvue OAuth credentials."""
    profile_oauth = settings.get_fanvue_oauth_credentials(profile_name)
    result = await refresh_fanvue_access_token(
        refresh_token,
        client_id=profile_oauth.client_id,
        client_secret=profile_oauth.client_secret,
        issuer_base_url=settings.fanvue_oauth_issuer_base_url,
    )
    return dict(result)


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_fastapi_server() -> tuple[subprocess.Popen | None, int]:
    """Start FastAPI server if not already running.

    Returns:
        Tuple of (process, port). Process is None if server was already running.
    """
    port = 8000  # FIXME: Fanvue has a callback url in the fanvue_fastapi settings the port is fixed there

    if _is_port_in_use(port):
        logger.info(f"FastAPI server already running on port {port}, reusing it")
        return None, port

    env = os.environ.copy()
    pythonpath = [
        str(FANVUE_FASTAPI_DIR),
        str(SHARED_FANVUE_API_CLIENT_DIR),
        env.get("PYTHONPATH", ""),
    ]
    env["PYTHONPATH"] = os.pathsep.join(part for part in pythonpath if part)

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "fanvue_fastapi.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(FANVUE_FASTAPI_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    logger.debug(f"Started FastAPI server on port {port}")
    return process, port


def _open_isolated_browser(
    url: str,
) -> tuple[subprocess.Popen, Path, Callable[[], None]]:
    """Launch a browser with a fresh temporary profile to avoid cookie cross-contamination.

    Tries Chrome/Chromium first, then Firefox. Raises AuthError if none are found.
    Returns (process, temp_profile_dir, atexit_cleanup_fn).
    """
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
