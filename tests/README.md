# Root Test Suite

Use this folder for tests that cover the root automation app.

## Structure
- `tests/main_components/` for planning, generation, scheduling, config, profile, and domain model tests.
- `tests/automation/` for Google Drive, Meta, Fanvue client, and other service boundary tests.
- `tests/llm/` for LLM wrappers, routing, classification, prompt utilities, and error handling tests.
- `tests/mains/` for Typer CLI command and orchestration tests.
- `tests/integration/` for cross-component behavior that cannot be covered cleanly by unit tests.

Keep the nested FastAPI app tests in `fanvue-fastapi/tests/`.

## Guidelines
- Mock network, OAuth, Google Drive, Meta, Fanvue, ComfyUI, and filesystem side effects by default.
- Keep unit tests focused on one module or behavior.
- Use integration tests only when the behavior crosses module boundaries.
- Name test files with the `test_*.py` pattern.
