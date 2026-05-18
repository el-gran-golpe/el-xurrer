# AI Content Pipeline

Typer CLI app for AI creator content workflows: planning, generation, scheduling, Instagram publishing, Fanvue publishing orchestration, Google Drive sync, ComfyUI, and LLM routing.

## Run

Run commands from the repository root:

```bash
uv run python apps/ai-content-pipeline/main.py --help
uv run python apps/ai-content-pipeline/main.py meta plan -p 0
uv run python apps/ai-content-pipeline/main.py meta generate -p 0
uv run python apps/ai-content-pipeline/main.py meta schedule -p 0
uv run python apps/ai-content-pipeline/main.py all run_all -p 0
```

## Tests

```bash
uv run pytest apps/ai-content-pipeline/tests -q
```

## Notes

- Runtime profile data lives in the repository root `resources/` folder.
- Commands that sync resources, generate media, authenticate, upload, schedule, or publish have external side effects.
- Instagram assets must remain safe for work. Fanvue-specific content belongs only in Fanvue resources and outputs.
