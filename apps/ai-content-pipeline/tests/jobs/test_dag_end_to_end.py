"""
Drives the real Queue through the real CLI wiring (register_handlers +
seed_plans), with only the 3 external boundaries faked: the LLM planner,
ComfyUI, and the publisher. This is what proves the pieces fit together.
"""

import json
from pathlib import Path

import pytest

from ai_content_pipeline.cli.commands import jobs as jobs_cli
from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.generation.publications_generator import ImageSpec
from ai_content_pipeline.integrations.fanvue.publisher import FanvueAPIPublisher
from ai_content_pipeline.integrations.meta.graph_api import MetaPublisher
from ai_content_pipeline.jobs import tasks
from ai_content_pipeline.jobs.queue import Queue
from ai_content_pipeline.jobs.store import JobStatus, JobType

PLANNING = {
    "week_1": [
        {
            "day": 1,
            "posts": [
                {
                    "title": "Beach day",
                    "caption": "sun",
                    "hashtags": ["#sun"],
                    "upload_time": "2026-09-01T10:00:00Z",
                    "images": [
                        {"image_description": "a beach"},
                        {"image_description": "a wave"},
                    ],
                }
            ],
        }
    ]
}


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

        def plan(self) -> None:
            planned.append(self.kwargs)
            tasks._planning_path(
                self.kwargs["template_profiles"][0], self.kwargs["platform_name"]
            ).write_text(json.dumps(PLANNING), encoding="utf-8")

    class FakePostingScheduler:
        def __init__(self, **kwargs):
            uploaded.append(kwargs)

        async def upload(self) -> None:
            pass

    monkeypatch.setattr(tasks, "PlanningManager", FakePlanningManager)
    monkeypatch.setattr(tasks, "PostingScheduler", FakePostingScheduler)
    return planned, uploaded


async def _run_dag(profile: Profile, store, backend) -> None:
    queue = Queue()
    jobs_cli.register_handlers(
        queue,
        store,
        {profile.name: backend},
        use_initial_conditions=True,
        refresh_model_cache=False,
        schedule_concurrency=2,
    )
    await jobs_cli.seed_plans(queue, [profile])
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
        assert store.status(tasks.plan_job_id(profile, platform)) is JobStatus.DONE
        assert store.status(tasks.schedule_job_id(profile, platform)) is JobStatus.DONE


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
        tasks.plan_job_id(profile, platform) for platform in Platform
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
        use_initial_conditions=True,
        refresh_model_cache=False,
        schedule_concurrency=2,
        skip_schedule=True,
    )
    await jobs_cli.seed_plans(queue, [profile])
    await queue.run()

    assert len(backend.generated) == 2 * len(Platform)
    assert uploaded == []
    for platform in Platform:
        # Left pending, so a later run without the flag still publishes it.
        assert (
            store.status(tasks.schedule_job_id(profile, platform)) is JobStatus.PENDING
        )
