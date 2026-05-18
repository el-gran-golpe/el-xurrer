# AI Content Pipeline Agent Instructions

## Purpose
- This app handles AI influencer planning, generation, scheduling, Instagram publishing, Fanvue publishing orchestration, Google Drive resource sync, ComfyUI image generation, and LLM routing.
- These instructions extend the root `AGENTS.md`.
- Do not commit or push changes unless the user explicitly asks for that in the current task.

## Project Map
- `main.py` is the app-local CLI entrypoint.
- `ai_content_pipeline/cli/` contains the Typer CLI and `meta`, `fanvue`, and `all` commands.
- `ai_content_pipeline/domain/`, `profiles/`, `planning/`, `generation/`, and `publishing/` contain domain models and workflow services.
- `ai_content_pipeline/integrations/` contains adapters for Google Drive, Meta/Instagram, Fanvue publishing, and ComfyUI.
- `ai_content_pipeline/llm/` contains LLM routing, model classification/cache logic, prompt utilities, and API error handling.
- `tests/` contains this app's test suite.

## Commands
- Run the CLI from the repository root: `uv run python apps/ai-content-pipeline/main.py --help`
- Run this app's tests: `uv run pytest apps/ai-content-pipeline/tests -q`
- Run all tests: `uv run pytest -q`
- Run configured checks: `uv run pre-commit run --all-files`
- After making changes, run the relevant focused tests plus `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, and `uv run pytest -q`.

## Safety
- Do not inspect or modify the repository root `resources/` folder unless the task explicitly requires profile/resource work.
- Ask before running commands that touch external services or generated assets, including Google Drive sync, ComfyUI generation, Meta/Instagram calls, Fanvue API calls, OAuth flows, uploads, scheduling, or publishing.
- Keep external API interactions mocked in tests unless the user explicitly approves live calls.
- Instagram assets must stay safe for work. Fanvue-specific explicit content belongs only in Fanvue resources and outputs.
