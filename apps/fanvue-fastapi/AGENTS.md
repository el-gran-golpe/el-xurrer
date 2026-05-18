# Fanvue FastAPI Agent Instructions

## Purpose
- This app handles Fanvue OAuth, session handling, media upload orchestration, and post creation.
- Fanvue is the adult-content platform in this repo. Keep Fanvue-specific explicit content separate from Meta/Instagram content.
- These instructions extend the root `AGENTS.md`.
- Do not commit or push changes unless the user explicitly asks for that in the current task.

## Project Map
- `main.py` is the app-local run shim.
- `fanvue_fastapi/main.py` creates the FastAPI app, includes routers, and exposes the demo home page and user endpoint.
- `fanvue_fastapi/config.py` loads shared and per-profile Fanvue OAuth settings.
- `fanvue_fastapi/oauth.py`, `session.py`, `fanvue.py`, `media.py`, and `posts.py` hold service logic.
- `fanvue_fastapi/routes/` contains HTTP route handlers.
- `fanvue_fastapi/schemas/` contains request and response models.
- `tests/` contains this app's test suite.

## Fanvue API Docs
- Fanvue publishes LLM-friendly live docs. Do not vendor them into the repo because they may change.
- For any Fanvue API change, read the latest relevant docs first:
  - Index: `https://api.fanvue.com/docs/llms.txt`
  - Full LLM context: `https://api.fanvue.com/docs/llms-full.txt`
- Use page-specific `.md` docs from the index when changing OAuth, scopes, rate limits, media uploads, post creation, agency endpoints, or webhooks.
- Compare the docs with local modules before editing. The relevant local surfaces are `fanvue_fastapi/oauth.py`, `fanvue_fastapi/media.py`, `fanvue_fastapi/posts.py`, `fanvue_fastapi/fanvue.py`, `shared/fanvue-api-client/fanvue_api_client/`, and `apps/ai-content-pipeline/ai_content_pipeline/integrations/fanvue/`.

## Commands
- Run this app's tests from the repository root: `uv run pytest apps/fanvue-fastapi/tests -q`
- Run a focused test from the repository root: `uv run pytest apps/fanvue-fastapi/tests/test_config.py -q`
- Start the app only when explicitly needed: `uv run python apps/fanvue-fastapi/main.py`
- Run configured checks: `uv run pre-commit run --all-files`
- After making changes, run the relevant focused tests plus `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, and `uv run pytest -q`.

## Safety And Side Effects
- Keep Fanvue API calls, OAuth exchanges, uploads, and token refreshes mocked in tests unless the user explicitly approves live calls.
- Never read, print, commit, or infer values from `apps/fanvue-fastapi/.env`, OAuth client secrets, session secrets, access tokens, refresh tokens, or cookies.
- Do not start a local server or browser OAuth flow unless the task explicitly requires it.
- Do not mix Fanvue adult-content assumptions into Meta/Instagram code paths or tests.

## Testing
- Keep new tests in `apps/fanvue-fastapi/tests/`.
- Organize tests by behavior or module, following the existing names such as `test_config.py`, `test_oauth.py`, `test_session.py`, `test_media.py`, `test_posts.py`, and `test_routes_posts.py`.
- Use unit tests for pure service behavior and route tests for FastAPI request/response behavior.
- Add integration tests only when multiple app layers must be exercised together, and keep external Fanvue calls mocked.
