import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ai_content_pipeline.domain.types import Platform

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class JobType(str, Enum):
    """The 3 node kinds in the plan -> generate_image -> schedule DAG."""

    PLAN = "plan"
    GENERATE_IMAGE = "generate_image"
    SCHEDULE = "schedule"


class JobStatus(str, Enum):
    """Status of a single DAG node, persisted so a run can resume without repeating work."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobEventKind(str, Enum):
    """
    What happened to one DAG node during one `jobs run`, recorded in
    `job_events` so the end-of-run summary and `jobs status` can report on a
    run without grepping logs. Kept in sync with the `kind` CHECK constraint
    in schema.sql.
    """

    PLAN_REUSED = "plan_reused"
    PLAN_DONE = "plan_done"
    PLAN_FAILED = "plan_failed"
    PLAN_ATTEMPT_INVALID = "plan_attempt_invalid"
    WEEK_NOT_ENQUEUED = "week_not_enqueued"
    IMAGE_GENERATED = "image_generated"
    IMAGE_REUSED = "image_reused"
    IMAGE_STALE_REMOVED = "image_stale_removed"
    IMAGE_FAILED = "image_failed"
    SCHEDULE_DONE = "schedule_done"
    SCHEDULE_SKIPPED = "schedule_skipped"
    SCHEDULE_FAILED = "schedule_failed"


class JobStore:
    """
    Persists DAG node status (plan/generate_image/schedule) plus a fan-in
    counter, so a crashed run can resume by skipping nodes already `done`.

    Not thread-safe across OS threads; safe to share across coroutines on a
    single event loop, which is how the in-process Queue uses it.
    """

    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def status(self, job_id: str) -> JobStatus | None:
        row = self._conn.execute(
            "SELECT status FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return JobStatus(row[0]) if row else None

    def params_hash(self, job_id: str) -> str | None:
        """
        The `params_hash` currently stored for this job, or `None` if it has
        never been seen. Read this *before* calling `create()` with a newly
        computed hash, if the caller needs to tell whether that hash changed
        — `create()`'s own UPDATE overwrites the stored value.
        """
        row = self._conn.execute(
            "SELECT params_hash FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return row[0] if row else None

    def create(
        self,
        job_id: str,
        job_type: JobType,
        profile: str,
        platform: Platform,
        params_hash: str | None = None,
    ) -> JobStatus:
        """
        Idempotent seed: insert as `pending` if unseen. If already `done` with
        a matching `params_hash`, leave it alone (resume skips it). If `done`
        with a different `params_hash` (its inputs changed since it last
        completed) or `failed`, reset to `pending` so it re-runs. Returns the
        resulting status.
        """
        row = self._conn.execute(
            "SELECT status, params_hash FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO jobs (id, type, profile, platform, status, params_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, job_type, profile, platform, JobStatus.PENDING, params_hash),
            )
            self._conn.commit()
            return JobStatus.PENDING

        status, existing_hash = JobStatus(row[0]), row[1]
        if status is JobStatus.DONE and existing_hash == params_hash:
            return JobStatus.DONE
        if status in (JobStatus.PENDING, JobStatus.RUNNING):
            return status

        self._conn.execute(
            "UPDATE jobs SET status = ?, params_hash = ?, error = NULL WHERE id = ?",
            (JobStatus.PENDING, params_hash, job_id),
        )
        self._conn.commit()
        return JobStatus.PENDING

    def mark_running(self, job_id: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ?, attempts = attempts + 1 WHERE id = ?",
            (JobStatus.RUNNING, job_id),
        )
        self._conn.commit()

    def forget(self, job_id: str) -> None:
        """
        Deletes a job's row. For nodes that no longer exist in the DAG at all
        (an image whose post a re-plan removed), so status reports do not
        keep counting them.
        """
        self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self._conn.commit()

    def mark_done(self, job_id: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ?, error = NULL WHERE id = ?",
            (JobStatus.DONE, job_id),
        )
        self._conn.commit()

    def mark_failed(self, job_id: str, error: str) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = ?, error = ? WHERE id = ?",
            (JobStatus.FAILED, error, job_id),
        )
        self._conn.commit()

    def init_counter(self, group_key: str, total: int) -> None:
        """Idempotent: only sets the counter the first time a group is seen."""
        self._conn.execute(
            "INSERT OR IGNORE INTO fan_in_counters (group_key, remaining) VALUES (?, ?)",
            (group_key, total),
        )
        self._conn.commit()

    def decrement_counter(self, group_key: str) -> int:
        """Decrements and returns the remaining count (0 means the fan-in is complete)."""
        self._conn.execute(
            "UPDATE fan_in_counters SET remaining = remaining - 1 WHERE group_key = ?",
            (group_key,),
        )
        remaining = self._conn.execute(
            "SELECT remaining FROM fan_in_counters WHERE group_key = ?", (group_key,)
        ).fetchone()[0]
        self._conn.commit()
        return int(remaining)

    # ---------------- run lifecycle + events ----------------

    def start_run(self, args: dict[str, Any]) -> str:
        """Records the start of one `jobs run` invocation and returns its id."""
        run_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO runs (run_id, started_at, finished_at, args, outcome) "
            "VALUES (?, ?, NULL, ?, NULL)",
            (run_id, _now(), json.dumps(args)),
        )
        self._conn.commit()
        return run_id

    def finish_run(self, run_id: str, outcome: str) -> None:
        """`outcome` is `"success"` or `"failed"` — whatever `jobs run` decided
        after looking at this run's events."""
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, outcome = ? WHERE run_id = ?",
            (_now(), outcome, run_id),
        )
        self._conn.commit()

    def record_event(
        self,
        run_id: str,
        job_id: str,
        job_type: JobType,
        profile: str,
        platform: Platform,
        week: str,
        kind: JobEventKind,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """
        Appends one fact about a DAG node to this run's history. Never
        overwrites a previous event — unlike `jobs` (latest status only),
        `job_events` is append-only so a node re-run in a later `jobs run`
        does not erase what happened the first time.
        """
        self._conn.execute(
            "INSERT INTO job_events "
            "(run_id, job_id, type, profile, platform, week, kind, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                job_id,
                job_type.value,
                profile,
                platform.value,
                week,
                kind.value,
                json.dumps(detail) if detail is not None else None,
                _now(),
            ),
        )
        self._conn.commit()

    def events_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Every event recorded for one run, in the order they were recorded."""
        rows = self._conn.execute(
            "SELECT job_id, type, profile, platform, week, kind, detail, created_at "
            "FROM job_events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [
            {
                "job_id": r[0],
                "type": r[1],
                "profile": r[2],
                "platform": r[3],
                "week": r[4],
                "kind": r[5],
                "detail": json.loads(r[6]) if r[6] else None,
                "created_at": r[7],
            }
            for r in rows
        ]

    def last_run_id(self) -> str | None:
        row = self._conn.execute(
            "SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Most recent runs first, each with its failure-event count."""
        rows = self._conn.execute(
            "SELECT run_id, started_at, finished_at, args, outcome FROM runs "
            "ORDER BY rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        results = []
        for run_id, started_at, finished_at, args, outcome in rows:
            failure_count = self._conn.execute(
                "SELECT COUNT(*) FROM job_events WHERE run_id = ? AND kind LIKE '%\\_failed' ESCAPE '\\'",
                (run_id,),
            ).fetchone()[0]
            results.append(
                {
                    "run_id": run_id,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "args": json.loads(args) if args else {},
                    "outcome": outcome,
                    "failure_count": failure_count,
                }
            )
        return results

    def all_jobs(self) -> list[dict[str, Any]]:
        """Every DAG node's latest status, for `jobs status`'s overview."""
        rows = self._conn.execute(
            "SELECT id, type, profile, platform, status, attempts, error, params_hash "
            "FROM jobs"
        ).fetchall()
        return [
            {
                "id": r[0],
                "type": r[1],
                "profile": r[2],
                "platform": r[3],
                "status": r[4],
                "attempts": r[5],
                "error": r[6],
                "params_hash": r[7],
            }
            for r in rows
        ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
