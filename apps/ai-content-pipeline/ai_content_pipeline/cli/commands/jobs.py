import asyncio
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from ai_content_pipeline.cli.commands.utils import (
    profile_repository,
    get_gdrive_sync,
    resolve_profiles,
)
from ai_content_pipeline.config import settings
from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.integrations.comfyui.local import ComfyLocal
from ai_content_pipeline.integrations.fanvue.publisher import FanvueAPIPublisher
from ai_content_pipeline.integrations.meta.graph_api import (
    MetaPublisher,
    validate_meta_profile_auth,
)
from ai_content_pipeline.jobs import report
from ai_content_pipeline.jobs.generation_backend import (
    GenerationBackend,
    LocalComfyBackend,
)
from ai_content_pipeline.jobs.queue import Job, Queue
from ai_content_pipeline.jobs.store import JobEventKind, JobStore, JobType
from ai_content_pipeline.jobs.tasks import (
    ProfileJob,
    Publisher,
    parse_job_id,
    plan_job_id,
    run_generate_image,
    run_plan,
    run_schedule,
)
from ai_content_pipeline.llm.utils.utils import planning_week_start
from ai_content_pipeline.profiles.repository import ProfileRepository
from ai_content_pipeline.paths import RESOURCES_DIR

app = typer.Typer(help="Run the plan -> generate -> schedule DAG with resume support")

PUBLISHERS: dict[Platform, Publisher] = {
    Platform.META: MetaPublisher,
    Platform.FANVUE: FanvueAPIPublisher,
}


def register_handlers(
    queue: Queue,
    store: JobStore,
    backends: dict[str, GenerationBackend],
    *,
    repository: ProfileRepository,
    use_initial_conditions: bool,
    refresh_model_cache: bool,
    schedule_concurrency: int,
    run_id: str,
    skip_schedule: bool = False,
) -> None:
    """
    Wires the 3 job types onto the queue. Concurrency is decided here, per
    type, because it is a property of the resource each type contends for:

    - plan: 1, because ModelRouter's key cursor is not concurrency-safe.
      `--weeks N` week ordering no longer depends on this being FIFO: each
      week's `plan` job enqueues the next week itself (`run_plan`), once its
      own plan is done and fanned out, so the chain is explicit DAG edges
      rather than queue order.
    - generate_image: 1, one local GPU (LocalComfyBackend). A backend for a
      different resource would ask for a different number.
    - schedule: one worker per possible schedule job, because Meta scheduling
      sleeps until each upload_time and must not hold the others behind it.
      With `--weeks N`, each profile+platform can have up to N schedule jobs
      outstanding at once (one per planned week), so the caller multiplies
      its worker count by `weeks` too — otherwise week 1's Meta sleep would
      block week 2's schedule job for the same profile+platform.
    """

    async def handle_plan(batch: list[Job]) -> None:
        await run_plan(
            batch[0],
            store,
            queue,
            use_initial_conditions=use_initial_conditions,
            refresh_model_cache=refresh_model_cache,
            repository=repository,
            run_id=run_id,
        )

    async def handle_generate_image(batch: list[Job]) -> None:
        job = batch[0]
        await run_generate_image(
            job, store, queue, backends[job.payload.profile.name], run_id
        )

    async def handle_schedule(batch: list[Job]) -> None:
        job = batch[0]
        payload: ProfileJob = job.payload
        if skip_schedule:
            # Left pending on purpose, so a later run without the flag publishes it.
            logger.warning("Skipping publish for {} (--skip-schedule)", job.id)
            store.record_event(
                run_id,
                job.id,
                JobType.SCHEDULE,
                payload.profile.name,
                payload.platform,
                payload.week,
                JobEventKind.SCHEDULE_SKIPPED,
            )
            return
        await run_schedule(job, store, PUBLISHERS[job.payload.platform], run_id)

    queue.register(JobType.PLAN.value, handle_plan, concurrency=1)
    queue.register(JobType.GENERATE_IMAGE.value, handle_generate_image, concurrency=1)
    queue.register(
        JobType.SCHEDULE.value, handle_schedule, concurrency=schedule_concurrency
    )


async def seed_plans(queue: Queue, profiles: list[Profile], weeks: int = 1) -> None:
    """
    Seeds one `plan` root per profile+platform: only the FIRST target week.
    `weeks=1` (the default, same as before `--weeks N`) is the whole chain;
    `weeks=N` seeds that first week with `remaining_weeks=N-1`, and `run_plan`
    itself enqueues each following week's `plan` job as a DAG edge — only
    after the week before it is done (freshly planned or already done) and
    fanned out. This guarantees week order without relying on the `plan`
    queue being FIFO, and — more importantly — means a failed week k is
    never followed by week k+1 being planned on top of it in the same run:
    `run_plan` only reaches the "enqueue next week" step if planning this
    week and fanning it out succeeded.

    The starting week is computed once here, not per profile/platform or
    inside `PlanningManager`, so every job in this run agrees on the same
    target week even if the run straddles midnight.

    Always seeded, even when a plan is already `done`: run_plan skips the
    planning itself but still fans out, which is how a resumed run
    re-enqueues only unfinished images — and, for `--weeks N`, still walks
    the chain forward to whichever week is not yet done.
    """
    start = planning_week_start(date.today())
    week = start.isoformat()
    for profile in profiles:
        for platform in profile.platform_info:
            await queue.enqueue(
                JobType.PLAN.value,
                Job(
                    id=plan_job_id(profile, platform, week),
                    payload=ProfileJob(
                        profile=profile,
                        platform=platform,
                        week=week,
                        remaining_weeks=weeks - 1,
                    ),
                ),
            )


def build_backends(profiles: list[Profile]) -> dict[str, GenerationBackend]:
    """
    One backend per profile, because the ComfyUI workflow is per profile
    (`{profile}_comfyworkflow.json`). Connection is checked once up front so a
    ComfyUI that is down fails before any planning burns LLM quota.
    """
    backends: dict[str, GenerationBackend] = {}
    for profile in profiles:
        client = ComfyLocal(
            workflow_path=RESOURCES_DIR
            / profile.name
            / f"{profile.name}_comfyworkflow.json",
            server_host=settings.comfy_host,
            server_port=settings.comfy_port,
        )
        if not backends:
            client.check_connection()
        backends[profile.name] = LocalComfyBackend(client)
    return backends


async def _execute(
    profiles: list[Profile],
    use_initial_conditions: bool,
    refresh_model_cache: bool,
    skip_schedule: bool,
    weeks: int,
) -> tuple[str, list[report.RunRow]]:
    """
    Runs the DAG to completion and returns `(run_id, rows)`: `rows` is this
    run's end-of-run summary (built from `job_events`), for the caller
    (`run()`) to render, log, write to a file, and decide the exit code
    from. The `Queue` itself swallows handler exceptions (logging them and
    moving on, so one failed node does not kill the whole run) — `job_events`
    is how failures still surface here instead of being silently absorbed.
    """
    db_path = Path(settings.jobs_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Jobs state: {}", db_path)

    store = JobStore(db_path)
    run_id = store.start_run(
        {
            "profiles": [p.name for p in profiles],
            "weeks": weeks,
            "skip_schedule": skip_schedule,
            "use_initial_conditions": use_initial_conditions,
            "refresh_model_cache": refresh_model_cache,
        }
    )
    queue = Queue()
    try:
        register_handlers(
            queue,
            store,
            build_backends(profiles),
            repository=profile_repository,
            use_initial_conditions=use_initial_conditions,
            refresh_model_cache=refresh_model_cache,
            # One schedule job per profile+platform+week can be outstanding
            # at once, so the worker count must scale with `weeks` too.
            schedule_concurrency=max(1, len(profiles) * len(Platform) * weeks),
            run_id=run_id,
            skip_schedule=skip_schedule,
        )
        await seed_plans(queue, profiles, weeks)
        await queue.run()
        rows = report.build_run_rows(store.events_for_run(run_id))
        store.finish_run(run_id, "failed" if report.count_failures(rows) else "success")
        return run_id, rows
    finally:
        store.close()


@app.command("run")
def run(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
    refresh_model_cache: bool = typer.Option(
        False, "--refresh-model-cache", help="Refresh the cached model catalog."
    ),
    skip_schedule: bool = typer.Option(
        False,
        "--skip-schedule",
        help="Plan and generate only: never publish to Meta/Fanvue, and never "
        "sleep until upload_time. The schedule jobs stay pending for a later run.",
    ),
    weeks: int = typer.Option(
        1,
        "--weeks",
        min=1,
        help="Plan this many consecutive weeks per profile+platform in this "
        "run (today's target week, then the following weeks one after "
        "another), instead of only the current one.",
    ),
):
    """
    Run plan -> generate -> schedule as a DAG for the selected profiles.

    Resumable: re-running the same command after a crash or Ctrl+C skips
    whatever already completed. Unlike `all run_all` this never clears
    outputs/, because those files are the checkpoint.
    """
    profiles = resolve_profiles(profile_indexes, profile_names)
    if not profiles:
        logger.warning("No profiles to process")
        return

    if not skip_schedule:
        # Nothing will be published in this run, so there is nothing to
        # validate Meta auth against.
        for profile in profiles:
            validate_meta_profile_auth(profile)

    _run_id, rows = asyncio.run(
        _execute(
            profiles, use_initial_conditions, refresh_model_cache, skip_schedule, weeks
        )
    )
    get_gdrive_sync().push(RESOURCES_DIR)

    table = report.render_table(rows)
    report_dir = Path(settings.jobs_report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    report_path = report_dir / f"{timestamp}_jobs_run.md"
    report_path.write_text(f"# jobs run — {timestamp}\n\n{table}\n", encoding="utf-8")

    logger.info("\n{}", table)
    failures = report.count_failures(rows)
    if failures:
        logger.error(
            "❌  DAG run finished with {} failure(s) — see {}", failures, report_path
        )
        raise typer.Exit(1)
    logger.success("✅  DAG run finished — see {}", report_path)


@app.command("status")
def status(
    run: Optional[str] = typer.Option(
        None, "--run", help="Show this run id instead of the most recent one."
    ),
    show_runs: bool = typer.Option(
        False,
        "--runs",
        help="List recent runs (id, started, finished, outcome, "
        "failure count) instead of a report.",
    ),
    limit: int = typer.Option(
        10, "--limit", help="How many recent runs to list with --runs."
    ),
) -> None:
    """
    Read-only report on `jobs run` state from JOBS_DB_PATH: the last run's
    summary (or a specific `--run <id>`), plus a per profile/platform/week
    overview of current plan/images/schedule status. Never seeds or runs
    jobs, never pulls from Google Drive, never needs ComfyUI or LLM keys —
    `cli/main.py`'s top-level callback special-cases `jobs status` to skip
    the startup Drive pull and profile loading entirely.
    """
    db_path = Path(settings.jobs_db_path)
    if not db_path.exists():
        typer.echo(f"No jobs database found at {db_path}.")
        return

    store = JobStore(db_path)
    try:
        if show_runs:
            typer.echo(report.render_runs_list(store.list_runs(limit)))
            return

        target_run_id = run or store.last_run_id()
        if target_run_id is None:
            typer.echo("No runs recorded yet.")
        else:
            typer.echo(f"Run {target_run_id}:\n")
            typer.echo(
                report.render_table(
                    report.build_run_rows(store.events_for_run(target_run_id))
                )
            )
            typer.echo("")

        overview_jobs = [
            {**job, **vars(parse_job_id(job["id"]))} for job in store.all_jobs()
        ]
        typer.echo("Current state:\n")
        typer.echo(report.render_overview(report.build_overview_rows(overview_jobs)))
    finally:
        store.close()
