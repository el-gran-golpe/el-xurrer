# El Xurrer Agent Instructions

## Purpose
- This repository is a Python automation tool for AI influencer content workflows: planning, generation, scheduling, Instagram publishing, Fanvue publishing, Google Drive resource sync, ComfyUI image generation, and LLM routing.
- Treat this file as the shared source of truth for coding agents. Codex and opencode read `AGENTS.md`; Claude Code reads `CLAUDE.md`, which imports this file.
- Do not commit or push changes unless the user explicitly asks for that in the current task.

## Project Map
- `main.py` defines the top-level Typer CLI and wires `meta`, `fanvue`, and `all` commands.
- `mains/commands/` contains CLI command modules and orchestration helpers.
- `main_components/` contains planning, generation, scheduling, config, profile validation, and common domain types.
- `automation/` contains external service clients for Google Drive, Meta/Instagram, and Fanvue.
- `generation_tools/` contains media generation integrations such as ComfyUI.
- `llm/` contains LLM wrappers, routing, classification, prompt utilities, and API error handling. `ModelRouter` tries GitHub Models candidates first to use the GitHub free tier as much as possible, then falls back to DeepSeek.
- `fanvue-fastapi/` is a nested FastAPI app with its own dependencies, tests, and agent instructions.
- Runtime profile resources live under `resources/`, which is gitignored. Profile details are organized there by profile and platform, with `inputs/` for source prompt data and `outputs/` for local generated planning/publication artifacts.

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
- Before changing Instagram auth, token handling, permissions, media container creation, `media_publish`, comments, mentions, insights, Graph API versioning, or Facebook CDN staging, read the current Meta docs and compare them with `automation/meta_api/graph_api.py`, `main_components/config.py`, and `main_components/posting_scheduler.py`.
- For Fanvue API behavior, use Fanvue's live LLM documentation instead of copying API details into this repo. Start with `https://api.fanvue.com/docs/llms.txt` for the index, and use `https://api.fanvue.com/docs/llms-full.txt` or specific `.md` pages for task details and current request/response contracts.
- Before changing Fanvue auth, media upload, post creation, scheduling, scopes, rate limits, or version headers, read the relevant current Fanvue docs and compare them with the local wrappers in `fanvue-fastapi/` and `automation/fanvue_client/`.
- Instagram publishing requires a publicly reachable media URL. This repo intentionally uses `FacebookMediaStager` to upload unpublished photos to the shared Facebook staging Page, read the Facebook CDN URL from the photo `images` payload, and pass that URL to Instagram. This keeps the runtime zero-dollar by avoiding an external storage/CDN service.
- The Facebook staging Page is only a media URL bridge for Instagram. Do not turn it into Facebook cross-posting, do not publish those staging photos, and do not replace this cost-saving flow with paid storage unless the user explicitly asks.
- Instagram Graph API publishing has no native scheduling in this app. Meta scheduling waits asynchronously until each `upload_time`, so running the scheduler can leave the machine sleeping/holding until posts are due.
- Fanvue API publishing can pass scheduled `publish_at` timestamps to Fanvue.
- Use ISO 8601 `upload_time` values with an explicit timezone offset, preferably UTC with `Z`. The scheduler accepts `Z` by converting it to `+00:00`; naive datetimes are interpreted using the machine's local timezone and should be avoided.
- Usual operating cadence is weekly: generate a Monday-to-Sunday content batch. The Sunday regeneration run should produce the next Monday-to-Sunday batch, not rewrite the week that just finished.

## Commands
- Install root dependencies: `pip install -r requirements.txt`
- Install Fanvue FastAPI dependencies: `pip install -r fanvue-fastapi/requirements.txt`
- Run root quality checks: `pre-commit run --all-files`
- Run Fanvue FastAPI tests: `python -m pytest fanvue-fastapi/tests -q`

## Safety And Side Effects
- Ask before running commands that touch external services or local generated assets, including Google Drive sync, ComfyUI generation, Meta/Instagram calls, Fanvue API calls, OAuth flows, token validation, uploads, scheduling, or publishing.
- Be aware that root CLI commands such as `python main.py meta ...` and `python main.py all ...` load profiles and may pull from Google Drive before executing the requested command.
- Never read, print, commit, or infer secrets from `.env`, token files, OAuth credentials, Instagram access tokens, Fanvue credentials, Google Drive credentials, or generated media/resource outputs.
- Do not modify influencer personas, prompts, profile resources, generated assets, content safety level, or publishing schedules unless the task explicitly asks for it.
- Keep external API interactions mocked in tests unless the user explicitly approves live calls.

## Coding Standards
- Follow the existing Python style and module boundaries. Prefer small, focused changes over broad refactors.
- Use Pydantic models and validators for structured data rather than ad hoc dict or string handling.
- Keep Typer CLI behavior explicit and preserve existing option names unless the task is a CLI migration.
- Preserve async boundaries in publishing and FastAPI code. Do not hide blocking network calls inside async flows without a clear reason.
- Keep logging through `loguru` in the root automation app.
- Do not add large generated files, media outputs, credentials, resource snapshots, or cache directories to git.

## Tests
- Add or update tests for behavior you change when practical.
- Keep `fanvue-fastapi` tests inside `fanvue-fastapi/tests/`.
- For root automation code, create tests under the root `tests/` folder. Organize new tests by subsystem, for example:
  - `tests/main_components/`
  - `tests/automation/`
  - `tests/llm/`
  - `tests/mains/`
  - `tests/integration/`
- Put unit tests close to the subsystem they exercise. Use `tests/integration/` only for cross-component behavior.
- Mock filesystem, network, OAuth, Google Drive, Meta, Fanvue, and ComfyUI boundaries by default.
- If a verification command fails because of a pre-existing issue, report the exact command and failure instead of hiding it.

## Git Workflow
- Work in the current branch unless the user asks for a branch or worktree.
- Do not commit, push, merge, rebase, reset, or discard user changes unless the user explicitly asks.
- Before editing a file, check whether it already has unrelated local changes. Preserve user edits and avoid mixing unrelated cleanup into the task.
- If the task requires a commit later, use a focused commit message and include only files relevant to the task.
