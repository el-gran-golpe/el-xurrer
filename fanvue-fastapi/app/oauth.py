import base64
import hashlib
import secrets
from typing import TypedDict


class PKCEResult(TypedDict):
    verifier: str
    challenge: str
    method: str


def _base64url(data: bytes) -> str:
    """Encode bytes as base64url without padding."""
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_pkce() -> PKCEResult:
    """Generate PKCE verifier and challenge.

    Returns:
        Dict with verifier, challenge, and method (S256)
    """
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode()).digest())
    return {"verifier": verifier, "challenge": challenge, "method": "S256"}
