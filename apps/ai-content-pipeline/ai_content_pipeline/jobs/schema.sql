-- Schema for the local jobs DAG state store (ai_content_pipeline.jobs.store.JobStore).
-- Kept in its own file, separate from store.py, so the shape of the DB is
-- reviewable on its own even without an ORM/migration tool. See the plan doc
-- for why this is plain sqlite3 rather than SQLAlchemy + Alembic.
--
-- The CHECK constraints below must stay in sync with their Python enums:
--   type     <-> JobType (jobs/store.py)
--   platform <-> Platform (domain/types.py)
--   status   <-> JobStatus (jobs/store.py)
--   kind     <-> JobEventKind (jobs/store.py)
--   outcome  <-> the 'success'/'failed' strings jobs/commands/jobs.py passes
--                to JobStore.finish_run

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('plan', 'generate_image', 'schedule')),
    profile TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('meta', 'fanvue')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    params_hash TEXT
);

-- Fan-in tracking for the one join point in the DAG: how many generate_image
-- children (per profile+platform group_key) are still outstanding before the
-- schedule job for that group can be enqueued.
CREATE TABLE IF NOT EXISTS fan_in_counters (
    group_key TEXT PRIMARY KEY,
    remaining INTEGER NOT NULL
);

-- One row per `jobs run` invocation (including `jobs run --skip-schedule`),
-- so a run's own events (below) can be grouped and so `jobs status --runs`
-- can list recent runs without re-deriving a run boundary from `jobs`
-- (which only holds the latest status per DAG node, not per run).
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    args TEXT,
    outcome TEXT CHECK (outcome IN ('success', 'failed'))
);

-- Append-only log of what happened to each DAG node during one run, used to
-- render the end-of-run summary table and `jobs status`. Unlike `jobs`
-- (latest status only), this is never overwritten, so it survives a node
-- being re-run in a later `jobs run` with a different outcome.
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('plan', 'generate_image', 'schedule')),
    profile TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('meta', 'fanvue')),
    week TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'plan_reused',
        'plan_done',
        'plan_failed',
        'plan_attempt_invalid',
        'week_not_enqueued',
        'image_generated',
        'image_reused',
        'image_stale_removed',
        'image_failed',
        'schedule_done',
        'schedule_skipped',
        'schedule_failed'
    )),
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_events_run_id ON job_events (run_id);
