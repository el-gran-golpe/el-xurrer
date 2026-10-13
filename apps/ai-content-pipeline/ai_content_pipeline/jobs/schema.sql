-- Schema for the local jobs DAG state store (ai_content_pipeline.jobs.store.JobStore).
-- Kept in its own file, separate from store.py, so the shape of the DB is
-- reviewable on its own even without an ORM/migration tool. See the plan doc
-- for why this is plain sqlite3 rather than SQLAlchemy + Alembic.
--
-- The CHECK constraints below must stay in sync with their Python enums:
--   type     <-> JobType (jobs/store.py)
--   platform <-> Platform (domain/types.py)
--   status   <-> JobStatus (jobs/store.py)

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
