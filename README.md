# El Xurrer

Python monorepo for AI creator content workflows.

## Layout

- `apps/ai-content-pipeline/` - Typer CLI for planning, generation, scheduling, Instagram publishing, Fanvue publishing orchestration, Google Drive sync, ComfyUI, and LLM routing.
- `apps/fanvue-fastapi/` - FastAPI app for Fanvue OAuth, sessions, media uploads, and post creation.
- `shared/fanvue-api-client/` - shared Fanvue OAuth, media, post, and token-store helpers.
- `resources/` - local runtime profile resources. This folder is gitignored and should not be committed.

## Setup

Use `uv` from the repository root:

```bash
uv sync
uv run pre-commit install
```

Both apps use the repository-root `.env`. For a new checkout, copy the shared template from the repository root, then fill in the values needed by your app:

```bash
cp -n .env.example .env
```

Run the AI content CLI with the repository root as the working directory, including in IDE run configurations: it resolves `.env` relative to the working directory. Fanvue FastAPI resolves the root `.env` by absolute path.

## AI Content CLI

```bash
uv run python apps/ai-content-pipeline/main.py --help
uv run python apps/ai-content-pipeline/main.py meta plan -p 0
uv run python apps/ai-content-pipeline/main.py meta generate -p 0
uv run python apps/ai-content-pipeline/main.py meta schedule -p 0
uv run python apps/ai-content-pipeline/main.py all run_all -p 0
```

The Instagram publishing path uses a Facebook staging Page only to obtain public media URLs for Instagram. It is not a Facebook cross-posting flow.

## Fanvue FastAPI

```bash
uv run python apps/fanvue-fastapi/main.py
```

## Checks

```bash
uv run ruff format .
uv run ruff check .
uv run mypy
uv run pytest -q
uv run pre-commit run --all-files
```

`pre-commit` runs Ruff format checking, Ruff linting, mypy, and the full pytest suite.
