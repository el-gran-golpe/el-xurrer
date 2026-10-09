#!/usr/bin/env bash
# Runs the AI content CLI against the isolated resources.migrated/ tree used
# while validating the weekly-planning-continuity migration
# (docs/weekly-planning-continuity-plan.md), instead of the real resources/
# tree. This lets the migration be exercised on this branch without ever
# touching resources/ or Google Drive, regardless of whether the caller
# remembers to set env vars by hand.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATED_DIR="$REPO_ROOT/resources.migrated"

if [[ ! -d "$MIGRATED_DIR" ]]; then
    echo "resources.migrated/ not found at $MIGRATED_DIR. Create/populate it before using this wrapper." >&2
    exit 1
fi

export AI_CONTENT_RESOURCES_DIR="$MIGRATED_DIR"
export DRIVE_SYNC_ENABLED=false
export JOBS_DB_PATH="$REPO_ROOT/.cache/jobs/migrated.db"

cd "$REPO_ROOT"
exec uv run python apps/ai-content-pipeline/main.py "$@"
