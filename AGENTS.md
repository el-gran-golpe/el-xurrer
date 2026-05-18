# El Xurrer Agent Instructions

## Purpose
- This repository is a Python monorepo with two apps and one shared package.
- The AI content app handles influencer content workflows: planning, generation, scheduling, Instagram publishing, Fanvue publishing orchestration, Google Drive resource sync, ComfyUI image generation, and LLM routing.
- The Fanvue FastAPI app handles Fanvue OAuth, session handling, media upload orchestration, and post creation.
- Treat this file as the shared source of truth for coding agents. Codex and opencode read `AGENTS.md`; Claude Code reads `CLAUDE.md`, which imports this file.
- Do not commit or push changes unless the user explicitly asks for that in the current task.

## Project Map
- `pyproject.toml` is the source of truth for dependencies and tool configuration for `uv`, Ruff, mypy, and pytest.
- `.pre-commit-config.yaml` runs the same `uv run ...` quality commands that agents should run manually.
- `apps/ai-content-pipeline/` contains the AI content Typer app, its app-local entrypoint, tests, README, and app-specific agent instructions.
- `apps/ai-content-pipeline/ai_content_pipeline/cli/` contains Typer command modules and orchestration helpers.
- `apps/ai-content-pipeline/ai_content_pipeline/domain/`, `profiles/`, `planning/`, `generation/`, and `publishing/` contain domain models and workflow services.
- `apps/ai-content-pipeline/ai_content_pipeline/integrations/` contains adapters for Google Drive, Meta/Instagram, Fanvue publishing, and ComfyUI.
- `apps/ai-content-pipeline/ai_content_pipeline/llm/` contains LLM wrappers, routing, classification, prompt utilities, and API error handling.
- `apps/fanvue-fastapi/` contains the Fanvue FastAPI app, tests, README, and app-specific agent instructions.
- `shared/fanvue-api-client/` contains shared Fanvue OAuth, media upload, post creation, and token-store primitives used by both apps.
- Runtime profile resources live under `resources/`, which is gitignored. Profile details are organized by profile and platform, with `inputs/` for source prompt data and `outputs/` for local generated planning/publication artifacts.
- Do not add root-level app code or root-level test folders. Root files should be workspace-wide config or documentation only.

## Commands
- Install/sync dependencies: `uv sync`
- Run Ruff formatting: `uv run ruff format .`
- Check Ruff formatting: `uv run ruff format --check .`
- Run Ruff linting: `uv run ruff check .`
- Run mypy: `uv run mypy`
- Run all tests: `uv run pytest -q`
- Run all configured checks: `uv run pre-commit run --all-files`
- Run the AI content CLI: `uv run python apps/ai-content-pipeline/main.py --help`
- Run Fanvue FastAPI locally only when needed: `uv run python apps/fanvue-fastapi/main.py`

## Model Router Behavior
- `ModelRouter` uses GitHub Models first, then falls back to DeepSeek if GitHub candidates fail.
- GitHub model discovery is cache-backed. On the first run without cache, the router fetches the GitHub Models catalog once and stores it under `.cache/model_router/github_models_catalog.json`.
- The catalog fetch is metadata only: model IDs, token limits, and similar fields. Do not reintroduce startup probes that send test prompts to every model, because that is slow and consumes quota.
- During generation, the router tries candidate models lazily. It stops as soon as one model returns a usable response.
- Runtime failures are learned and cached:
  - Rate limits are stored per GitHub API key fingerprint and skipped until cooldown recovery.
  - JSON-mode bad requests mark that model as not supporting JSON, so future JSON prompts skip it.
- The cache refreshes automatically after 24 hours. Planning commands can force refresh with `--refresh-model-cache`.
- Prompt files are processed as sequential prompt items, not one persistent API conversation. Continuity comes from local `cache_key` placeholder substitution between prompts.

## Resources And Sync
- Google Drive is used as a simple sync source of truth for managed profile inputs.
- The Drive sync contract covers only each profile workflow JSON plus each platform's flat `inputs/initial_conditions.md` and `inputs/{profile}.json`.
- Google Drive push is not append-only. For locally pushed profile folders, `GoogleDriveSync.push()` deletes remote files and folders outside the sync contract, while preserving valid remote profile folders that are not part of the local push.
- Generated images, captions, planning files, publication folders, and other assets under `outputs/` are local runtime artifacts. Do not assume they are committed or synced to Drive.
- Do not inspect or modify `resources/` unless the task explicitly requires profile/resource work.
- Do not edit `resources/*/*/inputs/initial_conditions.md` or `resources/*/*/inputs/{profile}.json` without explicit user approval. These files define persona/profile setup and prompt behavior.

## Content And Platform Rules
- Meta/Instagram content must be safe for work.
- Fanvue content is adult-oriented and may be explicit. Preserve prompt metadata such as `is_sensitive_content`; the model router uses it to avoid censored models when needed.
- Do not move content expectations between platforms. Meta prompts, captions, and generated assets must stay Instagram-safe; Fanvue-specific explicit content belongs only in Fanvue resources and outputs.
- For Meta/Instagram API behavior, use Meta's official Instagram Postman collection as the most practical agent-friendly source for structured requests, parameters, auth/token flows, publishing examples, and response examples: `https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api`.
- For official Meta/Instagram reference material, use the Instagram Platform docs and API Reference first, then the Graph API overview for concepts: `https://developers.facebook.com/docs/instagram-platform/` and `https://developers.facebook.com/docs/graph-api/overview/`. Meta's `developers.facebook.com/llms.txt` is currently more focused on the Marketing API / Ads MCP surface, so do not treat it as the Instagram-specific source of truth.
- Before changing Instagram auth, token handling, permissions, media container creation, `media_publish`, comments, mentions, insights, Graph API versioning, or Facebook CDN staging, read the current Meta docs and compare them with `apps/ai-content-pipeline/ai_content_pipeline/integrations/meta/graph_api.py`, `apps/ai-content-pipeline/ai_content_pipeline/config.py`, and `apps/ai-content-pipeline/ai_content_pipeline/publishing/posting_scheduler.py`.
- For Fanvue API behavior, use Fanvue's live LLM documentation instead of copying API details into this repo. Start with `https://api.fanvue.com/docs/llms.txt` for the index, and use `https://api.fanvue.com/docs/llms-full.txt` or specific `.md` pages for task details and current request/response contracts.
- Before changing Fanvue auth, media upload, post creation, scheduling, scopes, rate limits, or version headers, read the relevant current Fanvue docs and compare them with `apps/fanvue-fastapi/fanvue_fastapi/`, `shared/fanvue-api-client/fanvue_api_client/`, and `apps/ai-content-pipeline/ai_content_pipeline/integrations/fanvue/`.
- Instagram publishing requires a publicly reachable media URL. This repo intentionally uses `FacebookMediaStager` to upload unpublished photos to the shared Facebook staging Page, read the Facebook CDN URL from the photo `images` payload, and pass that URL to Instagram. This keeps the runtime zero-dollar by avoiding an external storage/CDN service.
- The Facebook staging Page is only a media URL bridge for Instagram. Do not turn it into Facebook cross-posting, do not publish those staging photos, and do not replace this cost-saving flow with paid storage unless the user explicitly asks.
- Instagram Graph API publishing has no native scheduling in this app. Meta scheduling waits asynchronously until each `upload_time`, so running the scheduler can leave the machine sleeping/holding until posts are due.
- Fanvue API publishing can pass scheduled `publish_at` timestamps to Fanvue.
- Use ISO 8601 `upload_time` values with an explicit timezone offset, preferably UTC with `Z`. The scheduler accepts `Z` by converting it to `+00:00`; naive datetimes are interpreted using the machine's local timezone and should be avoided.
- Usual operating cadence is weekly: generate a Monday-to-Sunday content batch. The Sunday regeneration run should produce the next Monday-to-Sunday batch, not rewrite the week that just finished.

## Safety And Side Effects
- Ask before running commands that touch external services or local generated assets, including Google Drive sync, ComfyUI generation, Meta/Instagram calls, Fanvue API calls, OAuth flows, token validation, uploads, scheduling, or publishing.
- AI content CLI commands such as `uv run python apps/ai-content-pipeline/main.py meta ...` and `uv run python apps/ai-content-pipeline/main.py all ...` load profiles and may pull from Google Drive before executing the requested command.
- Never read, print, commit, or infer secrets from `.env`, token files, OAuth credentials, Instagram access tokens, Fanvue credentials, Google Drive credentials, or generated media/resource outputs.
- Do not modify influencer personas, prompts, profile resources, generated assets, content safety level, or publishing schedules unless the task explicitly asks for it.
- Keep external API interactions mocked in tests unless the user explicitly approves live calls.

## Coding Standards
- Follow the existing Python style and module boundaries. Prefer small, focused changes over broad refactors.
- Use Pydantic models and validators for structured data rather than ad hoc dict or string handling.
- Keep Typer CLI behavior explicit and preserve existing option names unless the task is a CLI migration.
- Preserve async boundaries in publishing and FastAPI code. Do not hide blocking network calls inside async flows without a clear reason.
- Keep logging through `loguru` in the AI content app.
- Do not add large generated files, media outputs, credentials, resource snapshots, or cache directories to git.
- Do not reintroduce `requirements.txt`, `pytest.ini`, `mypy.ini`, or app-level dependency files unless the user explicitly asks. Use `pyproject.toml`.

## Tests
- Add or update tests for behavior you change when practical.
- Keep AI content tests inside `apps/ai-content-pipeline/tests/`.
- Keep Fanvue FastAPI tests inside `apps/fanvue-fastapi/tests/`.
- Keep shared Fanvue client tests inside `shared/fanvue-api-client/tests/`.
- Put unit tests close to the subsystem they exercise. Use app/package `tests/integration/` folders only for cross-component behavior.
- Mock filesystem, network, OAuth, Google Drive, Meta, Fanvue, and ComfyUI boundaries by default.
- After changes, run the relevant focused tests plus the configured checks: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, and `uv run pytest -q`. For a final full gate, run `uv run pre-commit run --all-files`.
- If a verification command fails because of a pre-existing issue, report the exact command and failure instead of hiding it.

## Git Workflow
- Work in the current branch unless the user asks for a branch or worktree.
- Do not commit, push, merge, rebase, reset, or discard user changes unless the user explicitly asks.
- Before editing a file, check whether it already has unrelated local changes. Preserve user edits and avoid mixing unrelated cleanup into the task.
- If the task requires a commit later, use a focused commit message and include only files relevant to the task.
