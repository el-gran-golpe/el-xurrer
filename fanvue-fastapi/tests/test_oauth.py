import base64
import hashlib


def test_generate_pkce_returns_verifier_and_challenge():
    """PKCE generation should return verifier, challenge, and method."""
    from app.oauth import generate_pkce

    result = generate_pkce()

    assert "verifier" in result
    assert "challenge" in result
    assert result["method"] == "S256"


def test_generate_pkce_challenge_is_sha256_of_verifier():
    """Challenge should be base64url(SHA256(verifier))."""
    from app.oauth import generate_pkce

    result = generate_pkce()
    verifier = result["verifier"]
    challenge = result["challenge"]

    # Manually compute expected challenge
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    assert challenge == expected


def test_generate_pkce_verifier_is_unique():
    """Each call should generate a unique verifier."""
    from app.oauth import generate_pkce

    result1 = generate_pkce()
    result2 = generate_pkce()

    assert result1["verifier"] != result2["verifier"]
