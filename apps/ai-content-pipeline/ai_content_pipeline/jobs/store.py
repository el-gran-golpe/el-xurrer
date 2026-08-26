import sqlite3
from enum import Enum
from pathlib import Path

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
