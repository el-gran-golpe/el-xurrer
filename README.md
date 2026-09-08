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
uv run python apps/ai-content-pipeline/main.py all run_all
uv run python apps/ai-content-pipeline/main.py all debug
uv run python apps/ai-content-pipeline/main.py meta plan
uv run python apps/ai-content-pipeline/main.py meta generate
uv run python apps/ai-content-pipeline/main.py meta schedule
uv run python apps/ai-content-pipeline/main.py fanvue plan
uv run python apps/ai-content-pipeline/main.py fanvue generate
uv run python apps/ai-content-pipeline/main.py fanvue schedule
uv run python apps/ai-content-pipeline/main.py fanvue auth
```

Every command above that accepts profile selectors runs **all loaded profiles**
when neither `-p/--profile-indexes` nor `-n/--profile-names` is supplied. This applies
to `all run_all`, `all debug`, Meta/Fanvue `plan`, `generate`, and `schedule`, and
`fanvue auth`.

To run a command for specific profiles, pass an index with `-p` (repeat it to select
multiple profiles) or comma-separated names with `-n`. Indexes take precedence when
both selectors are supplied:

```bash
uv run python apps/ai-content-pipeline/main.py all run_all -p 0
uv run python apps/ai-content-pipeline/main.py meta generate -p 0 -p 1
uv run python apps/ai-content-pipeline/main.py fanvue plan -n laura_vigne,maria_larsen
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
