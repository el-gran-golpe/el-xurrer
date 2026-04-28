# Multi-Profile Fanvue OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `fanvue-fastapi` app support OAuth authentication for multiple independent Fanvue profiles, each with its own `client_id`/`client_secret`, so the CLI can authenticate and refresh tokens for any profile (haru, charly, laura_vigne, etc.).

**Architecture:** Split `Settings` into shared globals and per-profile OAuth credentials. The OAuth library functions become parameterized — they accept `client_id`/`client_secret` rather than reading them from a global singleton. Routes resolve the profile from the existing `?profile=` query param / `oauth_profile` cookie and inject the right credentials per request. The CLI's `FanvueTokenManager` propagates its `profile_name` into the refresh path.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, httpx, pytest, JWT.

---

## Context

The `fanvue-fastapi` app was originally designed for a single Fanvue OAuth app: one `FANVUE_WEBAPP_OAUTH_CLIENT_ID` and one `FANVUE_WEBAPP_OAUTH_CLIENT_SECRET` loaded into a global `Settings` singleton via `@lru_cache`. The CLI now needs to authenticate **multiple independent Fanvue accounts** (each with its own OAuth app registration, since "every Fanvue account is independent").

The CLI flow already passes `?profile=<name>` to `/api/oauth/login`, stores the profile in an `oauth_profile` cookie, and saves tokens via `FanvueTokenManager` to `resources/{profile}/fanvue/tokens.json`. What's missing is the OAuth credential lookup — `oauth.py` still reads one global `client_id`/`client_secret` from `Settings`, so it can't authenticate any profile other than whichever one is in `.env`.

The shared/global settings (`api_base_url`, `base_url`, `oauth_issuer_base_url`, `oauth_redirect_uri`, `session_secret`, `session_cookie_name`, `oauth_scopes`, `oauth_response_mode`, `oauth_prompt`) stay as-is — they are the same for all profiles. The single redirect URI works because every Fanvue OAuth app registers the same URL (`http://localhost:8000/api/oauth/callback`) against the same FastAPI server.

`api_base_url` is shared, so `media.py`, `posts.py`, and `fanvue.py` (apart from token refresh) need no changes — the access token alone identifies which Fanvue account a request acts on.

---

## File Structure

**Modified:**
- `fanvue-fastapi/fanvue_fastapi/config.py` — drop OAuth credentials from `Settings`, add `ProfileOAuthSettings` + `get_profile_oauth_settings()`
- `fanvue-fastapi/fanvue_fastapi/oauth.py` — parameterize `client_id`/`client_secret` on all three functions
- `fanvue-fastapi/fanvue_fastapi/routes/oauth.py` — require `profile`, resolve credentials per request
- `fanvue-fastapi/fanvue_fastapi/session.py` — add `profile` field to `SessionPayload`
- `fanvue-fastapi/fanvue_fastapi/fanvue.py` — propagate `session.profile` into refresh
- `fanvue-fastapi/.env.example` — show per-profile credential vars
- `main_components/fanvue_auth.py` — propagate `profile_name` into refresh wrapper

**Tests modified:**
- `fanvue-fastapi/tests/test_config.py` — drop OAuth-credential assertions, add `ProfileOAuthSettings` tests
- `fanvue-fastapi/tests/test_oauth.py` — update mocks to pass `client_id`/`client_secret`
- `fanvue-fastapi/tests/test_routes_posts.py` — adjust env-var fixture
- `fanvue-fastapi/tests/test_integration.py` — adjust env-var fixture
- `fanvue-fastapi/tests/test_fanvue.py` — pass profile in test sessions

---

## Task 1: Add `ProfileOAuthSettings` and lookup function

**Files:**
- Modify: `fanvue-fastapi/fanvue_fastapi/config.py`
- Test: `fanvue-fastapi/tests/test_config.py`

- [ ] **Step 1: Write failing test for `get_profile_oauth_settings`**

Append to `tests/test_config.py`:

```python
def test_get_profile_oauth_settings_loads_per_profile_vars(monkeypatch):
    monkeypatch.setenv("FANVUE_WEBAPP_HARU_OAUTH_CLIENT_ID", "haru_id")
    monkeypatch.setenv("FANVUE_WEBAPP_HARU_OAUTH_CLIENT_SECRET", "haru_secret")
    monkeypatch.setenv("FANVUE_WEBAPP_CHARLY_OAUTH_CLIENT_ID", "charly_id")
    monkeypatch.setenv("FANVUE_WEBAPP_CHARLY_OAUTH_CLIENT_SECRET", "charly_secret")

    from fanvue_fastapi.config import get_profile_oauth_settings

    get_profile_oauth_settings.cache_clear()
    haru = get_profile_oauth_settings("haru")
    charly = get_profile_oauth_settings("charly")

    assert haru.client_id == "haru_id"
    assert haru.client_secret == "haru_secret"
    assert charly.client_id == "charly_id"
    assert charly.client_secret == "charly_secret"


def test_get_profile_oauth_settings_missing_profile_raises(monkeypatch):
    monkeypatch.delenv("FANVUE_WEBAPP_GHOST_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("FANVUE_WEBAPP_GHOST_OAUTH_CLIENT_SECRET", raising=False)

    from fanvue_fastapi.config import get_profile_oauth_settings, ProfileNotConfiguredError

    get_profile_oauth_settings.cache_clear()
    with pytest.raises(ProfileNotConfiguredError, match="ghost"):
        get_profile_oauth_settings("ghost")


def test_get_profile_oauth_settings_normalizes_case(monkeypatch):
    monkeypatch.setenv("FANVUE_WEBAPP_LAURA_VIGNE_OAUTH_CLIENT_ID", "lv_id")
    monkeypatch.setenv("FANVUE_WEBAPP_LAURA_VIGNE_OAUTH_CLIENT_SECRET", "lv_secret")

    from fanvue_fastapi.config import get_profile_oauth_settings

    get_profile_oauth_settings.cache_clear()
    result = get_profile_oauth_settings("laura_vigne")

    assert result.client_id == "lv_id"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd fanvue-fastapi && pytest tests/test_config.py::test_get_profile_oauth_settings_loads_per_profile_vars -v
```
Expected: FAIL — `cannot import name 'get_profile_oauth_settings'`.

- [ ] **Step 3: Implement `ProfileOAuthSettings` and lookup**

Replace the body of `fanvue_fastapi/config.py` with:

```python
import os
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProfileNotConfiguredError(RuntimeError):
    """Raised when a requested profile has no OAuth credentials configured."""


class Settings(BaseSettings):
    """Shared application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="FANVUE_WEBAPP_",
    )

    # OAuth Configuration (shared across profiles)
    oauth_redirect_uri: str = Field(...)
    oauth_scopes: str = Field(default="")
    oauth_issuer_base_url: str = Field(...)
    oauth_response_mode: str | None = Field(default=None)
    oauth_prompt: str | None = Field(default=None)

    # Session Configuration
    session_secret: str = Field(...)
    session_cookie_name: str = Field(default="fvsession")

    # API Configuration
    api_base_url: str = Field(...)
    base_url: str = Field(...)

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret_length(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("SESSION_SECRET must be at least 16 characters")
        return v


class ProfileOAuthSettings(BaseModel):
    """Per-profile OAuth credentials."""

    client_id: str
    client_secret: str


@lru_cache
def get_settings() -> Settings:
    """Get cached shared settings instance."""
    return Settings()


@lru_cache
def get_profile_oauth_settings(profile_name: str) -> ProfileOAuthSettings:
    """Resolve OAuth credentials for a given profile from environment variables.

    Reads ``FANVUE_WEBAPP_{PROFILE_UPPER}_OAUTH_CLIENT_ID`` and
    ``FANVUE_WEBAPP_{PROFILE_UPPER}_OAUTH_CLIENT_SECRET`` (case-insensitive on the
    profile name).
    """
    prefix = f"FANVUE_WEBAPP_{profile_name.upper()}_OAUTH"
    client_id = os.environ.get(f"{prefix}_CLIENT_ID")
    client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ProfileNotConfiguredError(
            f"OAuth credentials for profile '{profile_name}' not configured. "
            f"Set {prefix}_CLIENT_ID and {prefix}_CLIENT_SECRET in the environment."
        )

    return ProfileOAuthSettings(client_id=client_id, client_secret=client_secret)
```

- [ ] **Step 4: Update existing test_config tests that referenced the dropped fields**

Open `tests/test_config.py` and remove every assertion against `oauth_client_id` / `oauth_client_secret` on `Settings`. Drop the corresponding `monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_ID", ...)` / `..._CLIENT_SECRET` lines from those tests (the fixtures still need to set the surviving fields: redirect URI, issuer URL, etc.). If a test's only purpose was to validate those two fields, delete it.

- [ ] **Step 5: Run all config tests**

```bash
cd fanvue-fastapi && pytest tests/test_config.py -v
```
Expected: PASS for all (including new tests).

- [ ] **Step 6: Commit**

```bash
git add fanvue-fastapi/fanvue_fastapi/config.py fanvue-fastapi/tests/test_config.py
git commit -m "feat(config): add per-profile OAuth credential lookup"
```

---

## Task 2: Parameterize `oauth.py` library functions

**Files:**
- Modify: `fanvue-fastapi/fanvue_fastapi/oauth.py`
- Test: `fanvue-fastapi/tests/test_oauth.py`

- [ ] **Step 1: Update tests to pass credentials explicitly**

In `tests/test_oauth.py`, change every call to `get_authorize_url`, `exchange_code_for_token`, and `refresh_access_token` so the test passes credentials directly. Example pattern for `get_authorize_url`:

```python
url = get_authorize_url(
    state="abc",
    code_challenge="xyz",
    client_id="test_client",
    redirect_uri="http://localhost:8000/api/oauth/callback",
    issuer_base_url="https://auth.fanvue.com",
)
assert "client_id=test_client" in url
```

For `exchange_code_for_token`:

```python
result = await exchange_code_for_token(
    code="test_code",
    code_verifier="test_verifier",
    client_id="test_client",
    client_secret="test_secret",
    redirect_uri="http://localhost:8000/api/oauth/callback",
    issuer_base_url="https://auth.fanvue.com",
)
```

For `refresh_access_token`:

```python
result = await refresh_access_token(
    refresh_token="rt",
    client_id="test_client",
    client_secret="test_secret",
    issuer_base_url="https://auth.fanvue.com",
)
```

Drop any monkeypatching of `FANVUE_WEBAPP_OAUTH_CLIENT_ID` / `..._CLIENT_SECRET` since those settings no longer exist. Keep the env vars for the surviving global settings (issuer URL, redirect URI) where the test still needs `Settings` indirectly — but most oauth tests should now not need `get_settings.cache_clear()` at all.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd fanvue-fastapi && pytest tests/test_oauth.py -v
```
Expected: FAIL — signatures don't match.

- [ ] **Step 3: Rewrite `oauth.py` to accept credentials as parameters**

Replace `fanvue_fastapi/oauth.py` with:

```python
import base64
import hashlib
import secrets
from typing import TypedDict
from urllib.parse import urlencode

import httpx

from fanvue_fastapi.config import get_settings

DEFAULT_SCOPES = "openid offline_access offline"


class OAuthError(Exception):
    """Raised when OAuth operations fail."""


class PKCEResult(TypedDict):
    verifier: str
    challenge: str
    method: str


class TokenResponse(TypedDict, total=False):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
    scope: str
    id_token: str


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def generate_pkce() -> PKCEResult:
    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode()).digest())
    return {"verifier": verifier, "challenge": challenge, "method": "S256"}


def get_authorize_url(
    state: str,
    code_challenge: str,
    client_id: str,
    redirect_uri: str | None = None,
    issuer_base_url: str | None = None,
) -> str:
    settings = get_settings()
    scopes = f"{DEFAULT_SCOPES} {settings.oauth_scopes}".strip()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri or settings.oauth_redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if settings.oauth_response_mode:
        params["response_mode"] = settings.oauth_response_mode
    if settings.oauth_prompt:
        params["prompt"] = settings.oauth_prompt

    issuer = issuer_base_url or settings.oauth_issuer_base_url
    return f"{issuer}/oauth2/auth?{urlencode(params)}"


async def exchange_code_for_token(
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str | None = None,
    issuer_base_url: str | None = None,
) -> TokenResponse:
    settings = get_settings()
    credentials = f"{client_id}:{client_secret}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri or settings.oauth_redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    issuer = issuer_base_url or settings.oauth_issuer_base_url

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{issuer}/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic_auth}",
            },
            data=data,
        )

    if response.status_code != 200:
        raise OAuthError(
            f"Token exchange failed: {response.status_code} {response.text}"
        )
    return response.json()


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    issuer_base_url: str | None = None,
) -> TokenResponse:
    settings = get_settings()
    credentials = f"{client_id}:{client_secret}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    issuer = issuer_base_url or settings.oauth_issuer_base_url

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{issuer}/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic_auth}",
            },
            data=data,
        )

    if response.status_code != 200:
        raise OAuthError(
            f"Token refresh failed: {response.status_code} {response.text}"
        )
    return response.json()
```

- [ ] **Step 4: Run tests**

```bash
cd fanvue-fastapi && pytest tests/test_oauth.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fanvue-fastapi/fanvue_fastapi/oauth.py fanvue-fastapi/tests/test_oauth.py
git commit -m "refactor(oauth): parameterize client_id and client_secret"
```

---

## Task 3: Add `profile` field to `SessionPayload`

**Files:**
- Modify: `fanvue-fastapi/fanvue_fastapi/session.py`
- Test: `fanvue-fastapi/tests/test_session.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_session.py`:

```python
def test_session_payload_round_trip_preserves_profile(monkeypatch):
    monkeypatch.setenv("FANVUE_WEBAPP_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_REDIRECT_URI", "http://localhost:8000/cb")
    monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL", "https://auth.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_API_BASE_URL", "https://api.fanvue.com")
    monkeypatch.setenv("FANVUE_WEBAPP_BASE_URL", "http://localhost:8000")

    from fanvue_fastapi.config import get_settings
    from fanvue_fastapi.session import SessionPayload, create_session_token, verify_session_token

    get_settings.cache_clear()

    payload = SessionPayload(
        access_token="at",
        refresh_token="rt",
        expires_at=1_000_000,
        profile="haru",
    )
    token = create_session_token(payload)
    decoded = verify_session_token(token)

    assert decoded is not None
    assert decoded.profile == "haru"
```

- [ ] **Step 2: Verify test fails**

```bash
cd fanvue-fastapi && pytest tests/test_session.py::test_session_payload_round_trip_preserves_profile -v
```
Expected: FAIL — `profile` field doesn't exist.

- [ ] **Step 3: Add `profile` to `SessionPayload`**

Edit `fanvue_fastapi/session.py`, in the `SessionPayload` class add:

```python
profile: Optional[str] = None
```

…right after the `id_token` field. No other changes needed in this file (Pydantic handles the new optional field on encode/decode).

- [ ] **Step 4: Run session tests**

```bash
cd fanvue-fastapi && pytest tests/test_session.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fanvue-fastapi/fanvue_fastapi/session.py fanvue-fastapi/tests/test_session.py
git commit -m "feat(session): add profile field to SessionPayload"
```

---

## Task 4: Make routes profile-aware

**Files:**
- Modify: `fanvue-fastapi/fanvue_fastapi/routes/oauth.py`
- Modify: `fanvue-fastapi/fanvue_fastapi/fanvue.py`
- Test: `fanvue-fastapi/tests/test_routes_posts.py`, `tests/test_integration.py`, `tests/test_fanvue.py`

- [ ] **Step 1: Update `routes/oauth.py` login to require profile and resolve credentials**

Replace the body of the `login` handler in `fanvue_fastapi/routes/oauth.py` with:

```python
@router.get("/login")
async def login(request: Request, profile: str) -> Response:
    """Initiate OAuth login flow for a specific profile."""
    from fanvue_fastapi.config import (
        get_profile_oauth_settings,
        ProfileNotConfiguredError,
    )

    try:
        profile_oauth = get_profile_oauth_settings(profile)
    except ProfileNotConfiguredError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pkce = generate_pkce()
    state = f"{profile}_{uuid.uuid4()}"

    auth_url = get_authorize_url(
        state=state,
        code_challenge=pkce["challenge"],
        client_id=profile_oauth.client_id,
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    secure = request.url.scheme == "https"

    response.set_cookie(
        key="oauth_state", value=state, httponly=True, secure=secure,
        samesite="lax", max_age=OAUTH_COOKIE_MAX_AGE, path="/",
    )
    response.set_cookie(
        key="oauth_verifier", value=pkce["verifier"], httponly=True, secure=secure,
        samesite="lax", max_age=OAUTH_COOKIE_MAX_AGE, path="/",
    )
    response.set_cookie(
        key="oauth_profile", value=profile, httponly=True, secure=secure,
        samesite="lax", max_age=OAUTH_COOKIE_MAX_AGE, path="/",
    )

    response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response
```

Add `HTTPException` to the imports at the top.

- [ ] **Step 2: Update `routes/oauth.py` callback to resolve credentials from cookie profile**

Replace the body of the `callback` handler with one that requires `profile` from the cookie and uses it for both the token exchange and the session payload. Replace the whole `callback` function (everything between `@router.get("/callback")` and the `@router.post("/logout")` line) with:

```python
@router.get("/callback")
async def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
) -> Response:
    """Handle OAuth callback from Fanvue."""
    from fanvue_fastapi.config import (
        get_profile_oauth_settings,
        ProfileNotConfiguredError,
    )

    settings = get_settings()

    stored_state = request.cookies.get("oauth_state")
    verifier = request.cookies.get("oauth_verifier")
    profile = request.cookies.get("oauth_profile")

    def make_redirect(path: str) -> RedirectResponse:
        response = RedirectResponse(url=f"{settings.base_url}{path}", status_code=302)
        response.delete_cookie("oauth_state", path="/")
        response.delete_cookie("oauth_verifier", path="/")
        response.delete_cookie("oauth_profile", path="/")
        return response

    if error:
        params = f"?error={error}"
        if error_description:
            params += f"&error_description={error_description}"
        return make_redirect(f"/{params}")

    if (
        not code or not state or not stored_state or not verifier or not profile
        or state != stored_state
    ):
        return make_redirect("/?error=oauth_state_mismatch")

    try:
        profile_oauth = get_profile_oauth_settings(profile)
    except ProfileNotConfiguredError:
        return make_redirect("/?error=profile_not_configured")

    try:
        token = await exchange_code_for_token(
            code=code,
            code_verifier=verifier,
            client_id=profile_oauth.client_id,
            client_secret=profile_oauth.client_secret,
        )
    except OAuthError:
        return make_redirect("/?error=oauth_token_exchange_failed")

    # CLI flow: persist tokens to disk and return success page
    import sys
    from pathlib import Path as PathLib

    project_root = PathLib(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from main_components.fanvue_auth import FanvueTokenManager

    manager = FanvueTokenManager(profile)
    manager.save_tokens(dict(token))

    # Web session for any future browser-based UI
    import time
    session = SessionPayload(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_type=token.get("token_type"),
        scope=token.get("scope"),
        id_token=token.get("id_token"),
        expires_at=int(time.time() * 1000) + token["expires_in"] * 1000,
        profile=profile,
    )
    session_token = create_session_token(session)

    response = HTMLResponse(
        content="""
        <html>
            <head><title>Authentication Successful</title></head>
            <body>
                <h1>✓ Authentication Successful</h1>
                <p>You can close this window and return to the CLI.</p>
                <script>setTimeout(() => window.close(), 2000);</script>
            </body>
        </html>
        """,
        status_code=200,
    )
    secure = request.url.scheme == "https"
    response.set_cookie(
        key=settings.session_cookie_name, value=session_token, httponly=True,
        secure=secure, samesite="lax", max_age=SESSION_COOKIE_MAX_AGE, path="/",
    )
    response.delete_cookie("oauth_state", path="/")
    response.delete_cookie("oauth_verifier", path="/")
    response.delete_cookie("oauth_profile", path="/")
    return response
```

- [ ] **Step 3: Update `fanvue.py` to use `session.profile` for refresh**

Replace `ensure_valid_token` in `fanvue_fastapi/fanvue.py`:

```python
async def ensure_valid_token(
    session: SessionPayload,
) -> Tuple[str, Optional[SessionPayload]]:
    from fanvue_fastapi.config import (
        get_profile_oauth_settings,
        ProfileNotConfiguredError,
    )

    updated_session: Optional[SessionPayload] = None
    access_token = session.access_token

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    needs_refresh = (
        now_ms >= session.expires_at - TOKEN_REFRESH_BUFFER_MS
        and session.refresh_token
    )
    if not needs_refresh:
        return access_token, None

    if not session.profile:
        return access_token, None  # Cannot refresh without profile context

    try:
        profile_oauth = get_profile_oauth_settings(session.profile)
    except ProfileNotConfiguredError:
        return access_token, None

    try:
        refreshed = await refresh_access_token(
            session.refresh_token,
            client_id=profile_oauth.client_id,
            client_secret=profile_oauth.client_secret,
        )
        access_token = refreshed.get("access_token", session.access_token)
        updated_session = SessionPayload(
            access_token=access_token,
            refresh_token=refreshed.get("refresh_token", session.refresh_token),
            token_type=refreshed.get("token_type", session.token_type),
            scope=refreshed.get("scope", session.scope),
            id_token=refreshed.get("id_token", session.id_token),
            expires_at=now_ms + refreshed.get("expires_in", 0) * 1000,
            profile=session.profile,
        )
    except OAuthError:
        pass

    return access_token, updated_session
```

- [ ] **Step 4: Update affected route/integration tests**

In `tests/test_routes_posts.py`, `tests/test_integration.py`, and `tests/test_fanvue.py`:

- Drop any `monkeypatch.setenv("FANVUE_WEBAPP_OAUTH_CLIENT_ID", ...)` / `..._CLIENT_SECRET` lines.
- Where a test creates a `SessionPayload`, add `profile="testprofile"`.
- Where a test calls `client.get("/api/oauth/login")` without a profile, change to `client.get("/api/oauth/login?profile=testprofile")` and also set `FANVUE_WEBAPP_TESTPROFILE_OAUTH_CLIENT_ID` / `..._CLIENT_SECRET` in the fixture.
- For tests of `ensure_valid_token`, set `profile="testprofile"` on the session fixtures and configure the env vars.

- [ ] **Step 5: Run all tests**

```bash
cd fanvue-fastapi && pytest -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fanvue-fastapi/fanvue_fastapi/routes/oauth.py fanvue-fastapi/fanvue_fastapi/fanvue.py fanvue-fastapi/tests/
git commit -m "feat(routes): make OAuth and refresh flows profile-aware"
```

---

## Task 5: Propagate profile through the CLI refresh wrapper

**Files:**
- Modify: `main_components/fanvue_auth.py`

`FanvueTokenManager.ensure_valid_token` (line 119-152) calls the local `refresh_access_token` wrapper (line 174-195) which forwards to `fanvue_fastapi.oauth.refresh_access_token`. After Task 2, that downstream function requires `client_id`/`client_secret`, so we need to plumb the profile through.

- [ ] **Step 1: Update the local `refresh_access_token` wrapper to accept a profile**

Replace lines 174-195 of `main_components/fanvue_auth.py` with:

```python
async def refresh_access_token(
    refresh_token: str, profile_name: str
) -> dict[str, Any]:
    """Refresh access token via fanvue_fastapi using profile-specific OAuth credentials."""
    fastapi_path = Path(__file__).parent.parent / "fanvue-fastapi"
    if str(fastapi_path) not in sys.path:
        logger.debug(f"Adding {fastapi_path} to sys.path")
        sys.path.insert(0, str(fastapi_path))

    from fanvue_fastapi.config import get_profile_oauth_settings
    from fanvue_fastapi.oauth import refresh_access_token as oauth_refresh

    profile_oauth = get_profile_oauth_settings(profile_name)
    result = await oauth_refresh(
        refresh_token,
        client_id=profile_oauth.client_id,
        client_secret=profile_oauth.client_secret,
    )
    return dict(result)
```

- [ ] **Step 2: Update `FanvueTokenManager.ensure_valid_token` call site (line 143)**

Change:

```python
new_tokens = await refresh_access_token(tokens["refresh_token"])
```

to:

```python
new_tokens = await refresh_access_token(tokens["refresh_token"], self.profile_name)
```

- [ ] **Step 3: Smoke-test the CLI refresh path manually**

With env vars set for at least one configured profile (e.g. `FANVUE_WEBAPP_LAURA_VIGNE_OAUTH_CLIENT_ID=...`), and a valid `tokens.json` for that profile, run:

```bash
cd /home/moises/repos/gg2/el-xurrer
python -c "
import asyncio
from main_components.fanvue_auth import FanvueTokenManager
m = FanvueTokenManager('laura_vigne')
print(asyncio.run(m.ensure_valid_token())[:20] + '...')
"
```

Expected: prints first 20 chars of a valid access token without raising.

- [ ] **Step 4: Commit**

```bash
git add main_components/fanvue_auth.py
git commit -m "feat(cli): pass profile to fanvue token refresh wrapper"
```

---

## Task 6: Update `.env.example` documentation

**Files:**
- Modify: `fanvue-fastapi/.env.example`

- [ ] **Step 1: Rewrite `.env.example`**

Replace the file contents with:

```dotenv
# ── Per-Profile OAuth Credentials ─────────────────────────────────────────────
# Each Fanvue account has its own OAuth app registration with independent
# client_id / client_secret. Use FANVUE_WEBAPP_<PROFILE>_OAUTH_CLIENT_ID where
# <PROFILE> is the uppercased profile directory name (e.g. resources/haru/ →
# HARU; resources/laura_vigne/ → LAURA_VIGNE).

FANVUE_WEBAPP_HARU_OAUTH_CLIENT_ID=your_haru_client_id
FANVUE_WEBAPP_HARU_OAUTH_CLIENT_SECRET=your_haru_client_secret

FANVUE_WEBAPP_LAURA_VIGNE_OAUTH_CLIENT_ID=your_laura_vigne_client_id
FANVUE_WEBAPP_LAURA_VIGNE_OAUTH_CLIENT_SECRET=your_laura_vigne_client_secret

# ── Shared OAuth Configuration ────────────────────────────────────────────────
FANVUE_WEBAPP_OAUTH_REDIRECT_URI=http://localhost:8000/api/oauth/callback
FANVUE_WEBAPP_OAUTH_SCOPES=read:self
FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL=https://auth.fanvue.com

# ── Session ───────────────────────────────────────────────────────────────────
FANVUE_WEBAPP_SESSION_SECRET=change_this_to_a_secure_random_string_min_16_chars
FANVUE_WEBAPP_SESSION_COOKIE_NAME=fvsession

# ── API ───────────────────────────────────────────────────────────────────────
FANVUE_WEBAPP_API_BASE_URL=https://api.fanvue.com
FANVUE_WEBAPP_BASE_URL=http://localhost:8000
```

- [ ] **Step 2: Commit**

```bash
git add fanvue-fastapi/.env.example
git commit -m "docs: document per-profile OAuth env vars"
```

---

## Verification

End-to-end checks after all tasks complete:

1. **Test suite** — from `fanvue-fastapi/`: `pytest -v` → all pass.
2. **Type check** — from repo root: `mypy .` → clean.
3. **Lint** — from repo root: `ruff check .` and `ruff format --check .` → clean.
4. **Multi-profile auth flow** — with two profiles configured in `.env` (e.g. `HARU` and `LAURA_VIGNE`):
   ```bash
   python -m mains.main fanvue auth -n haru
   python -m mains.main fanvue auth -n laura_vigne
   ```
   Each should open an isolated browser, complete OAuth, and write tokens to `resources/{profile}/fanvue/tokens.json` with the right client.
5. **Multi-profile refresh** — manually expire a `tokens.json` (set `expires_at` to a past timestamp), then run a posting command for that profile (`python -m mains.main fanvue schedule-api -n laura_vigne`); confirm the token gets refreshed with the correct profile credentials and the post succeeds.
6. **Misconfigured profile** — request `/api/oauth/login?profile=ghost` (no env vars set for `GHOST`); expect `400 Bad Request` with a clear error mentioning the missing env var names.
