import json
import os
import time
from pathlib import Path
from typing import Any


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
