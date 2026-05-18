import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FanvueTokenStore:
    profile_name: str
    resources_root: Path

    @property
    def token_path(self) -> Path:
        return self.resources_root / self.profile_name / "fanvue" / "tokens.json"

    def save_tokens(self, token_response: dict[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)

        now = int(time.time())
        token_data = {
            "access_token": token_response["access_token"],
            "refresh_token": token_response["refresh_token"],
            "expires_at": now + token_response["expires_in"],
            "token_type": token_response.get("token_type", "Bearer"),
            "scope": token_response.get("scope", ""),
            "created_at": now,
        }

        self.token_path.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
        os.chmod(self.token_path, 0o600)

    def load_tokens(self) -> dict[str, Any] | None:
        if not self.token_path.exists():
            return None
        return json.loads(self.token_path.read_text(encoding="utf-8"))

    def is_expired(self) -> bool:
        tokens = self.load_tokens()
        if not tokens:
            return True
        return time.time() >= (tokens["expires_at"] - 60)
