import sqlite3

from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.jobs.store import JobEventKind, JobStatus, JobStore, JobType


def _store() -> JobStore:
    return JobStore(":memory:")


def test_create_seeds_a_new_job_as_pending():
    store = _store()
    status = store.create("plan:haru:meta", JobType.PLAN, "haru", Platform.META)
    assert status is JobStatus.PENDING
    assert store.status("plan:haru:meta") is JobStatus.PENDING


def test_unknown_job_has_no_status():
    store = _store()
    assert store.status("nope") is None


def test_running_then_done_transitions():
    store = _store()
    job_id = "plan:haru:meta"
    store.create(job_id, JobType.PLAN, "haru", Platform.META)

    store.mark_running(job_id)
    assert store.status(job_id) is JobStatus.RUNNING

    store.mark_done(job_id)
    assert store.status(job_id) is JobStatus.DONE


def test_resume_skips_a_done_job_with_matching_params_hash():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )
    store.mark_done(job_id)

    status = store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )

    assert status is JobStatus.DONE


def test_resume_reruns_a_done_job_whose_params_hash_changed():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )
    store.mark_done(job_id)

    status = store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="different"
    )

    assert status is JobStatus.PENDING


def test_resume_reruns_a_previously_failed_job():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(job_id, JobType.GENERATE_IMAGE, "haru", Platform.META)
    store.mark_failed(job_id, "boom")

    status = store.create(job_id, JobType.GENERATE_IMAGE, "haru", Platform.META)

    assert status is JobStatus.PENDING
    assert store.status(job_id) is JobStatus.PENDING


def test_resume_leaves_a_pending_job_untouched():
    store = _store()
    job_id = "generate_image:haru:meta:slug:0"
    store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="abc"
    )

    status = store.create(
        job_id, JobType.GENERATE_IMAGE, "haru", Platform.META, params_hash="different"
    )

    assert status is JobStatus.PENDING


def test_fan_in_counter_reaches_zero_after_every_decrement():
    store = _store()
    store.init_counter("haru:meta", 3)

    assert store.decrement_counter("haru:meta") == 2
    assert store.decrement_counter("haru:meta") == 1
    assert store.decrement_counter("haru:meta") == 0


def test_init_counter_is_idempotent():
    store = _store()
    store.init_counter("haru:meta", 3)
    store.decrement_counter("haru:meta")
    store.init_counter("haru:meta", 3)  # re-seed on resume must not reset progress

    assert store.decrement_counter("haru:meta") == 1


# ---------------- run lifecycle + events ----------------


def test_start_run_returns_a_run_id_and_persists_the_args():
    store = _store()
    run_id = store.start_run({"weeks": 2, "skip_schedule": False})

    assert run_id
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == run_id
    assert runs[0]["args"] == {"weeks": 2, "skip_schedule": False}
    assert runs[0]["finished_at"] is None
    assert runs[0]["outcome"] is None


def test_finish_run_records_outcome_and_finished_at():
    store = _store()
    run_id = store.start_run({})

    store.finish_run(run_id, "success")

    runs = store.list_runs()
    assert runs[0]["outcome"] == "success"
    assert runs[0]["finished_at"] is not None


def test_last_run_id_is_the_most_recently_started_run():
    store = _store()
    store.start_run({})
    second = store.start_run({})

    assert store.last_run_id() == second


def test_last_run_id_is_none_when_no_run_was_ever_started():
    store = _store()
    assert store.last_run_id() is None


def test_record_event_round_trips_through_events_for_run():
    store = _store()
    run_id = store.start_run({})

    store.record_event(
        run_id,
        "plan:haru:meta:2026-09-01",
        JobType.PLAN,
        "haru",
        Platform.META,
        "2026-09-01",
        JobEventKind.PLAN_DONE,
        detail={"attempt": 1, "max_attempts": 5},
    )

    events = store.events_for_run(run_id)
    assert len(events) == 1
    event = events[0]
    assert event["job_id"] == "plan:haru:meta:2026-09-01"
    assert event["type"] == "plan"
    assert event["profile"] == "haru"
    assert event["platform"] == "meta"
    assert event["week"] == "2026-09-01"
    assert event["kind"] == "plan_done"
    assert event["detail"] == {"attempt": 1, "max_attempts": 5}


def test_record_event_without_detail_round_trips_as_none():
    store = _store()
    run_id = store.start_run({})

    store.record_event(
        run_id,
        "plan:haru:meta:2026-09-01",
        JobType.PLAN,
        "haru",
        Platform.META,
        "2026-09-01",
        JobEventKind.PLAN_REUSED,
    )

    assert store.events_for_run(run_id)[0]["detail"] is None


def test_events_for_run_only_returns_that_runs_events():
    store = _store()
    run_a = store.start_run({})
    run_b = store.start_run({})
    store.record_event(
        run_a, "plan:a", JobType.PLAN, "a", Platform.META, "w", JobEventKind.PLAN_DONE
    )
    store.record_event(
        run_b, "plan:b", JobType.PLAN, "b", Platform.META, "w", JobEventKind.PLAN_DONE
    )

    assert [e["job_id"] for e in store.events_for_run(run_a)] == ["plan:a"]
    assert [e["job_id"] for e in store.events_for_run(run_b)] == ["plan:b"]


def test_list_runs_reports_a_failure_count_per_run():
    store = _store()
    run_id = store.start_run({})
    store.record_event(
        run_id,
        "plan:a",
        JobType.PLAN,
        "a",
        Platform.META,
        "w",
        JobEventKind.PLAN_FAILED,
        detail={"error": "boom"},
    )
    store.record_event(
        run_id,
        "img:a",
        JobType.GENERATE_IMAGE,
        "a",
        Platform.META,
        "w",
        JobEventKind.IMAGE_FAILED,
        detail={"error": "boom"},
    )
    store.record_event(
        run_id,
        "plan:b",
        JobType.PLAN,
        "b",
        Platform.META,
        "w",
        JobEventKind.PLAN_DONE,
    )

    runs = store.list_runs()
    assert runs[0]["failure_count"] == 2


def test_list_runs_orders_most_recent_first_and_respects_limit():
    store = _store()
    first = store.start_run({})
    second = store.start_run({})
    third = store.start_run({})

    runs = store.list_runs(limit=2)

    assert [r["run_id"] for r in runs] == [third, second]
    assert first not in [r["run_id"] for r in runs]


def test_all_jobs_returns_every_job_row():
    store = _store()
    store.create("plan:haru:meta:2026-09-01", JobType.PLAN, "haru", Platform.META)
    store.mark_done("plan:haru:meta:2026-09-01")

    jobs = store.all_jobs()

    assert len(jobs) == 1
    assert jobs[0]["id"] == "plan:haru:meta:2026-09-01"
    assert jobs[0]["type"] == "plan"
    assert jobs[0]["status"] == "done"


def test_schema_upgrades_an_existing_db_that_only_has_the_old_tables(tmp_path):
    """
    `JOBS_DB_PATH` points at a real file across `jobs run` invocations, so an
    existing DB created before `runs`/`job_events` existed must keep working
    once this code opens it — `CREATE TABLE IF NOT EXISTS` must only add the
    new tables, never touch `jobs`/`fan_in_counters` or their data.
    """
    db_path = tmp_path / "state.db"
    old_conn = sqlite3.connect(str(db_path))
    old_conn.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            profile TEXT NOT NULL,
            platform TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            params_hash TEXT
        );
        CREATE TABLE fan_in_counters (
            group_key TEXT PRIMARY KEY,
            remaining INTEGER NOT NULL
        );
        """
    )
    old_conn.execute(
        "INSERT INTO jobs (id, type, profile, platform, status) "
        "VALUES ('plan:haru:meta:2026-09-01', 'plan', 'haru', 'meta', 'done')"
    )
    old_conn.commit()
    old_conn.close()

    store = JobStore(db_path)

    # Pre-existing data survived the upgrade.
    assert store.status("plan:haru:meta:2026-09-01") is JobStatus.DONE
    # And the new tables are usable.
    run_id = store.start_run({})
    store.record_event(
        run_id,
        "plan:haru:meta:2026-09-01",
        JobType.PLAN,
        "haru",
        Platform.META,
        "2026-09-01",
        JobEventKind.PLAN_DONE,
    )
    assert len(store.events_for_run(run_id)) == 1


def test_forget_deletes_the_job_row(tmp_path):
    store = JobStore(tmp_path / "state.db")
    store.create(
        "generate_image:p:meta:2026-10-12/day_1/a_0.jpeg",
        JobType.GENERATE_IMAGE,
        "p",
        Platform.META,
        "h",
    )

    store.forget("generate_image:p:meta:2026-10-12/day_1/a_0.jpeg")

    assert store.status("generate_image:p:meta:2026-10-12/day_1/a_0.jpeg") is None


# ---------------- story job type + nullable platform ----------------


def test_story_job_can_be_created_with_no_platform():
    store = _store()

    status = store.create("story:haru:2026-10-05", JobType.STORY, "haru", None)

    assert status is JobStatus.PENDING
    jobs = store.all_jobs()
    assert jobs[0]["platform"] is None
    assert jobs[0]["type"] == "story"


def test_story_event_can_be_recorded_with_no_platform():
    store = _store()
    run_id = store.start_run({})

    store.record_event(
        run_id,
        "story:haru:2026-10-05",
        JobType.STORY,
        "haru",
        None,
        "2026-10-05",
        JobEventKind.ARC_DONE,
    )

    events = store.events_for_run(run_id)
    assert events[0]["platform"] is None
    assert events[0]["kind"] == "arc_done"


def test_schema_upgrades_a_db_whose_jobs_table_predates_the_story_type(tmp_path):
    """
    A `JOBS_DB_PATH` created before the `story` job type (and nullable
    `platform`) existed has a `jobs`/`job_events` CHECK constraint that
    rejects both. SQLite cannot `ALTER` a CHECK constraint, so `JobStore`
    must rebuild those two tables (preserving their rows) rather than fail
    to open the DB or silently keep the old, incompatible constraint.
    """
    db_path = tmp_path / "state.db"
    old_conn = sqlite3.connect(str(db_path))
    old_conn.executescript(
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK (type IN ('plan', 'generate_image', 'schedule')),
            profile TEXT NOT NULL,
            platform TEXT NOT NULL CHECK (platform IN ('meta', 'fanvue')),
            status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'done', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            params_hash TEXT
        );
        CREATE TABLE fan_in_counters (
            group_key TEXT PRIMARY KEY,
            remaining INTEGER NOT NULL
        );
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            args TEXT,
            outcome TEXT
        );
        CREATE TABLE job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('plan', 'generate_image', 'schedule')),
            profile TEXT NOT NULL,
            platform TEXT NOT NULL CHECK (platform IN ('meta', 'fanvue')),
            week TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    old_conn.execute(
        "INSERT INTO jobs (id, type, profile, platform, status) "
        "VALUES ('plan:haru:meta:2026-09-01', 'plan', 'haru', 'meta', 'done')"
    )
    old_conn.execute(
        "INSERT INTO runs (run_id, started_at, finished_at, args, outcome) "
        "VALUES ('run-old', '2026-09-01T00:00:00+00:00', NULL, '{}', NULL)"
    )
    old_conn.execute(
        "INSERT INTO job_events "
        "(run_id, job_id, type, profile, platform, week, kind, detail, created_at) "
        "VALUES ('run-old', 'plan:haru:meta:2026-09-01', 'plan', 'haru', 'meta', "
        "'2026-09-01', 'plan_done', NULL, '2026-09-01T00:00:00+00:00')"
    )
    old_conn.commit()
    old_conn.close()

    store = JobStore(db_path)

    # Pre-existing rows in both rebuilt tables survived the upgrade.
    assert store.status("plan:haru:meta:2026-09-01") is JobStatus.DONE
    old_events = store.events_for_run("run-old")
    assert len(old_events) == 1
    assert old_events[0]["kind"] == "plan_done"

    # And the new shape (story type, nullable platform) is now usable.
    status = store.create("story:haru:2026-10-05", JobType.STORY, "haru", None)
    assert status is JobStatus.PENDING
    run_id = store.start_run({})
    store.record_event(
        run_id,
        "story:haru:2026-10-05",
        JobType.STORY,
        "haru",
        None,
        "2026-10-05",
        JobEventKind.ARC_DONE,
    )
    assert len(store.events_for_run(run_id)) == 1


def test_schema_upgrade_is_a_noop_on_a_db_already_on_the_current_shape(tmp_path):
    """Opening a DB a second time (the normal case across `jobs run`
    invocations) must not re-trigger the rename/copy/drop migration dance."""
    db_path = tmp_path / "state.db"
    JobStore(db_path).close()

    store = JobStore(db_path)  # second open: schema already current

    status = store.create("story:haru:2026-10-05", JobType.STORY, "haru", None)
    assert status is JobStatus.PENDING
