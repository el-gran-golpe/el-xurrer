# Fanvue FastAPI Agent Instructions

## Scope
- These instructions extend the repository root `AGENTS.md`.
- Treat the root file as the source of truth for shared safety, git workflow, external-service rules, Fanvue/Meta content boundaries, and full-repo verification.
- This file only captures Fanvue FastAPI app-specific orientation.

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
- The root instructions define the required doc sources and comparison workflow.
- App-local Fanvue API surfaces are `fanvue_fastapi/oauth.py`, `fanvue_fastapi/media.py`, `fanvue_fastapi/posts.py`, `fanvue_fastapi/fanvue.py`, and `fanvue_fastapi/routes/`.

## Commands
- Run this app's tests from the repository root: `uv run pytest apps/fanvue-fastapi/tests -q`
- Run a focused test from the repository root: `uv run pytest apps/fanvue-fastapi/tests/test_config.py -q`
- Start the app only when explicitly needed: `uv run python apps/fanvue-fastapi/main.py`

## Local Testing
- Keep new tests in `apps/fanvue-fastapi/tests/`.
- Organize tests by behavior or module, following the existing names such as `test_config.py`, `test_oauth.py`, `test_session.py`, `test_media.py`, `test_posts.py`, and `test_routes_posts.py`.
- Use unit tests for pure service behavior and route tests for FastAPI request/response behavior.
- Add integration tests only when multiple app layers must be exercised together, and keep external Fanvue calls mocked.
