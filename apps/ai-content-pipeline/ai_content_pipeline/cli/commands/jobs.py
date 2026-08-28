import asyncio
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from ai_content_pipeline.cli.commands.utils import (
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
from ai_content_pipeline.jobs.generation_backend import (
    GenerationBackend,
    LocalComfyBackend,
)
from ai_content_pipeline.jobs.queue import Job, Queue
from ai_content_pipeline.jobs.store import JobStore, JobType
from ai_content_pipeline.jobs.tasks import (
    ProfileJob,
    Publisher,
    plan_job_id,
    run_generate_image,
    run_plan,
    run_schedule,
)
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
    use_initial_conditions: bool,
    refresh_model_cache: bool,
    schedule_concurrency: int,
) -> None:
    """
    Wires the 3 job types onto the queue. Concurrency is decided here, per
    type, because it is a property of the resource each type contends for:

    - plan: 1, because ModelRouter's key cursor is not concurrency-safe.
    - generate_image: 1, one local GPU (LocalComfyBackend). A backend for a
      different resource would ask for a different number.
    - schedule: one worker per possible schedule job, because Meta scheduling
      sleeps until each upload_time and must not hold the others behind it.
    """

    async def handle_plan(batch: list[Job]) -> None:
        await run_plan(
            batch[0],
            store,
            queue,
            use_initial_conditions=use_initial_conditions,
            refresh_model_cache=refresh_model_cache,
        )

    async def handle_generate_image(batch: list[Job]) -> None:
        job = batch[0]
        await run_generate_image(job, store, queue, backends[job.payload.profile.name])

    async def handle_schedule(batch: list[Job]) -> None:
        job = batch[0]
        await run_schedule(job, store, PUBLISHERS[job.payload.platform])

    queue.register(JobType.PLAN.value, handle_plan, concurrency=1)
    queue.register(JobType.GENERATE_IMAGE.value, handle_generate_image, concurrency=1)
    queue.register(
        JobType.SCHEDULE.value, handle_schedule, concurrency=schedule_concurrency
    )


async def seed_plans(queue: Queue, profiles: list[Profile]) -> None:
    """
    Seeds one `plan` root per profile+platform. Always seeded, even when the
    plan is already `done`: run_plan skips the planning itself but still fans
    out, which is how a resumed run re-enqueues only unfinished images.
    """
    for profile in profiles:
        for platform in profile.platform_info:
            await queue.enqueue(
                JobType.PLAN.value,
                Job(
                    id=plan_job_id(profile, platform),
                    payload=ProfileJob(profile=profile, platform=platform),
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
) -> None:
    db_path = Path(settings.jobs_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Jobs state: {}", db_path)

    store = JobStore(db_path)
    queue = Queue()
    try:
        register_handlers(
            queue,
            store,
            build_backends(profiles),
            use_initial_conditions=use_initial_conditions,
            refresh_model_cache=refresh_model_cache,
            schedule_concurrency=max(1, len(profiles) * len(Platform)),
        )
        await seed_plans(queue, profiles)
        await queue.run()
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
):
    """
    Run plan -> generate -> schedule as a DAG for the selected profiles.

    Resumable: re-running the same command after a crash or Ctrl+C skips
    whatever already completed. Unlike `all run_all` this never clears
    outputs/, because those files are the checkpoint.
    """
    profiles = resolve_profiles(profile_indexes, profile_names, default_all=True)
    if not profiles:
        logger.warning("No profiles to process")
        return

    for profile in profiles:
        validate_meta_profile_auth(profile)

    asyncio.run(_execute(profiles, use_initial_conditions, refresh_model_cache))
    get_gdrive_sync().push(RESOURCES_DIR)
    logger.success("✅  DAG run finished for {} profile(s).", len(profiles))
