# AI Content Pipeline Agent Instructions

## Scope
- These instructions extend the repository root `AGENTS.md`.
- Treat the root file as the source of truth for shared safety, git workflow, external-service rules, Meta/Fanvue platform boundaries, resources, and full-repo verification.
- This file only captures AI content app-specific orientation.

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
- Exchange a Meta short-lived user token for a profile Page token: fill in `GRAPH_API_BASE_URL`, `DEFAULT_PROFILE_ALIAS`, `DEFAULT_PAGE_ID`, and `META_APP_ID` inside the `if __name__ == "__main__"` block in `apps/ai-content-pipeline/scripts/exchange_meta_page_token.py`, then run `uv run python apps/ai-content-pipeline/scripts/exchange_meta_page_token.py` or a PyCharm run configuration.
- Run the full Meta and Fanvue pipeline for all loaded profiles: `uv run python apps/ai-content-pipeline/main.py all run_all`
- `all run_all` defaults to every loaded profile when no `-p/--profile-indexes` or `-n/--profile-names` selector is passed. Selectors still limit the run.
- `all run_all` clears each selected profile's `meta/outputs` and `fanvue/outputs` before planning/generation by default. Pass `--keep-local-outputs` only when intentionally preserving previous outputs.

## Local Notes
- Profile resources are loaded from the repository root `resources/` tree; follow the root resource-editing restrictions.
- Meta/Instagram, Fanvue, Google Drive, ComfyUI, OAuth, upload, scheduling, and publishing side-effect rules are defined in the root instructions.
- Full Meta/Instagram Page token account setup is documented in `../../docs/meta-instagram-page-token-runbook.md`.
