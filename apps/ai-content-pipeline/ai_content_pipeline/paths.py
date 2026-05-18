import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
APP_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = APP_ROOT.parent.parent

RESOURCES_DIR = Path(
    os.getenv("AI_CONTENT_RESOURCES_DIR", str(REPO_ROOT / "resources"))
).expanduser()
FANVUE_FASTAPI_DIR = REPO_ROOT / "apps" / "fanvue-fastapi"
SHARED_FANVUE_API_CLIENT_DIR = REPO_ROOT / "shared" / "fanvue-api-client"
