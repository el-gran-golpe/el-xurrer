# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt  # Install dependencies
uvicorn main:app --reload        # Start dev server
```

## Architecture

This is a **FastAPI** app for building Fanvue OAuth integrations.

### OAuth Flow (PKCE) - To Implement

Reference implementation: `/home/moises/repos/gg2/fanvue-app-starter/` (Next.js version)

```
/api/oauth/login → Fanvue auth → /api/oauth/callback → Home page
```

1. **Login** (`/api/oauth/login`): Generates PKCE challenge, stores state/verifier in cookies, redirects to Fanvue auth
2. **Callback** (`/api/oauth/callback`): Validates state, exchanges code for tokens, creates session
3. **Logout** (`/api/oauth/logout`): Clears session cookie

### Key Modules to Create

- `app/config.py` - Environment validation with Pydantic Settings. All env vars typed and validated at runtime.
- `app/oauth.py` - OAuth helpers: PKCE generation, authorize URL, token exchange, token refresh
- `app/session.py` - JWT-based session in httpOnly cookie using python-jose. Sessions expire in 30 days.
- `app/fanvue.py` - `get_current_user()` fetches `/users/me` from Fanvue API with auto token refresh

### Environment Setup

Create `.env` file. Required variables:
- `OAUTH_CLIENT_ID` - From Fanvue Developer Area
- `OAUTH_CLIENT_SECRET` - From Fanvue Developer Area
- `OAUTH_SCOPES` - Must match scopes configured in Fanvue UI (e.g., `read:self`)
- `OAUTH_REDIRECT_URI` - Full callback URL for your environment
- `SESSION_SECRET` - Min 16 characters for JWT signing

System scopes `openid offline_access offline` are automatically added to configured scopes.

### Fanvue API Endpoints

- Auth URL: `https://www.fanvue.com/oauth/authorize`
- Token URL: `https://www.fanvue.com/oauth/token`
- API Base: `https://www.fanvue.com/api/v1`
- User endpoint: `/users/me`
