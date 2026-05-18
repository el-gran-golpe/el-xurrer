from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parents[1]

for import_path in (
    APP_ROOT,
    REPO_ROOT / "apps" / "fanvue-fastapi",
    REPO_ROOT / "shared" / "fanvue-api-client",
):
    import_path_str = str(import_path)
    if import_path_str not in sys.path:
        sys.path.insert(0, import_path_str)

from ai_content_pipeline.cli.main import app  # noqa: E402


if __name__ == "__main__":
    app()
