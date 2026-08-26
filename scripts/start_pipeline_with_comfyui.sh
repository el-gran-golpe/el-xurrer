#!/usr/bin/env bash
# Starts ComfyUI (sibling repo, its own uv env) and, once it's ready, the full
# AI content pipeline ("all run_all" for every loaded profile) — both fully
# detached from this terminal/session via setsid, so closing the terminal or
# the SSH/tmux session that launched this script does not stop them.
#
# Logs and pid files live in <repo>/logs/. Use stop_pipeline_with_comfyui.sh
# to stop both processes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMFYUI_DIR="${COMFYUI_DIR:-$REPO_ROOT/../ComfyUI}"
COMFY_HOST="${COMFY_HOST:-127.0.0.1}"
COMFY_PORT="${COMFY_PORT:-8188}"
COMFYUI_READY_TIMEOUT="${COMFYUI_READY_TIMEOUT:-180}"

LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

COMFYUI_LOG="$LOG_DIR/comfyui.log"
COMFYUI_PID_FILE="$LOG_DIR/comfyui.pid"
PIPELINE_LOG="$LOG_DIR/pipeline.log"
PIPELINE_PID_FILE="$LOG_DIR/pipeline.pid"
PIPELINE_WRAPPER="$LOG_DIR/.pipeline_wrapper.sh"

is_running() {
    local pid_file="$1"
    [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

if is_running "$COMFYUI_PID_FILE"; then
    echo "ComfyUI is already running (pid $(cat "$COMFYUI_PID_FILE")). Run scripts/stop_pipeline_with_comfyui.sh first." >&2
    exit 1
fi
if is_running "$PIPELINE_PID_FILE"; then
    echo "Pipeline is already running (pid $(cat "$PIPELINE_PID_FILE")). Run scripts/stop_pipeline_with_comfyui.sh first." >&2
    exit 1
fi
if [[ ! -d "$COMFYUI_DIR" ]]; then
    echo "ComfyUI directory not found at $COMFYUI_DIR (set COMFYUI_DIR to override)" >&2
    exit 1
fi

echo "Starting ComfyUI in $COMFYUI_DIR (log: $COMFYUI_LOG)..."
setsid env -C "$COMFYUI_DIR" uv run python main.py --listen "$COMFY_HOST" --port "$COMFY_PORT" \
    </dev/null >"$COMFYUI_LOG" 2>&1 &
COMFYUI_PID=$!
disown
echo "$COMFYUI_PID" >"$COMFYUI_PID_FILE"
echo "ComfyUI started (pid $COMFYUI_PID)."

# The pipeline needs to wait for ComfyUI to accept connections before it
# starts (the CLI's ComfyUI connection check does not retry). That wait has
# to run inside the detached process too, so it survives a terminal close
# just like the pipeline run that follows it.
cat >"$PIPELINE_WRAPPER" <<'WRAPPER_EOF'
#!/usr/bin/env bash
set -uo pipefail
COMFY_HOST="$1"; COMFY_PORT="$2"; TIMEOUT="$3"; COMFYUI_PID_FILE="$4"; REPO_ROOT="$5"
shift 5

elapsed=0
until curl --silent --fail --output /dev/null "http://$COMFY_HOST:$COMFY_PORT/"; do
    if [[ -s "$COMFYUI_PID_FILE" ]] && ! kill -0 "$(cat "$COMFYUI_PID_FILE")" 2>/dev/null; then
        echo "ComfyUI process is not running. Aborting pipeline." >&2
        exit 1
    fi
    if (( elapsed >= TIMEOUT )); then
        echo "Timed out waiting for ComfyUI after ${TIMEOUT}s." >&2
        exit 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

echo "ComfyUI is up. Starting pipeline: all run_all $*"
cd "$REPO_ROOT"
exec uv run python apps/ai-content-pipeline/main.py all run_all "$@"
WRAPPER_EOF
chmod +x "$PIPELINE_WRAPPER"

echo "Starting pipeline wrapper (log: $PIPELINE_LOG)..."
setsid bash "$PIPELINE_WRAPPER" "$COMFY_HOST" "$COMFY_PORT" "$COMFYUI_READY_TIMEOUT" "$COMFYUI_PID_FILE" "$REPO_ROOT" "$@" \
    </dev/null >"$PIPELINE_LOG" 2>&1 &
PIPELINE_PID=$!
disown
echo "$PIPELINE_PID" >"$PIPELINE_PID_FILE"
echo "Pipeline wrapper started (pid $PIPELINE_PID); it will wait for ComfyUI then run all profiles."

echo
echo "Both processes are detached and will keep running after this shell exits."
echo "Follow progress with: tail -f $COMFYUI_LOG $PIPELINE_LOG"
echo "Stop everything with: scripts/stop_pipeline_with_comfyui.sh"
