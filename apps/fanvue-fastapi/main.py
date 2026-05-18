from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parents[1]

for import_path in (
    APP_ROOT,
    REPO_ROOT / "shared" / "fanvue-api-client",
):
    import_path_str = str(import_path)
    if import_path_str not in sys.path:
        sys.path.insert(0, import_path_str)

from fanvue_fastapi.main import app  # noqa: E402


__all__ = ["app"]


if __name__ == "__main__":
    import os

    import uvicorn

    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() in ("true", "1", "yes")

    print(f"Starting Fanvue OAuth App on {host}:{port} (Reload: {reload})")
    uvicorn.run("fanvue_fastapi.main:app", host=host, port=port, reload=reload)
