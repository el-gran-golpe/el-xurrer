import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from loguru import logger


class AuthError(Exception):
    """Raised when authentication operations fail."""

    pass


class FanvueTokenManager:
    """Manages OAuth tokens for a Fanvue profile."""

    def __init__(self, profile_name: str):
        self.profile_name = profile_name
        self.token_path = Path(f"resources/{profile_name}/fanvue/tokens.json")

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
                f"Run: python -m mains.main fanvue auth -p <profile_index>"
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
                f"Please re-authenticate: python -m mains.main fanvue auth -p <profile_index>"
            )


# Add this helper function at module level (outside class)
async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Refresh access token using OAuth refresh flow.

    Args:
        refresh_token: The refresh token

    Returns:
        New token response

    Raises:
        Exception: If refresh fails
    """
    # Import here to avoid circular dependency
    import sys
    from pathlib import Path

    # Add fanvue-fastapi to path
    fastapi_path = Path(__file__).parent.parent / "fanvue-fastapi"
    if str(fastapi_path) not in sys.path:
        sys.path.insert(0, str(fastapi_path))

    from app.oauth import refresh_access_token as oauth_refresh

    return await oauth_refresh(refresh_token)


def find_free_port() -> int:
    """Find a free port for FastAPI server.

    Returns:
        Available port number
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def start_fastapi_server() -> tuple[subprocess.Popen, int]:
    """Start FastAPI server on dynamic port.

    Returns:
        Tuple of (process, port)
    """
    port = find_free_port()

    # Get project root
    project_root = Path(__file__).parent.parent
    fastapi_dir = project_root / "fanvue-fastapi"

    process = subprocess.Popen(
        [
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
