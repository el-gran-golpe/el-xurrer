#!/usr/bin/env bash
# Stops the pipeline and ComfyUI processes started by
# start_pipeline_with_comfyui.sh. Stops the pipeline first (it depends on
# ComfyUI), then ComfyUI. Each process was started via setsid as its own
# session/process-group leader, so we signal the whole group (pid and any
# children it spawned), not just the tracked pid.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs"
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-20}"

stop_process_group() {
    local name="$1" pid_file="$2"

    if [[ ! -s "$pid_file" ]]; then
        echo "$name: no pid file, nothing to stop."
        return 0
    fi

    local pid
    pid="$(cat "$pid_file")"

    if ! kill -0 "$pid" 2>/dev/null; then
        echo "$name: pid $pid not running (stale pid file). Cleaning up."
        rm -f "$pid_file"
        return 0
    fi

    echo "$name: sending SIGTERM to process group $pid..."
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if (( waited >= GRACEFUL_TIMEOUT )); then
            echo "$name: still running after ${GRACEFUL_TIMEOUT}s, sending SIGKILL."
            kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done

    rm -f "$pid_file"
    echo "$name: stopped."
}

stop_process_group "Pipeline" "$LOG_DIR/pipeline.pid"
stop_process_group "ComfyUI" "$LOG_DIR/comfyui.pid"
