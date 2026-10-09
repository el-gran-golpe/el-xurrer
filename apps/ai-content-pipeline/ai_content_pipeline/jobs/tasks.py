import asyncio
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator, Type, Union

from loguru import logger

from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.generation.publications_generator import (
    DirectoryManager,
    ImageSpec,
    _parse_day,
)
from ai_content_pipeline.integrations.fanvue.publisher import FanvueAPIPublisher
from ai_content_pipeline.integrations.meta.graph_api import MetaPublisher
from ai_content_pipeline.jobs.generation_backend import GenerationBackend
from ai_content_pipeline.jobs.queue import Job, Queue
from ai_content_pipeline.jobs.store import JobEventKind, JobStatus, JobStore, JobType
from ai_content_pipeline.planning.planning_manager import (
    PlanningManager,
    build_previous_storyline,
)
from ai_content_pipeline.profiles.repository import ProfileRepository
from ai_content_pipeline.publishing.posting_scheduler import PostingScheduler

Publisher = Union[Type[MetaPublisher], Type[FanvueAPIPublisher]]


@dataclass(frozen=True)
class ProfileJob:
    """Payload of a `plan` or a `schedule` node: one profile+platform+week."""

    profile: Profile
    platform: Platform
    week: str
    # `plan` payload only (unused, left at 0, for `schedule`): how many more
    # weeks follow this one in a `--weeks N` chain. `run_plan` enqueues the
    # next week's plan job (with this decremented) only after this week's
    # plan is done and fanned out — see `run_plan`.
    remaining_weeks: int = 0


@dataclass(frozen=True)
class ImageJob:
    """Payload of a `generate_image` node: one image."""

    profile: Profile
    platform: Platform
    week: str
    spec: ImageSpec
    output_path: Path
    planning_hash: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _outputs_dir(profile: Profile, platform: Platform) -> Path:
    return Path(profile.platform_info[platform].outputs_path)


def _publications_dir(profile: Profile, platform: Platform) -> Path:
    return _outputs_dir(profile, platform) / "publications"


def plan_job_id(profile: Profile, platform: Platform, week: str) -> str:
    return f"{JobType.PLAN.value}:{profile.name}:{platform.value}:{week}"


def schedule_job_id(profile: Profile, platform: Platform, week: str) -> str:
    # Has a week dimension, unlike before `--weeks N`: with several weeks
    # planned in one `jobs run`, each week's images must fan in to their own
    # `schedule` job. One id per profile+platform (no week) would make the
    # second week's `_enqueue_schedule` reset the first week's params hash
    # (and fan-in group) through the same job id, instead of each week
    # getting its own resumable node.
    return f"{JobType.SCHEDULE.value}:{profile.name}:{platform.value}:{week}"


def _image_job_id(profile: Profile, platform: Platform, output_path: Path) -> str:
    # Relative to the publications folder so the id (and therefore resume)
    # survives the repo living at a different absolute path.
    rel = output_path.relative_to(_publications_dir(profile, platform))
    return f"{JobType.GENERATE_IMAGE.value}:{profile.name}:{platform.value}:{rel.as_posix()}"


@dataclass(frozen=True)
class ParsedJobId:
    type: str
    profile: str
    platform: str
    week: str


def parse_job_id(job_id: str) -> ParsedJobId:
    """
    Recovers (type, profile, platform, week) from a job id built by
    `plan_job_id`/`schedule_job_id`/`_image_job_id`. Used only by `jobs
    status`'s overview, to group the long-lived `jobs` table by week even
    for nodes created before `job_events` existed — the `jobs` table itself
    has no week column.

    `plan`/`schedule` ids are `{type}:{profile}:{platform}:{week}`, so the
    4th colon-split segment is the week verbatim. `generate_image` ids are
    `{type}:{profile}:{platform}:{week}/day_N/{slug}_{index}.jpeg` — the
    week is the first path segment of that same 4th part. Profile names and
    `Platform` values never contain a colon or a slash, so `split(":", 3)`
    is unambiguous either way.

    Real DBs created before `schedule_job_id` grew a week dimension (ahead
    of `--weeks N`) still have `schedule:{profile}:{platform}` rows with no
    4th segment at all — observed against `.cache/jobs/migrated.db`. Those
    parse to `week="unknown"` instead of raising, so `jobs status` can still
    show the rest of the DB.
    """
    parts = job_id.split(":", 3)
    job_type = parts[0] if len(parts) > 0 else ""
    profile = parts[1] if len(parts) > 1 else ""
    platform = parts[2] if len(parts) > 2 else ""
    week = parts[3].split("/", 1)[0] if len(parts) > 3 else "unknown"
    return ParsedJobId(type=job_type, profile=profile, platform=platform, week=week)


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
    repository: ProfileRepository,
    run_id: str,
) -> None:
    """
    Plans one profile+platform, then fans out one `generate_image` per image.

    A `plan` already `done` with unchanged inputs is not re-planned, but the
    fan-out still runs: that is what makes a resumed run re-enqueue only the
    images it never finished.

    `--weeks N` is a DAG edge, not a seed-time batch: `payload.remaining_weeks`
    carries how many more weeks follow this one, and this function enqueues
    the next week's `plan` job itself, only after this week's plan is done
    (freshly planned or already done) *and* fanned out. If planning this week
    raises, nothing below it runs — no fan-out, no next-week enqueue — so a
    failed week never lets a later week plan on top of it (which would read
    the wrong "previous week" and get re-planned/regenerated for nothing once
    the failed week is finally planned on a later run).

    `run_id` (from `JobStore.start_run`, created once per `jobs run`
    invocation) tags every `job_events` row this call records, so the
    end-of-run summary and `jobs status` can group events by run.
    """
    payload: ProfileJob = job.payload
    profile, platform, week = payload.profile, payload.platform, payload.week

    # Hash exactly what the prompt gets: the previous-storyline text (persona
    # + platform notes + last week's recap) plus the validated prompts JSON
    # plus the target week. That way changing the previous week's plan
    # correctly invalidates this one, and nothing else does.
    platform_profile = repository.get_platform_profile(profile, platform)
    previous_storyline = build_previous_storyline(
        repository, profile, platform, platform_profile, use_initial_conditions, week
    )
    inputs = platform_profile.model_dump_json(include={"lang", "prompts"})
    inputs += previous_storyline
    inputs += week
    status = store.create(job.id, JobType.PLAN, profile.name, platform, _hash(inputs))
    replanned = status is not JobStatus.DONE

    try:
        if not replanned:
            logger.info(
                "Plan already done for {} {} week {}, reusing it",
                profile.name,
                platform.value,
                week,
            )
            store.record_event(
                run_id,
                job.id,
                JobType.PLAN,
                profile.name,
                platform,
                week,
                JobEventKind.PLAN_REUSED,
            )
        else:
            try:
                with _running(store, job.id):
                    outcomes = await asyncio.to_thread(
                        PlanningManager(
                            template_profiles=[profile],
                            platform_name=platform,
                            use_initial_conditions=use_initial_conditions,
                            refresh_model_cache=refresh_model_cache,
                            repository=repository,
                            target_week=date.fromisoformat(week),
                        ).plan
                    )
            except Exception as e:
                store.record_event(
                    run_id,
                    job.id,
                    JobType.PLAN,
                    profile.name,
                    platform,
                    week,
                    JobEventKind.PLAN_FAILED,
                    detail={
                        "error": f"{type(e).__name__}: {e}",
                        "invalid_attempts": getattr(e, "invalid_attempts", []),
                    },
                )
                raise
            logger.success(
                "{} planning done for {} week {}.", platform.name, profile.name, week
            )
            outcome = outcomes[0]
            store.record_event(
                run_id,
                job.id,
                JobType.PLAN,
                profile.name,
                platform,
                week,
                JobEventKind.PLAN_DONE,
                detail={
                    "attempt": outcome.attempt,
                    "max_attempts": outcome.max_attempts,
                    "model": outcome.model,
                    "used_fallback": outcome.used_fallback,
                    "pinned_corrections": outcome.pinned_corrections,
                },
            )
            for invalid_error in outcome.invalid_attempts:
                store.record_event(
                    run_id,
                    job.id,
                    JobType.PLAN,
                    profile.name,
                    platform,
                    week,
                    JobEventKind.PLAN_ATTEMPT_INVALID,
                    detail={"error": invalid_error},
                )

        if replanned:
            _remove_stale_images(
                profile,
                platform,
                repository.get_week_plan(profile, platform, week),
                store,
                run_id,
            )

        await _fan_out_images(profile, platform, week, store, queue, repository, run_id)
    except Exception:
        if payload.remaining_weeks > 0:
            next_week = (date.fromisoformat(week) + timedelta(days=7)).isoformat()
            logger.warning(
                "Week {} for {} {} not enqueued: week {} plan failed",
                next_week,
                profile.name,
                platform.value,
                week,
            )
            store.record_event(
                run_id,
                job.id,
                JobType.PLAN,
                profile.name,
                platform,
                week,
                JobEventKind.WEEK_NOT_ENQUEUED,
                detail={"next_week": next_week},
            )
        raise

    if payload.remaining_weeks > 0:
        next_week = (date.fromisoformat(week) + timedelta(days=7)).isoformat()
        await queue.enqueue(
            JobType.PLAN.value,
            Job(
                id=plan_job_id(profile, platform, next_week),
                payload=ProfileJob(
                    profile=profile,
                    platform=platform,
                    week=next_week,
                    remaining_weeks=payload.remaining_weeks - 1,
                ),
            ),
        )


def _planned_images(
    profile: Profile, platform: Platform, plan: WeekPlan
) -> list[tuple[Path, ImageSpec]]:
    """Every image this plan calls for, as (output_path, spec) pairs."""
    week_folder = _publications_dir(profile, platform) / plan.week
    images: list[tuple[Path, ImageSpec]] = []
    for day in plan.days:
        day_folder = week_folder / f"day_{day.day}"
        for publication in _parse_day(day):
            for spec in publication.images:
                images.append(
                    (day_folder / f"{publication.slug}_{spec.index}.jpeg", spec)
                )
    return images


def _remove_stale_images(
    profile: Profile,
    platform: Platform,
    plan: WeekPlan,
    store: JobStore,
    run_id: str,
) -> None:
    """
    Called right after a week was actually (re)planned (not the "already
    done" path), before fan-out. New titles produce new file names
    (`{slug}_{index}.jpeg`), so a re-plan can leave old images sitting in
    `publications/{week}/day_*/` that `PostingScheduler` would otherwise glob
    and publish alongside the new ones. Only this week's own day folders are
    touched; `captions.txt`/`upload_times.txt` are untouched (`DirectoryManager`
    rewrites those) and so are other weeks' folders.
    """
    week_folder = _publications_dir(profile, platform) / plan.week
    if not week_folder.is_dir():
        return
    expected = {path for path, _ in _planned_images(profile, platform, plan)}
    for day_folder in sorted(p for p in week_folder.glob("day_*") if p.is_dir()):
        images = (
            list(day_folder.glob("*.jpeg"))
            + list(day_folder.glob("*.jpg"))
            + list(day_folder.glob("*.png"))
        )
        for image_path in sorted(images):
            if image_path not in expected:
                logger.info(
                    "Removing stale image {} (week {} was re-planned)",
                    image_path,
                    plan.week,
                )
                image_path.unlink()
                # The image no longer belongs to the plan, so neither does
                # its job: without this, `jobs status` would keep counting it.
                stale_job_id = _image_job_id(profile, platform, image_path)
                store.forget(stale_job_id)
                store.record_event(
                    run_id,
                    stale_job_id,
                    JobType.GENERATE_IMAGE,
                    profile.name,
                    platform,
                    plan.week,
                    JobEventKind.IMAGE_STALE_REMOVED,
                    detail={"path": str(image_path), "reason": "week was re-planned"},
                )


async def _fan_out_images(
    profile: Profile,
    platform: Platform,
    week: str,
    store: JobStore,
    queue: Queue,
    repository: ProfileRepository,
    run_id: str,
) -> None:
    plan = repository.get_week_plan(profile, platform, week)
    planning_hash = _hash(plan.model_dump_json())
    publications_dir = _publications_dir(profile, platform)

    # captions.txt / upload_times.txt belong to the plan node, not to any
    # image: schedule reads them, so they must exist before any child runs.
    DirectoryManager(publications_dir).create_structure(plan)

    children: list[ImageJob] = [
        ImageJob(
            profile=profile,
            platform=platform,
            week=week,
            spec=spec,
            output_path=output_path,
            planning_hash=planning_hash,
        )
        for output_path, spec in _planned_images(profile, platform, plan)
    ]

    store.init_counter(_group_key(profile, platform, planning_hash), len(children))

    pending: list[tuple[str, ImageJob]] = []
    for child in children:
        job_id = _image_job_id(profile, platform, child.output_path)
        new_hash = _hash(child.spec.description)
        # Read the stored hash *before* `store.create` overwrites it, so a
        # description change hiding behind an unchanged file name (same
        # slug+index, different image_description — `_remove_stale_images`
        # only catches a changed *name*) can be detected here: delete the
        # stale file so `run_generate_image`'s `output_path.exists()` check
        # does not short-circuit into skipping a regeneration it should do.
        previous_hash = store.params_hash(job_id)
        status = store.create(
            job_id,
            JobType.GENERATE_IMAGE,
            profile.name,
            platform,
            new_hash,
        )
        if status is not JobStatus.DONE:
            if (
                previous_hash is not None
                and previous_hash != new_hash
                and child.output_path.exists()
            ):
                logger.info(
                    "Removing stale image {} (description changed for the "
                    "same file name)",
                    child.output_path,
                )
                child.output_path.unlink()
                store.record_event(
                    run_id,
                    job_id,
                    JobType.GENERATE_IMAGE,
                    profile.name,
                    platform,
                    week,
                    JobEventKind.IMAGE_STALE_REMOVED,
                    detail={
                        "path": str(child.output_path),
                        "reason": "description changed for the same file name",
                    },
                )
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
        await _enqueue_schedule(profile, platform, week, planning_hash, store, queue)
        return
    for job_id, child in pending:
        await queue.enqueue(JobType.GENERATE_IMAGE.value, Job(id=job_id, payload=child))


async def run_generate_image(
    job: Job,
    store: JobStore,
    queue: Queue,
    backend: GenerationBackend,
    run_id: str,
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
        store.record_event(
            run_id,
            job.id,
            JobType.GENERATE_IMAGE,
            profile.name,
            platform,
            payload.week,
            JobEventKind.IMAGE_REUSED,
        )
    else:
        try:
            with _running(store, job.id):
                await backend.generate(payload.spec, payload.output_path)
        except Exception as e:
            store.record_event(
                run_id,
                job.id,
                JobType.GENERATE_IMAGE,
                profile.name,
                platform,
                payload.week,
                JobEventKind.IMAGE_FAILED,
                detail={"error": f"{type(e).__name__}: {e}"},
            )
            raise
        logger.success("Image saved at: {}", payload.output_path)
        store.record_event(
            run_id,
            job.id,
            JobType.GENERATE_IMAGE,
            profile.name,
            platform,
            payload.week,
            JobEventKind.IMAGE_GENERATED,
        )

    remaining = store.decrement_counter(
        _group_key(profile, platform, payload.planning_hash)
    )
    if remaining <= 0:
        await _enqueue_schedule(
            profile, platform, payload.week, payload.planning_hash, store, queue
        )


async def _enqueue_schedule(
    profile: Profile,
    platform: Platform,
    week: str,
    planning_hash: str,
    store: JobStore,
    queue: Queue,
) -> None:
    # One `schedule` per profile+platform+week (see schedule_job_id). Its
    # params hash is the planning hash, so a re-planned week resets it to
    # pending, and the payload's week limits what it publishes.
    job_id = schedule_job_id(profile, platform, week)
    status = store.create(
        job_id, JobType.SCHEDULE, profile.name, platform, planning_hash
    )
    if status is JobStatus.DONE:
        logger.info(
            "Schedule already done for {} {} week {}",
            profile.name,
            platform.value,
            week,
        )
        return
    await queue.enqueue(
        JobType.SCHEDULE.value,
        Job(
            id=job_id,
            payload=ProfileJob(profile=profile, platform=platform, week=week),
        ),
    )


async def run_schedule(
    job: Job, store: JobStore, publisher: Publisher, run_id: str
) -> None:
    """
    Uploads/schedules one profile+platform, same call as pipeline.schedule,
    but restricted to the week this job was planned for — `jobs run` never
    clears `outputs/`, so older week folders (including a legacy `week_1`)
    can still be sitting under `publications/` with past-due upload times
    that `PostingScheduler` would otherwise publish again immediately.
    """
    payload: ProfileJob = job.payload
    try:
        with _running(store, job.id):
            await PostingScheduler(
                template_profiles=[payload.profile],
                platform_name=payload.platform,
                publisher=publisher,
                weeks={payload.week},
            ).upload()
    except Exception as e:
        store.record_event(
            run_id,
            job.id,
            JobType.SCHEDULE,
            payload.profile.name,
            payload.platform,
            payload.week,
            JobEventKind.SCHEDULE_FAILED,
            detail={"error": f"{type(e).__name__}: {e}"},
        )
        raise
    store.record_event(
        run_id,
        job.id,
        JobType.SCHEDULE,
        payload.profile.name,
        payload.platform,
        payload.week,
        JobEventKind.SCHEDULE_DONE,
    )
