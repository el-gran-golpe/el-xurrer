import asyncio
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Type, Union

from loguru import logger

from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.generation.publications_generator import (
    DirectoryManager,
    ImageSpec,
    _load_planning,
    _parse_day,
)
from ai_content_pipeline.integrations.fanvue.publisher import FanvueAPIPublisher
from ai_content_pipeline.integrations.meta.graph_api import MetaPublisher
from ai_content_pipeline.jobs.generation_backend import GenerationBackend
from ai_content_pipeline.jobs.queue import Job, Queue
from ai_content_pipeline.jobs.store import JobStatus, JobStore, JobType
from ai_content_pipeline.planning.planning_manager import PlanningManager
from ai_content_pipeline.publishing.posting_scheduler import PostingScheduler

Publisher = Union[Type[MetaPublisher], Type[FanvueAPIPublisher]]


@dataclass(frozen=True)
class ProfileJob:
    """Payload of a `plan` or a `schedule` node: one profile+platform."""

    profile: Profile
    platform: Platform


@dataclass(frozen=True)
class ImageJob:
    """Payload of a `generate_image` node: one image."""

    profile: Profile
    platform: Platform
    spec: ImageSpec
    output_path: Path
    planning_hash: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _outputs_dir(profile: Profile, platform: Platform) -> Path:
    return Path(profile.platform_info[platform].outputs_path)


def _planning_path(profile: Profile, platform: Platform) -> Path:
    # Same filename convention as PublicationsGenerator.generate.
    initials = "".join(part[0] for part in profile.name.split("_"))
    return _outputs_dir(profile, platform) / f"{initials}_planning.json"


def _publications_dir(profile: Profile, platform: Platform) -> Path:
    return _outputs_dir(profile, platform) / "publications"


def plan_job_id(profile: Profile, platform: Platform) -> str:
    return f"{JobType.PLAN.value}:{profile.name}:{platform.value}"


def schedule_job_id(profile: Profile, platform: Platform) -> str:
    return f"{JobType.SCHEDULE.value}:{profile.name}:{platform.value}"


def _image_job_id(profile: Profile, platform: Platform, output_path: Path) -> str:
    # Relative to the publications folder so the id (and therefore resume)
    # survives the repo living at a different absolute path.
    rel = output_path.relative_to(_publications_dir(profile, platform))
    return f"{JobType.GENERATE_IMAGE.value}:{profile.name}:{platform.value}:{rel.as_posix()}"


def _group_key(profile: Profile, platform: Platform, planning_hash: str) -> str:
    """
    Fan-in group for the `schedule` node. The planning hash is part of the key
    so a re-planned week gets a fresh counter instead of reusing the old one,
    whose total was the previous week's image count.
    """
    return f"{profile.name}:{platform.value}:{planning_hash}"


@contextmanager
def _running(store: JobStore, job_id: str) -> Iterator[None]:
    store.mark_running(job_id)
    try:
        yield
    except Exception as e:
        # httpx/transport errors often have an empty str(); keep the type name.
        store.mark_failed(job_id, f"{type(e).__name__}: {e}")
        raise
    store.mark_done(job_id)


async def run_plan(
    job: Job,
    store: JobStore,
    queue: Queue,
    *,
    use_initial_conditions: bool,
    refresh_model_cache: bool = False,
) -> None:
    """
    Plans one profile+platform, then fans out one `generate_image` per image.

    A `plan` already `done` with unchanged inputs is not re-planned, but the
    fan-out still runs: that is what makes a resumed run re-enqueue only the
    images it never finished.
    """
    payload: ProfileJob = job.payload
    profile, platform = payload.profile, payload.platform
    inputs = Path(profile.platform_info[platform].inputs_path)

    prompts = (inputs / f"{profile.name}.json").read_text(encoding="utf-8")
    conditions = (
        (inputs / "initial_conditions.md").read_text(encoding="utf-8")
        if use_initial_conditions
        else ""
    )
    status = store.create(
        job.id, JobType.PLAN, profile.name, platform, _hash(prompts + conditions)
    )

    if status is JobStatus.DONE:
        logger.info(
            "Plan already done for {} {}, reusing {}",
            profile.name,
            platform.value,
            _planning_path(profile, platform).name,
        )
    else:
        with _running(store, job.id):
            await asyncio.to_thread(
                PlanningManager(
                    template_profiles=[profile],
                    platform_name=platform,
                    use_initial_conditions=use_initial_conditions,
                    refresh_model_cache=refresh_model_cache,
                ).plan
            )
        logger.success("{} planning done for {}.", platform.name, profile.name)

    await _fan_out_images(profile, platform, store, queue)


async def _fan_out_images(
    profile: Profile, platform: Platform, store: JobStore, queue: Queue
) -> None:
    planning_path = _planning_path(profile, platform)
    planning: dict[str, list[dict[str, Any]]] = _load_planning(planning_path)
    planning_hash = _hash(planning_path.read_text(encoding="utf-8"))
    publications_dir = _publications_dir(profile, platform)

    # captions.txt / upload_times.txt belong to the plan node, not to any
    # image: schedule reads them, so they must exist before any child runs.
    DirectoryManager(publications_dir).create_structure(planning)

    children: list[ImageJob] = []
    for week, days in planning.items():
        for day_data in days:
            day_folder = publications_dir / week / f"day_{day_data['day']}"
            for publication in _parse_day(day_data):
                for spec in publication.images:
                    children.append(
                        ImageJob(
                            profile=profile,
                            platform=platform,
                            spec=spec,
                            output_path=day_folder
                            / f"{publication.slug}_{spec.index}.jpeg",
                            planning_hash=planning_hash,
                        )
                    )

    store.init_counter(_group_key(profile, platform, planning_hash), len(children))

    pending: list[tuple[str, ImageJob]] = []
    for child in children:
        job_id = _image_job_id(profile, platform, child.output_path)
        status = store.create(
            job_id,
            JobType.GENERATE_IMAGE,
            profile.name,
            platform,
            _hash(child.spec.description),
        )
        if status is not JobStatus.DONE:
            pending.append((job_id, child))

    logger.info(
        "{} {}: {}/{} images to generate",
        profile.name,
        platform.value,
        len(pending),
        len(children),
    )

    if not pending:
        # Nothing left to wait for, so the fan-in counter will never reach 0
        # on its own — enqueue schedule directly.
        await _enqueue_schedule(profile, platform, planning_hash, store, queue)
        return
    for job_id, child in pending:
        await queue.enqueue(JobType.GENERATE_IMAGE.value, Job(id=job_id, payload=child))


async def run_generate_image(
    job: Job, store: JobStore, queue: Queue, backend: GenerationBackend
) -> None:
    """
    Generates one image, then enqueues `schedule` if it was the last one
    outstanding for its profile+platform (fan-in). A failure raises, so the
    counter is not decremented and `schedule` cannot start with a missing
    image; the retry happens on the next run.
    """
    payload: ImageJob = job.payload
    profile, platform = payload.profile, payload.platform

    if payload.output_path.exists():
        # Same skip-if-exists as ImageGeneratorService today: cheaper than
        # trusting the store alone when the file is already on disk.
        logger.info("Skipping existing image: {}", payload.output_path)
        store.mark_done(job.id)
    else:
        with _running(store, job.id):
            await backend.generate(payload.spec, payload.output_path)
        logger.success("Image saved at: {}", payload.output_path)

    remaining = store.decrement_counter(
        _group_key(profile, platform, payload.planning_hash)
    )
    if remaining <= 0:
        await _enqueue_schedule(profile, platform, payload.planning_hash, store, queue)


async def _enqueue_schedule(
    profile: Profile,
    platform: Platform,
    planning_hash: str,
    store: JobStore,
    queue: Queue,
) -> None:
    job_id = schedule_job_id(profile, platform)
    status = store.create(
        job_id, JobType.SCHEDULE, profile.name, platform, planning_hash
    )
    if status is JobStatus.DONE:
        logger.info("Schedule already done for {} {}", profile.name, platform.value)
        return
    await queue.enqueue(
        JobType.SCHEDULE.value,
        Job(id=job_id, payload=ProfileJob(profile=profile, platform=platform)),
    )


async def run_schedule(job: Job, store: JobStore, publisher: Publisher) -> None:
    """Uploads/schedules one profile+platform, same call as pipeline.schedule."""
    payload: ProfileJob = job.payload
    with _running(store, job.id):
        await PostingScheduler(
            template_profiles=[payload.profile],
            platform_name=payload.platform,
            publisher=publisher,
        ).upload()
