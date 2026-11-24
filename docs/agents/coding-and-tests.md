# Coding Standards And Tests

Split out of the root `AGENTS.md` to keep always-loaded agent instructions small. Read it before writing or changing code or tests.

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
- `apps/ai-content-pipeline/tests/conftest.py` has an autouse `_no_external_network` fixture that makes any non-localhost socket connection raise, so a missing fake fails the test instead of silently calling an LLM provider or another external service. Do not disable it; fake the boundary instead.
- After changes, run the relevant focused tests plus the configured checks: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, and `uv run pytest -q`. For a final full gate, run `uv run pre-commit run --all-files`.
- If a verification command fails because of a pre-existing issue, report the exact command and failure instead of hiding it.
