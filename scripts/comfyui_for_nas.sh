#!/usr/bin/env bash
# Serves ComfyUI from this PC (GPU) for a `jobs run` on the NAS, and powers
# this PC off once that run has finished generating images.
#
#   1. Starts ComfyUI from the sibling ../ComfyUI repo if it is not already up
#      (listening on 0.0.0.0 so the NAS reaches it over ZeroTier).
#   2. Watches the NAS run's state DB (inside its container) until no
#      story/plan/generate_image job is pending or running and ComfyUI's queue
#      is empty, for STABLE_POLLS polls in a row. The `schedule` jobs are left
#      running on the NAS: they sleep until each upload time and do not need
#      ComfyUI.
#   3. Stops ComfyUI (if this script started it) and powers off after a
#      countdown, which Ctrl+C cancels.
#
# Start the NAS run with a fixed container name so this script can find it:
#   ssh nas 'cd /srv/apps/el-xurrer && docker compose run -d --name el-xurrer-jobs pipeline jobs run'
#
# Usage: scripts/comfyui_for_nas.sh [--no-poweroff]
# Env overrides: NAS_HOST, NAS_CONTAINER, COMFYUI_DIR, COMFY_PORT, POLL_SECONDS,
#                STABLE_POLLS, POWEROFF_DELAY, COMFYUI_READY_TIMEOUT
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_DIR="${COMFYUI_DIR:-$REPO_ROOT/../ComfyUI}"
COMFY_PORT="${COMFY_PORT:-8188}"
COMFY_URL="http://127.0.0.1:$COMFY_PORT"
COMFYUI_READY_TIMEOUT="${COMFYUI_READY_TIMEOUT:-180}"
NAS_HOST="${NAS_HOST:-nas}"
NAS_CONTAINER="${NAS_CONTAINER:-el-xurrer-jobs}"
POLL_SECONDS="${POLL_SECONDS:-60}"
STABLE_POLLS="${STABLE_POLLS:-5}"
POWEROFF_DELAY="${POWEROFF_DELAY:-120}"

POWEROFF=1
case "${1:-}" in
    --no-poweroff) POWEROFF=0 ;;
    "") ;;
    *) echo "Usage: $0 [--no-poweroff]" >&2; exit 2 ;;
esac

LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"
COMFYUI_LOG="$LOG_DIR/comfyui.log"
STARTED_COMFYUI_PID=""

log() { printf '%s %s\n' "$(date '+%F %T')" "$*"; }

comfy_up() {
    curl --silent --fail --max-time 5 --output /dev/null "$COMFY_URL/"
}

# Prints "idle" when ComfyUI has nothing running or queued, "busy" otherwise.
comfy_queue_state() {
    curl --silent --fail --max-time 5 "$COMFY_URL/queue" | python3 -c '
import json, sys
q = json.load(sys.stdin)
print("busy" if q.get("queue_running") or q.get("queue_pending") else "idle")
' 2>/dev/null || echo "unknown"
}

start_comfyui() {
    if comfy_up; then
        log "ComfyUI is already running at $COMFY_URL; leaving it as it is."
        return 0
    fi
    if [[ ! -d "$COMFYUI_DIR" ]]; then
        log "ComfyUI directory not found at $COMFYUI_DIR (set COMFYUI_DIR)." >&2
        exit 1
    fi
    log "Starting ComfyUI in $COMFYUI_DIR (log: $COMFYUI_LOG)..."
    setsid env -C "$COMFYUI_DIR" uv run python main.py --listen 0.0.0.0 --port "$COMFY_PORT" \
        </dev/null >"$COMFYUI_LOG" 2>&1 &
    STARTED_COMFYUI_PID=$!
    local elapsed=0
    until comfy_up; do
        if ! kill -0 "$STARTED_COMFYUI_PID" 2>/dev/null; then
            log "ComfyUI exited during startup; see $COMFYUI_LOG." >&2
            exit 1
        fi
        if (( elapsed >= COMFYUI_READY_TIMEOUT )); then
            log "Timed out waiting for ComfyUI after ${COMFYUI_READY_TIMEOUT}s." >&2
            exit 1
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    log "ComfyUI is up (pid $STARTED_COMFYUI_PID)."
}

stop_comfyui() {
    [[ -n "$STARTED_COMFYUI_PID" ]] || return 0
    log "Stopping ComfyUI (pid $STARTED_COMFYUI_PID)..."
    # setsid made it a process-group leader: stop uv and its python child.
    kill -TERM -- "-$STARTED_COMFYUI_PID" 2>/dev/null || kill -TERM "$STARTED_COMFYUI_PID" 2>/dev/null
}

# Asks the NAS for the run's state. Prints one line:
#   absent                     container does not exist
#   exited                     container exists but is not running
#   starting                   running, but its jobs run has not recorded a run yet
#   active <n> <done> <failed> run recorded; n = story/plan/generate_image jobs
#                              still pending or running; done/failed images
# Prints nothing if SSH itself fails (e.g. Bitwarden vault locked).
nas_state() {
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$NAS_HOST" bash -s -- "$NAS_CONTAINER" <<'REMOTE'
container="$1"
running=$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null) || { echo absent; exit 0; }
[[ "$running" == "true" ]] || { echo exited; exit 0; }
started=$(docker inspect -f '{{.State.StartedAt}}' "$container")
docker exec -i -e CONTAINER_STARTED="$started" "$container" python - <<'PY'
import os, re, sqlite3
from datetime import datetime

def parse(ts):
    # Docker gives nanoseconds and "Z"; Python wants at most microseconds.
    ts = re.sub(r"(\.\d{6})\d+", r"\1", ts.replace("Z", "+00:00"))
    return datetime.fromisoformat(ts)

db = sqlite3.connect(os.environ.get("JOBS_DB_PATH", ".cache/jobs/state.db"))
row = db.execute("SELECT started_at FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
if row is None or parse(row[0]) < parse(os.environ["CONTAINER_STARTED"]):
    print("starting")
else:
    active = db.execute(
        "SELECT count(*) FROM jobs WHERE type IN ('story', 'plan', 'generate_image')"
        " AND status IN ('pending', 'running')"
    ).fetchone()[0]
    images = dict(db.execute(
        "SELECT status, count(*) FROM jobs WHERE type = 'generate_image' GROUP BY status"
    ).fetchall())
    print("active", active, images.get("done", 0), images.get("failed", 0))
PY
REMOTE
}

poweroff_after_countdown() {
    log "Powering off in ${POWEROFF_DELAY}s. Press Ctrl+C to cancel."
    command -v notify-send >/dev/null && notify-send -u critical "ComfyUI for NAS" \
        "Generation finished. Powering off in ${POWEROFF_DELAY}s (Ctrl+C in the terminal cancels)." || true
    trap 'echo; log "Power-off cancelled."; exit 130' INT
    sleep "$POWEROFF_DELAY"
    log "Powering off."
    systemctl poweroff
}

start_comfyui

log "Watching container '$NAS_CONTAINER' on '$NAS_HOST' every ${POLL_SECONDS}s (needs ${STABLE_POLLS} idle polls in a row)."
seen_running=0
idle_polls=0
while true; do
    state=$(nas_state)
    queue=$(comfy_queue_state)
    case "$state" in
        "")
            log "Could not reach $NAS_HOST over SSH (is the Bitwarden vault unlocked?); retrying."
            idle_polls=0
            ;;
        absent)
            if (( seen_running )); then
                log "Container '$NAS_CONTAINER' is gone; the run has ended."
                break
            fi
            log "Container '$NAS_CONTAINER' does not exist yet; waiting for the NAS run to be started."
            ;;
        exited)
            if (( seen_running )); then
                log "Container '$NAS_CONTAINER' has exited; the run has ended (check: ssh $NAS_HOST docker logs $NAS_CONTAINER)."
                break
            fi
            log "Container '$NAS_CONTAINER' exists but is not running (a previous run?); waiting for a new one."
            ;;
        starting)
            seen_running=1
            idle_polls=0
            log "NAS run is starting (Drive pull / profile loading)."
            ;;
        active\ *)
            seen_running=1
            read -r _ active done failed <<<"$state"
            # "unknown" (ComfyUI not answering, e.g. it crashed) counts as idle:
            # nothing can be generating, and the PC must not stay on forever.
            if [[ "$active" == "0" && "$queue" != "busy" ]]; then
                idle_polls=$((idle_polls + 1))
            else
                idle_polls=0
            fi
            log "Jobs left: $active, images done: $done, failed: $failed, ComfyUI queue: $queue, idle polls: $idle_polls/$STABLE_POLLS"
            if (( idle_polls >= STABLE_POLLS )); then
                log "Generation finished: $done images done, $failed failed."
                break
            fi
            ;;
        *)
            log "Unexpected answer from the NAS: $state"
            idle_polls=0
            ;;
    esac
    sleep "$POLL_SECONDS"
done

stop_comfyui
if (( POWEROFF )); then
    poweroff_after_countdown
else
    log "--no-poweroff given; leaving the PC on."
fi
