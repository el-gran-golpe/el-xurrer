# El Xurrer Agent Instructions

## Purpose
- This repository is a Python monorepo with two apps and one shared package.
- The AI content app handles influencer content workflows: planning, generation, scheduling, Instagram publishing, Fanvue publishing orchestration, Google Drive resource sync, ComfyUI image generation, and LLM routing.
- The Fanvue FastAPI app handles Fanvue OAuth, session handling, media upload orchestration, and post creation.
- Treat this file as the shared source of truth for coding agents. Codex and opencode read `AGENTS.md`; Claude Code reads `CLAUDE.md`, which imports this file.
- Do not commit or push changes unless the user explicitly asks for that in the current task.

## Agent Instructions Maintenance
- Treat stale agent instructions as a repository bug. At the start of each task, read the applicable `AGENTS.md` files for the area being changed.
- Before finishing any task that changes behavior, commands, architecture, workflows, safety rules, dependencies, external integrations, or testing expectations, decide whether root or app-specific `AGENTS.md` needs an update.
- Update `AGENTS.md` in the same change when the new knowledge is durable and useful for future agents. Do not update it for one-off debugging notes, transient failures, or information already captured accurately.
- Prefer updating `AGENTS.md` rather than `CLAUDE.md`; this repo's `CLAUDE.md` files import their matching `AGENTS.md` files.
- In the final response, mention whether agent instructions were updated or why no update was needed.

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
- Run the full AI content pipeline for all loaded profiles: `uv run python apps/ai-content-pipeline/main.py all run_all`
- `all run_all` defaults to every loaded profile when no `-p/--profile-indexes` or `-n/--profile-names` selector is passed. Selectors still limit the run.
- `all run_all` clears each selected profile's Meta and Fanvue `outputs/` folders before planning/generation by default. Pass `--keep-local-outputs` only when intentionally reusing existing outputs.

## Model Router Behavior
- GitHub Models (the router's original free provider) was fully retired by GitHub on 2026-07-30. `ModelRouter` now routes through an `LLMProvider` abstraction (`apps/ai-content-pipeline/ai_content_pipeline/llm/routing/providers/`) instead of hardcoding any one provider.
- `ModelRouter` tries an ordered list of provider groups: free providers first, then DeepSeek (paid) last as the final fallback. Today the only free provider is OpenRouter (`OPENROUTER_PROVIDER`); DeepSeek and OpenRouter both implement the OpenAI-compatible chat-completions wire format via the shared `OpenAICompatibleProvider` class.
- Adding another free provider is meant to be cheap: a new `LLMProvider` (or `OpenAICompatibleProvider(...)` instance if it's OpenAI-compatible) plus an entry in `ModelRouter`'s `free_providers` list. Do not special-case a new provider's transport/error-handling inside `ModelRouter` or `ModelClassifier` — that logic is provider-agnostic by design.
- Like GitHub Models before it, each profile/account can define its own key — `OPENROUTER_API_KEY_HARU`, `OPENROUTER_API_KEY_CHARLY`, etc. — summed to increase free-tier quota. `ModelRouter` rotates across a provider's keys independently per provider (a cursor per `provider_id`), retrying the next key on quota exhaustion.
- Model discovery is cache-backed and namespaced per provider: `.cache/model_router/{provider_id}_catalog.json`, `{provider_id}_state_{fingerprint}.json` (per API key), `{provider_id}_capabilities.json` (shared across a provider's keys). On the first run without cache, the router fetches a provider's catalog once and reuses it across all of that provider's keys.
- The catalog fetch is metadata only: model IDs, token limits, and similar fields. Do not reintroduce startup probes that send test prompts to every model, because that is slow and consumes quota.
- During generation, the router tries candidate models lazily, highest-ELO first within a provider, and stops as soon as one model returns a usable response.
- Runtime failures are learned and cached:
  - Rate limits are stored per provider+API-key fingerprint and skipped until cooldown recovery.
  - JSON-mode requests are validated by actually parsing the reply (via `decode_json_from_message`), not just trusting a 200 response — a model that returns malformed JSON despite `response_format=json_object` (common on free/experimental models) is marked as not supporting JSON and the router fails over to the next candidate, same as an explicit 400.
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
- The Meta publishing integration and standalone Page-token exchange helper target Graph API `v25.0`; keep their versions aligned when upgrading Meta API contracts.
- For Meta/Instagram API behavior, use Meta's official Instagram Postman collection as the most practical agent-friendly source for structured requests, parameters, auth/token flows, publishing examples, and response examples: `https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api`.
- For official Meta/Instagram reference material, use the Instagram Platform docs and API Reference first, then the Graph API overview for concepts: `https://developers.facebook.com/docs/instagram-platform/` and `https://developers.facebook.com/docs/graph-api/overview/`. Meta's `developers.facebook.com/llms.txt` is currently more focused on the Marketing API / Ads MCP surface, so do not treat it as the Instagram-specific source of truth.
- Before changing Instagram auth, token handling, permissions, media container creation, `media_publish`, comments, mentions, insights, Graph API versioning, or Facebook CDN staging, read the current Meta docs and compare them with `apps/ai-content-pipeline/ai_content_pipeline/integrations/meta/graph_api.py`, `apps/ai-content-pipeline/ai_content_pipeline/config.py`, and `apps/ai-content-pipeline/ai_content_pipeline/publishing/posting_scheduler.py`.
- Instagram publishing uses the Instagram API with Facebook Login through `graph.facebook.com`, authenticated with per-profile Facebook Page tokens. Each profile must define `{PROFILE}_INSTAGRAM_ACCOUNT_ID`, `{PROFILE}_FACEBOOK_PAGE_ID`, and `{PROFILE}_FACEBOOK_PAGE_ACCESS_TOKEN`; do not reintroduce profile `INSTAGRAM_USER_ACCESS_TOKEN` publishing through `graph.instagram.com`.
- `all run_all` validates each selected profile's Facebook Page token against its configured Instagram account before clearing outputs or starting planning/generation. Publishing also validates internally before upload.
- To obtain profile Page tokens, generate a Facebook User Access Token for the Business app with `pages_show_list`, `pages_read_engagement`, `instagram_basic`, and `instagram_content_publish`, then prefer the standalone exchange helper at `apps/ai-content-pipeline/scripts/exchange_meta_page_token.py`. The helper is intentionally not a CLI: fill in `GRAPH_API_BASE_URL`, `DEFAULT_PROFILE_ALIAS`, `DEFAULT_PAGE_ID`, and `META_APP_ID` inside the `if __name__ == "__main__"` block, run it directly from PyCharm or with `uv run python apps/ai-content-pipeline/scripts/exchange_meta_page_token.py`, and enter the app secret and short-lived user token only through the hidden prompts. The helper exchanges for a long-lived user token, calls `/me/accounts?fields=name,id,access_token,instagram_business_account`, falls back to direct `/{page_id}?fields=name,id,access_token,instagram_business_account` lookup when the configured Page is not listed, validates the Page's linked Instagram account, and writes `{PROFILE}_FACEBOOK_PAGE_ID`, `{PROFILE}_INSTAGRAM_ACCOUNT_ID`, and `{PROFILE}_FACEBOOK_PAGE_ACCESS_TOKEN` to the repository root `.env` regardless of the process working directory.
- For the full human setup flow covering Cloudflare/domain setup, Facebook Page creation, Instagram professional account linking, Meta Business Suite, Meta Developer apps, Graph API Explorer permissions, version caveats, and troubleshooting, use `docs/meta-instagram-page-token-runbook.md`.
- For Fanvue API behavior, use Fanvue's live LLM documentation instead of copying API details into this repo. Start with `https://api.fanvue.com/docs/llms.txt` for the index, and use `https://api.fanvue.com/docs/llms-full.txt` or specific `.md` pages for task details and current request/response contracts.
- Before changing Fanvue auth, media upload, post creation, scheduling, scopes, rate limits, or version headers, read the relevant current Fanvue docs and compare them with `apps/fanvue-fastapi/fanvue_fastapi/`, `shared/fanvue-api-client/fanvue_api_client/`, and `apps/ai-content-pipeline/ai_content_pipeline/integrations/fanvue/`.
- Instagram publishing requires a publicly reachable media URL. This repo intentionally uses `FacebookMediaStager` to upload unpublished photos to the shared Facebook staging Page, read the Facebook CDN URL from the photo `images` payload, and pass that URL to Instagram. This keeps the runtime zero-dollar by avoiding an external storage/CDN service.
- The Facebook staging Page is only a media URL bridge for Instagram. Do not turn it into Facebook cross-posting, do not publish those staging photos, and do not replace this cost-saving flow with paid storage unless the user explicitly asks.
- Instagram Graph API publishing has no native scheduling in this app. Meta scheduling waits asynchronously until each `upload_time`, so running the scheduler can leave the machine sleeping/holding until posts are due.
- `PostingScheduler.upload()` processes every profile in `template_profiles` concurrently (`asyncio.gather` over a per-profile `_upload_profile` coroutine, with one profile's exception logged and isolated from the rest). This applies regardless of caller: `all run_all`, `meta schedule`, and `fanvue schedule` all get concurrent per-profile uploads/scheduling, including Meta's per-profile `_wait_for_time` sleep. Keep new PostingScheduler entry points going through a single instance's `upload()` rather than reintroducing manual per-profile task creation at the call site.
- Fanvue API publishing can pass scheduled `publish_at` timestamps to Fanvue.
- `PostingScheduler._upload_via_fanvue_api` retries a failed publication (media upload + post creation) up to 3 times with linear backoff before giving up and moving to the next day; it does not reuse media UUIDs already uploaded in a failed attempt, so a retry can leave orphaned unused media in the Fanvue vault.
- `httpx` transport-level exceptions (timeouts, connection resets) often have an empty `str()`. Fanvue upload/post error paths (`fanvue_api_client/media.py`, `fanvue_api_client/posts.py`, `posting_scheduler.py`) fall back to the exception type name so failures never log a blank message; keep that fallback when touching these paths.
- `fanvue_api_client/media.py` uses an explicit `UPLOAD_TIMEOUT` (60s) for its `httpx.AsyncClient` calls instead of httpx's 5s default, because multi-megabyte media chunk uploads were hitting spurious `ReadTimeout`s under the default.
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
