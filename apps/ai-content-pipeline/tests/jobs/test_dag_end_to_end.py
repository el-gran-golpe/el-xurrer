"""
Drives the real Queue through the real CLI wiring (register_handlers +
seed_plans), with only the 3 external boundaries faked: the LLM planner,
ComfyUI, and the publisher. This is what proves the pieces fit together.
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_content_pipeline.cli.commands import jobs as jobs_cli
from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import repository_for
from ai_content_pipeline.generation.publications_generator import ImageSpec
from ai_content_pipeline.integrations.fanvue.publisher import FanvueAPIPublisher
from ai_content_pipeline.integrations.meta.graph_api import MetaPublisher
from ai_content_pipeline.jobs import tasks
from ai_content_pipeline.jobs.queue import Queue
from ai_content_pipeline.jobs.store import JobStatus, JobType
from ai_content_pipeline.llm.utils.utils import planning_week_start
from ai_content_pipeline.planning.planning_manager import PlanOutcome

# Same deterministic rule `seed_plans` uses, so these tests agree with it on
# which week a run today targets.
WEEK = planning_week_start(date.today()).isoformat()

PLANNING_DAYS = [
    {
        "day": 1,
        "posts": [
            {
                "title": "Beach day",
                "caption": "sun",
                "hashtags": "#sun",
                "upload_time": "2026-09-01T10:00:00Z",
                "images": [
                    {"image_description": "a beach"},
                    {"image_description": "a wave"},
                ],
            }
        ],
    }
]


class FakeBackend:
    def __init__(self) -> None:
        self.generated: list[Path] = []

    async def generate(self, spec: ImageSpec, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"jpeg")
        self.generated.append(output_path)


@pytest.fixture
def fakes(monkeypatch, profile: Profile):
    """Fakes the LLM planner and the publisher; returns what each recorded."""
    planned: list[dict] = []
    uploaded: list[dict] = []

    class FakePlanningManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def plan(self) -> list[PlanOutcome]:
            planned.append(self.kwargs)
            profile_ = self.kwargs["template_profiles"][0]
            week = self.kwargs["target_week"].isoformat()
            repository_for(profile_).save_week_plan(
                profile_,
                self.kwargs["platform_name"],
                WeekPlan.from_planning_dict({week: PLANNING_DAYS}),
            )
            return [
                PlanOutcome(
                    profile=profile_.name,
                    week=week,
                    attempt=1,
                    max_attempts=5,
                    model="openrouter/fake-model",
                    used_fallback=False,
                    pinned_corrections=0,
                    invalid_attempts=[],
                )
            ]

    class FakePostingScheduler:
        def __init__(self, **kwargs):
            uploaded.append(kwargs)

        async def upload(self) -> None:
            pass

    monkeypatch.setattr(tasks, "PlanningManager", FakePlanningManager)
    monkeypatch.setattr(tasks, "PostingScheduler", FakePostingScheduler)
    return planned, uploaded


async def _run_dag(profile: Profile, store, backend, weeks: int = 1) -> None:
    queue = Queue()
    jobs_cli.register_handlers(
        queue,
        store,
        {profile.name: backend},
        repository=repository_for(profile),
        use_initial_conditions=True,
        refresh_model_cache=False,
        # One schedule worker per profile+platform+week, same formula as
        # `_execute`.
        schedule_concurrency=len(Platform) * weeks,
        run_id=store.start_run({}),
    )
    await jobs_cli.seed_plans(queue, [profile], weeks)
    await queue.run()


@pytest.mark.asyncio
async def test_a_full_run_plans_generates_and_schedules_every_platform(
    profile, store, fakes
):
    planned, uploaded = fakes
    backend = FakeBackend()

    await _run_dag(profile, store, backend)

    # One plan and one schedule per platform, two images each.
    assert {call["platform_name"] for call in planned} == set(Platform)
    assert len(backend.generated) == 2 * len(Platform)
    assert all(path.exists() for path in backend.generated)
    assert {call["platform_name"] for call in uploaded} == set(Platform)
    for platform in Platform:
        assert (
            store.status(tasks.plan_job_id(profile, platform, WEEK)) is JobStatus.DONE
        )
        assert (
            store.status(tasks.schedule_job_id(profile, platform, WEEK))
            is JobStatus.DONE
        )


@pytest.mark.asyncio
async def test_each_platform_schedules_with_its_own_publisher(profile, store, fakes):
    _, uploaded = fakes

    await _run_dag(profile, store, FakeBackend())

    publishers = {call["platform_name"]: call["publisher"] for call in uploaded}
    assert publishers[Platform.META] is MetaPublisher
    assert publishers[Platform.FANVUE] is FanvueAPIPublisher


@pytest.mark.asyncio
async def test_rerunning_after_a_finished_run_does_no_work_again(profile, store, fakes):
    planned, uploaded = fakes
    await _run_dag(profile, store, FakeBackend())

    second_backend = FakeBackend()
    await _run_dag(profile, store, second_backend)

    assert len(planned) == len(Platform)  # not re-planned
    assert second_backend.generated == []  # not re-generated
    assert len(uploaded) == len(Platform)  # not re-published


@pytest.mark.asyncio
async def test_a_crash_mid_generation_resumes_without_repeating_finished_images(
    profile, store, fakes
):
    planned, uploaded = fakes

    class CrashingBackend(FakeBackend):
        async def generate(self, spec: ImageSpec, output_path: Path) -> None:
            if len(self.generated) == 2:
                raise RuntimeError("ComfyUI died")
            await super().generate(spec, output_path)

    crashed = CrashingBackend()
    await _run_dag(profile, store, crashed)

    assert len(crashed.generated) == 2  # the rest failed
    assert len(uploaded) < len(Platform)  # at least one platform never scheduled

    resumed = FakeBackend()
    await _run_dag(profile, store, resumed)

    assert len(planned) == len(Platform)  # planning never repeated
    assert len(resumed.generated) == 2 * len(Platform) - 2  # only the missing ones
    assert len(uploaded) == len(Platform)  # every platform published in the end


@pytest.mark.asyncio
async def test_seed_plans_seeds_one_plan_per_profile_and_platform(profile):
    queue = Queue()
    queue.register(JobType.PLAN.value, lambda batch: None)

    await jobs_cli.seed_plans(queue, [profile])

    seeded = [await queue._queues[JobType.PLAN.value].get() for _ in Platform]
    assert sorted(job.id for job in seeded) == sorted(
        tasks.plan_job_id(profile, platform, WEEK) for platform in Platform
    )


@pytest.mark.asyncio
async def test_skip_schedule_generates_everything_but_never_publishes(
    profile, store, fakes
):
    _, uploaded = fakes
    backend = FakeBackend()
    queue = Queue()
    jobs_cli.register_handlers(
        queue,
        store,
        {profile.name: backend},
        repository=repository_for(profile),
        use_initial_conditions=True,
        refresh_model_cache=False,
        schedule_concurrency=2,
        run_id=store.start_run({}),
        skip_schedule=True,
    )
    await jobs_cli.seed_plans(queue, [profile])
    await queue.run()

    assert len(backend.generated) == 2 * len(Platform)
    assert uploaded == []
    for platform in Platform:
        # Left pending, so a later run without the flag still publishes it.
        assert (
            store.status(tasks.schedule_job_id(profile, platform, WEEK))
            is JobStatus.PENDING
        )


@pytest.mark.asyncio
async def test_seed_plans_seeds_only_the_first_week_with_the_rest_as_remaining_weeks(
    profile,
):
    """
    `--weeks N` is no longer a seed-time batch: `seed_plans` enqueues only
    the first target week per profile+platform, carrying how many more
    weeks follow in `ProfileJob.remaining_weeks`. `run_plan` is responsible
    for enqueuing week k+1 itself, as a DAG edge, only once week k is done
    and fanned out (see `test_tasks.py` for that half).
    """
    queue = Queue()
    queue.register(JobType.PLAN.value, lambda batch: None)

    await jobs_cli.seed_plans(queue, [profile], weeks=3)

    seeded = [await queue._queues[JobType.PLAN.value].get() for _ in Platform]
    assert queue._queues[JobType.PLAN.value].empty()  # nothing else seeded upfront
    start = planning_week_start(date.today())
    for job in seeded:
        assert job.payload.week == start.isoformat()
        assert job.payload.remaining_weeks == 2


@pytest.mark.asyncio
async def test_weeks_n_fans_out_and_schedules_each_week_independently(
    profile, store, fakes
):
    """Two weeks planned in one run must each fan out their own images and
    fan in to their own `schedule` job, instead of sharing one counter."""
    planned, uploaded = fakes
    backend = FakeBackend()

    await _run_dag(profile, store, backend, weeks=2)

    start = planning_week_start(date.today())
    week1 = start.isoformat()
    week2 = (start + timedelta(days=7)).isoformat()

    assert len(planned) == 2 * len(Platform)
    assert len(backend.generated) == 2 * 2 * len(Platform)  # 2 images/week
    assert all(path.exists() for path in backend.generated)
    assert len(uploaded) == 2 * len(Platform)
    for platform in Platform:
        assert (
            store.status(tasks.plan_job_id(profile, platform, week1)) is JobStatus.DONE
        )
        assert (
            store.status(tasks.plan_job_id(profile, platform, week2)) is JobStatus.DONE
        )
        assert (
            store.status(tasks.schedule_job_id(profile, platform, week1))
            is JobStatus.DONE
        )
        assert (
            store.status(tasks.schedule_job_id(profile, platform, week2))
            is JobStatus.DONE
        )


@pytest.mark.asyncio
async def test_rerunning_weeks_2_after_everything_done_plans_nothing(
    profile, store, fakes
):
    planned, uploaded = fakes
    await _run_dag(profile, store, FakeBackend(), weeks=2)

    second_backend = FakeBackend()
    await _run_dag(profile, store, second_backend, weeks=2)

    assert len(planned) == 2 * len(Platform)  # not re-planned
    assert second_backend.generated == []  # not re-generated
    assert len(uploaded) == 2 * len(Platform)  # not re-published


@pytest.mark.asyncio
async def test_a_mid_chain_plan_failure_blocks_the_rest_of_the_chain_then_a_rerun_continues_it(
    profile, store, monkeypatch
):
    """
    Week 2 of a 3-week run fails once (per platform). Week 3 must not be
    planned in that same run — `seed_plans` only seeds week 1, and `run_plan`
    only enqueues week k+1 after week k succeeds. Re-running must plan week 2
    (now succeeding) and then continue the chain on to week 3, without
    re-planning week 1.
    """
    planned: list[dict] = []
    start = planning_week_start(date.today())
    week2 = (start + timedelta(days=7)).isoformat()
    week3 = (start + timedelta(days=14)).isoformat()
    failed_once: set[Platform] = set()

    class FlakyPlanningManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def plan(self) -> list[PlanOutcome]:
            week = self.kwargs["target_week"].isoformat()
            platform = self.kwargs["platform_name"]
            if week == week2 and platform not in failed_once:
                failed_once.add(platform)
                raise ValueError("transient failure")
            planned.append(self.kwargs)
            profile_ = self.kwargs["template_profiles"][0]
            repository_for(profile_).save_week_plan(
                profile_,
                platform,
                WeekPlan.from_planning_dict({week: PLANNING_DAYS}),
            )
            return [
                PlanOutcome(
                    profile=profile_.name,
                    week=week,
                    attempt=1,
                    max_attempts=5,
                    model="openrouter/fake-model",
                    used_fallback=False,
                    pinned_corrections=0,
                    invalid_attempts=[],
                )
            ]

    class NoopPostingScheduler:
        def __init__(self, **kwargs):
            pass

        async def upload(self) -> None:
            pass

    monkeypatch.setattr(tasks, "PlanningManager", FlakyPlanningManager)
    monkeypatch.setattr(tasks, "PostingScheduler", NoopPostingScheduler)

    await _run_dag(profile, store, FakeBackend(), weeks=3)

    # Week 1 planned for every platform; week 2 failed, so week 3 never got
    # a chance to be seeded in this run.
    assert len(planned) == len(Platform)
    for platform in Platform:
        assert (
            store.status(tasks.plan_job_id(profile, platform, week2))
            is JobStatus.FAILED
        )
        assert store.status(tasks.plan_job_id(profile, platform, week3)) is None

    # Re-run: week 2 now succeeds (armed only once), and the chain continues
    # on to week 3 — week 1 is not re-planned.
    await _run_dag(profile, store, FakeBackend(), weeks=3)

    assert len(planned) == 3 * len(Platform)
    for platform in Platform:
        assert (
            store.status(tasks.plan_job_id(profile, platform, week2)) is JobStatus.DONE
        )
        assert (
            store.status(tasks.plan_job_id(profile, platform, week3)) is JobStatus.DONE
        )


@pytest.mark.asyncio
async def test_running_weeks_3_after_weeks_2_only_plans_the_third_week(
    profile, store, fakes
):
    planned, uploaded = fakes
    await _run_dag(profile, store, FakeBackend(), weeks=2)
    assert len(planned) == 2 * len(Platform)

    third_backend = FakeBackend()
    await _run_dag(profile, store, third_backend, weeks=3)

    start = planning_week_start(date.today())
    week3 = (start + timedelta(days=14)).isoformat()

    # Only one new plan call per platform, and it targets week 3.
    assert len(planned) == 3 * len(Platform)
    newly_planned_weeks = {
        call["target_week"].isoformat() for call in planned[-len(Platform) :]
    }
    assert newly_planned_weeks == {week3}
    # Only the new week's images get generated.
    assert len(third_backend.generated) == 2 * len(Platform)
    assert len(uploaded) == 3 * len(Platform)
