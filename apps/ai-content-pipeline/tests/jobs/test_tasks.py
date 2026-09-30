import json
from pathlib import Path

import pytest

from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.generation.publications_generator import ImageSpec
from ai_content_pipeline.jobs import tasks
from ai_content_pipeline.jobs.queue import Job
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
        },
        {
            "day": 2,
            "posts": [
                {
                    "title": "Coffee",
                    "caption": "brew",
                    "hashtags": [],
                    "upload_time": "2026-09-02T10:00:00Z",
                    "images": [{"image_description": "a latte"}],
                }
            ],
        },
    ]
}


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, Job]] = []

    async def enqueue(self, job_type: str, job: Job) -> None:
        self.enqueued.append((job_type, job))

    def ids(self, job_type: JobType) -> list[str]:
        return [job.id for t, job in self.enqueued if t == job_type.value]


class FakeBackend:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.generated: list[Path] = []

    async def generate(self, spec: ImageSpec, output_path: Path) -> None:
        if self.fail:
            raise RuntimeError("comfy exploded")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"jpeg")
        self.generated.append(output_path)


def _write_planning(profile: Profile, planning: dict = PLANNING) -> Path:
    path = tasks._planning_path(profile, Platform.META)
    path.write_text(json.dumps(planning), encoding="utf-8")
    return path


def _plan_job(profile: Profile) -> Job:
    return Job(
        id=tasks.plan_job_id(profile, Platform.META),
        payload=tasks.ProfileJob(profile=profile, platform=Platform.META),
    )


def _fake_planning_manager(monkeypatch, profile: Profile, calls: list) -> None:
    class FakePlanningManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def plan(self) -> None:
            calls.append(self.kwargs)
            _write_planning(profile)

    monkeypatch.setattr(tasks, "PlanningManager", FakePlanningManager)


@pytest.mark.asyncio
async def test_run_plan_plans_writes_text_artifacts_and_fans_out_per_image(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    queue = FakeQueue()

    await tasks.run_plan(_plan_job(profile), store, queue, use_initial_conditions=True)

    assert len(calls) == 1
    assert calls[0]["platform_name"] is Platform.META
    day_1 = tasks._publications_dir(profile, Platform.META) / "week_1" / "day_1"
    assert (day_1 / "captions.txt").read_text(encoding="utf-8") == "sun\n#sun"
    assert (day_1 / "upload_times.txt").exists()
    assert queue.ids(JobType.GENERATE_IMAGE) == [
        "generate_image:haru:meta:week_1/day_1/beach-day_0.jpeg",
        "generate_image:haru:meta:week_1/day_1/beach-day_1.jpeg",
        "generate_image:haru:meta:week_1/day_2/coffee_0.jpeg",
    ]
    assert store.status(tasks.plan_job_id(profile, Platform.META)) is JobStatus.DONE


@pytest.mark.asyncio
async def test_run_plan_does_not_replan_when_inputs_are_unchanged_but_still_fans_out(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile), store, FakeQueue(), use_initial_conditions=True
    )

    queue = FakeQueue()
    await tasks.run_plan(_plan_job(profile), store, queue, use_initial_conditions=True)

    assert len(calls) == 1  # not re-planned
    assert len(queue.ids(JobType.GENERATE_IMAGE)) == 3  # children re-enqueued


@pytest.mark.asyncio
async def test_run_plan_replans_when_the_prompt_inputs_changed(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile), store, FakeQueue(), use_initial_conditions=True
    )

    inputs = Path(profile.platform_info[Platform.META].inputs_path)
    (inputs / "haru.json").write_text('{"prompts": ["new"]}', encoding="utf-8")
    await tasks.run_plan(
        _plan_job(profile), store, FakeQueue(), use_initial_conditions=True
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_plan_enqueues_schedule_directly_when_every_image_is_already_done(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    queue = FakeQueue()
    await tasks.run_plan(_plan_job(profile), store, queue, use_initial_conditions=True)
    for job_id in queue.ids(JobType.GENERATE_IMAGE):
        store.mark_done(job_id)

    second = FakeQueue()
    await tasks.run_plan(_plan_job(profile), store, second, use_initial_conditions=True)

    assert second.ids(JobType.GENERATE_IMAGE) == []
    assert second.ids(JobType.SCHEDULE) == ["schedule:haru:meta"]


async def _plan_and_get_image_jobs(profile, store, queue, monkeypatch) -> list[Job]:
    _fake_planning_manager(monkeypatch, profile, [])
    await tasks.run_plan(_plan_job(profile), store, queue, use_initial_conditions=True)
    return [job for t, job in queue.enqueued if t == JobType.GENERATE_IMAGE.value]


@pytest.mark.asyncio
async def test_the_last_image_of_a_group_enqueues_schedule_and_the_others_do_not(
    profile, store, monkeypatch
):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)
    backend = FakeBackend()

    for job in image_jobs[:-1]:
        await tasks.run_generate_image(job, store, queue, backend)
    assert queue.ids(JobType.SCHEDULE) == []

    await tasks.run_generate_image(image_jobs[-1], store, queue, backend)

    assert queue.ids(JobType.SCHEDULE) == ["schedule:haru:meta"]
    assert len(backend.generated) == 3


@pytest.mark.asyncio
async def test_a_failed_image_leaves_the_job_failed_and_does_not_enqueue_schedule(
    profile, store, monkeypatch
):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)

    with pytest.raises(RuntimeError):
        await tasks.run_generate_image(
            image_jobs[0], store, queue, FakeBackend(fail=True)
        )

    assert store.status(image_jobs[0].id) is JobStatus.FAILED
    assert queue.ids(JobType.SCHEDULE) == []


@pytest.mark.asyncio
async def test_an_existing_image_file_is_not_regenerated(profile, store, monkeypatch):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)
    job = image_jobs[0]
    job.payload.output_path.parent.mkdir(parents=True, exist_ok=True)
    job.payload.output_path.write_bytes(b"already there")
    backend = FakeBackend()

    await tasks.run_generate_image(job, store, queue, backend)

    assert backend.generated == []
    assert store.status(job.id) is JobStatus.DONE


@pytest.mark.asyncio
async def test_resume_finishes_the_remaining_images_and_still_reaches_schedule(
    profile, store, monkeypatch
):
    # Run 1: two of three images generated, then the process "dies".
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)
    backend = FakeBackend()
    for job in image_jobs[:2]:
        await tasks.run_generate_image(job, store, queue, backend)
    assert queue.ids(JobType.SCHEDULE) == []

    # Run 2: same command again — only the unfinished image is re-enqueued,
    # and finishing it must still trip the fan-in counter.
    resumed = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile), store, resumed, use_initial_conditions=True
    )
    assert len(resumed.ids(JobType.GENERATE_IMAGE)) == 1

    remaining_job = [
        job for t, job in resumed.enqueued if t == JobType.GENERATE_IMAGE.value
    ][0]
    await tasks.run_generate_image(remaining_job, store, resumed, backend)

    assert resumed.ids(JobType.SCHEDULE) == ["schedule:haru:meta"]
    assert len(backend.generated) == 3


@pytest.mark.asyncio
async def test_run_schedule_uploads_that_profile_and_platform(
    profile, store, monkeypatch
):
    seen: list[dict] = []

    class FakeScheduler:
        def __init__(self, **kwargs):
            seen.append(kwargs)

        async def upload(self) -> None:
            pass

    monkeypatch.setattr(tasks, "PostingScheduler", FakeScheduler)
    job_id = tasks.schedule_job_id(profile, Platform.META)
    store.create(job_id, JobType.SCHEDULE, profile.name, Platform.META)
    job = Job(
        id=job_id, payload=tasks.ProfileJob(profile=profile, platform=Platform.META)
    )

    await tasks.run_schedule(job, store, publisher="publisher-cls")

    assert seen == [
        {
            "template_profiles": [profile],
            "platform_name": Platform.META,
            "publisher": "publisher-cls",
        }
    ]
    assert store.status(job_id) is JobStatus.DONE
