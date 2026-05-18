# Fanvue FastAPI

FastAPI app for Fanvue OAuth, session handling, media upload orchestration, and post creation.

## Run

Run from the repository root:

```bash
uv run python apps/fanvue-fastapi/main.py
```

## Tests

```bash
uv run pytest apps/fanvue-fastapi/tests -q
```

## Notes

- Dependencies are defined in the root `pyproject.toml`.
- Keep Fanvue API calls, OAuth exchanges, uploads, and token refreshes mocked in tests unless live calls are explicitly approved.
- Use Fanvue's live docs before changing API contracts: `https://api.fanvue.com/docs/llms.txt`.
