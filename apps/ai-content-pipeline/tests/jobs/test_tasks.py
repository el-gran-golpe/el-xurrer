import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import repository_for, write_persona
from ai_content_pipeline.generation.publications_generator import ImageSpec
from ai_content_pipeline.jobs import tasks
from ai_content_pipeline.jobs.queue import Job
from ai_content_pipeline.jobs.store import JobStatus, JobType
from ai_content_pipeline.planning import planning_manager as planning_manager_module
from ai_content_pipeline.planning.planning_manager import PlanOutcome

# The target week these tests plan for, fixed so folder/job-id assertions
# never depend on today's real date.
WEEK = "2026-09-01"

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
    },
    {
        "day": 2,
        "posts": [
            {
                "title": "Coffee",
                "caption": "brew",
                "hashtags": "",
                "upload_time": "2026-09-02T10:00:00Z",
                "images": [{"image_description": "a latte"}],
            }
        ],
    },
]


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


def _fake_outcome(profile: Profile, week: str) -> PlanOutcome:
    """A plausible `PlanOutcome` for test doubles that fake `PlanningManager`
    entirely — these tests exercise `run_plan`'s event recording, not the
    real retry/model-selection logic (covered in `tests/planning`)."""
    return PlanOutcome(
        profile=profile.name,
        week=week,
        attempt=1,
        max_attempts=5,
        model="openrouter/fake-model",
        used_fallback=False,
        pinned_corrections=0,
        invalid_attempts=[],
    )


def _plan_job(profile: Profile, week: str = WEEK) -> Job:
    return Job(
        id=tasks.plan_job_id(profile, Platform.META, week),
        payload=tasks.ProfileJob(profile=profile, platform=Platform.META, week=week),
    )


def _fake_planning_manager(monkeypatch, profile: Profile, calls: list) -> None:
    """
    Fakes PlanningManager so these tests exercise run_plan's resume/fan-out
    wiring, not the LLM stack. Writes a plan keyed by the job's target week,
    same as the real PlanningManager overriding whatever key the LLM used.
    """

    class FakePlanningManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def plan(self) -> list[PlanOutcome]:
            calls.append(self.kwargs)
            week = self.kwargs["target_week"].isoformat()
            repository_for(profile).save_week_plan(
                profile,
                Platform.META,
                WeekPlan.from_planning_dict({week: PLANNING_DAYS}),
            )
            return [_fake_outcome(profile, week)]

    monkeypatch.setattr(tasks, "PlanningManager", FakePlanningManager)


@pytest.mark.asyncio
async def test_run_plan_plans_writes_text_artifacts_and_fans_out_per_image(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    queue = FakeQueue()

    await tasks.run_plan(
        _plan_job(profile),
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 1
    assert calls[0]["platform_name"] is Platform.META
    assert calls[0]["target_week"].isoformat() == WEEK
    day_1 = tasks._publications_dir(profile, Platform.META) / WEEK / "day_1"
    assert (day_1 / "captions.txt").read_text(encoding="utf-8") == "sun\n#sun"
    assert (day_1 / "upload_times.txt").exists()
    assert queue.ids(JobType.GENERATE_IMAGE) == [
        f"generate_image:haru:meta:{WEEK}/day_1/beach-day_0.jpeg",
        f"generate_image:haru:meta:{WEEK}/day_1/beach-day_1.jpeg",
        f"generate_image:haru:meta:{WEEK}/day_2/coffee_0.jpeg",
    ]
    assert (
        store.status(tasks.plan_job_id(profile, Platform.META, WEEK)) is JobStatus.DONE
    )


@pytest.mark.asyncio
async def test_run_plan_does_not_replan_when_inputs_are_unchanged_but_still_fans_out(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    queue = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile),
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 1  # not re-planned
    assert len(queue.ids(JobType.GENERATE_IMAGE)) == 3  # children re-enqueued


@pytest.mark.asyncio
async def test_run_plan_replans_when_the_prompt_inputs_changed(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    inputs = Path(profile.platform_info[Platform.META].inputs_path)
    prompts = json.loads((inputs / "haru.json").read_text(encoding="utf-8"))
    prompts["lang"] = "es"
    (inputs / "haru.json").write_text(json.dumps(prompts), encoding="utf-8")
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_plan_replans_when_the_target_week_changed(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile, week=WEEK),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    await tasks.run_plan(
        _plan_job(profile, week="2026-09-08"),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_plan_replans_when_the_previous_weeks_plan_changed(
    profile, store, monkeypatch
):
    """
    run_plan hashes exactly what the prompt gets, which includes a recap of
    the previous week (`build_previous_storyline`). Changing that archived
    plan must invalidate the resume hash for the week that reads it.
    """
    calls: list = []
    repo = repository_for(profile)
    previous = WeekPlan.from_planning_dict(
        {"2026-08-25": [{"day": 1, "posts": [{"caption": "first pass"}]}]}
    )
    repo.save_week_plan(profile, Platform.META, previous)

    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )
    assert len(calls) == 1

    # The previous week is now archived (this run's plan became current);
    # change its content.
    history_path = (
        profile.platform_info[Platform.META].outputs_path
        / "history"
        / "2026-08-25_planning.json"
    )
    assert history_path.is_file()
    updated_previous = WeekPlan.from_planning_dict(
        {"2026-08-25": [{"day": 1, "posts": [{"caption": "revised pass"}]}]}
    )
    history_path.write_text(
        json.dumps(updated_previous.to_planning_dict()), encoding="utf-8"
    )

    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_editing_the_persona_does_trigger_a_replan(profile, store, monkeypatch):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    write_persona(profile, "29 now, moved to Lisbon")
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_plan_enqueues_schedule_directly_when_every_image_is_already_done(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    queue = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile),
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )
    for job_id in queue.ids(JobType.GENERATE_IMAGE):
        store.mark_done(job_id)

    second = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile),
        store,
        second,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert second.ids(JobType.GENERATE_IMAGE) == []
    assert second.ids(JobType.SCHEDULE) == [f"schedule:haru:meta:{WEEK}"]


async def _plan_and_get_image_jobs(profile, store, queue, monkeypatch) -> list[Job]:
    _fake_planning_manager(monkeypatch, profile, [])
    await tasks.run_plan(
        _plan_job(profile),
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )
    return [job for t, job in queue.enqueued if t == JobType.GENERATE_IMAGE.value]


@pytest.mark.asyncio
async def test_the_last_image_of_a_group_enqueues_schedule_and_the_others_do_not(
    profile, store, monkeypatch
):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)
    backend = FakeBackend()

    for job in image_jobs[:-1]:
        await tasks.run_generate_image(job, store, queue, backend, "run1")
    assert queue.ids(JobType.SCHEDULE) == []

    await tasks.run_generate_image(image_jobs[-1], store, queue, backend, "run1")

    assert queue.ids(JobType.SCHEDULE) == [f"schedule:haru:meta:{WEEK}"]
    assert len(backend.generated) == 3
    scheduled_payload = [
        job.payload for t, job in queue.enqueued if t == JobType.SCHEDULE.value
    ][0]
    assert scheduled_payload.week == WEEK


@pytest.mark.asyncio
async def test_a_failed_image_leaves_the_job_failed_and_does_not_enqueue_schedule(
    profile, store, monkeypatch
):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)

    with pytest.raises(RuntimeError):
        await tasks.run_generate_image(
            image_jobs[0], store, queue, FakeBackend(fail=True), "run1"
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

    await tasks.run_generate_image(job, store, queue, backend, "run1")

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
        await tasks.run_generate_image(job, store, queue, backend, "run1")
    assert queue.ids(JobType.SCHEDULE) == []

    # Run 2: same command again — only the unfinished image is re-enqueued,
    # and finishing it must still trip the fan-in counter.
    resumed = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile),
        store,
        resumed,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )
    assert len(resumed.ids(JobType.GENERATE_IMAGE)) == 1

    remaining_job = [
        job for t, job in resumed.enqueued if t == JobType.GENERATE_IMAGE.value
    ][0]
    await tasks.run_generate_image(remaining_job, store, resumed, backend, "run1")

    assert resumed.ids(JobType.SCHEDULE) == [f"schedule:haru:meta:{WEEK}"]
    assert len(backend.generated) == 3


@pytest.mark.asyncio
async def test_run_plan_enqueues_the_next_week_after_a_successful_plan_and_fan_out(
    profile, store, monkeypatch
):
    """`--weeks N` is a DAG edge: `run_plan` enqueues the next week's `plan`
    job itself, only once this week's plan is done and fanned out."""
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    queue = FakeQueue()
    job = Job(
        id=tasks.plan_job_id(profile, Platform.META, WEEK),
        payload=tasks.ProfileJob(
            profile=profile, platform=Platform.META, week=WEEK, remaining_weeks=2
        ),
    )

    await tasks.run_plan(
        job,
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    next_week = (date.fromisoformat(WEEK) + timedelta(days=7)).isoformat()
    next_plan_jobs = queue.ids(JobType.PLAN)
    assert next_plan_jobs == [tasks.plan_job_id(profile, Platform.META, next_week)]
    enqueued_payload = [
        j.payload for t, j in queue.enqueued if t == JobType.PLAN.value
    ][0]
    assert enqueued_payload.week == next_week
    assert enqueued_payload.remaining_weeks == 1


@pytest.mark.asyncio
async def test_run_plan_does_not_enqueue_a_next_week_when_none_remain(
    profile, store, monkeypatch
):
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    queue = FakeQueue()

    await tasks.run_plan(
        _plan_job(profile),  # remaining_weeks defaults to 0
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert queue.ids(JobType.PLAN) == []


@pytest.mark.asyncio
async def test_a_failed_plan_does_not_enqueue_the_next_week(
    profile, store, monkeypatch
):
    """
    A plan that raises (e.g. `PlanningManager.plan()` giving up after its own
    retries) must not let a later week in the chain get planned on top of it
    — that would read the wrong "previous week" and get silently re-planned
    once the failed week is eventually fixed.
    """

    class FailingPlanningManager:
        def __init__(self, **kwargs):
            pass

        def plan(self) -> None:
            raise ValueError("every attempt was invalid")

    monkeypatch.setattr(tasks, "PlanningManager", FailingPlanningManager)
    queue = FakeQueue()
    job = Job(
        id=tasks.plan_job_id(profile, Platform.META, WEEK),
        payload=tasks.ProfileJob(
            profile=profile, platform=Platform.META, week=WEEK, remaining_weeks=2
        ),
    )

    with pytest.raises(ValueError):
        await tasks.run_plan(
            job,
            store,
            queue,
            use_initial_conditions=True,
            repository=repository_for(profile),
            run_id="run1",
        )

    assert queue.ids(JobType.PLAN) == []
    assert store.status(job.id) is JobStatus.FAILED


def _planning_manager_writing(profile: Profile, days: list) -> type:
    """A fake `PlanningManager` that saves exactly `days` for whatever week
    it is asked to target, for the tests below that need control over the
    plan's content (titles, descriptions) across two `run_plan` calls."""

    class _Manager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def plan(self) -> list[PlanOutcome]:
            week = self.kwargs["target_week"].isoformat()
            repository_for(profile).save_week_plan(
                profile,
                self.kwargs["platform_name"],
                WeekPlan.from_planning_dict({week: days}),
            )
            return [_fake_outcome(profile, week)]

    return _Manager


def _force_replan(profile: Profile) -> None:
    """Changes a validated-prompts input so the next `run_plan` call's
    resume hash differs and it actually replans, same trick as
    `test_run_plan_replans_when_the_prompt_inputs_changed`."""
    inputs = Path(profile.platform_info[Platform.META].inputs_path)
    prompts = json.loads((inputs / "haru.json").read_text(encoding="utf-8"))
    prompts["lang"] = "es" if prompts["lang"] != "es" else "en"
    (inputs / "haru.json").write_text(json.dumps(prompts), encoding="utf-8")


@pytest.mark.asyncio
async def test_a_replan_removes_stale_images_with_old_file_names_but_keeps_unchanged_ones(
    profile, store, monkeypatch
):
    """
    New titles produce new file names (`{slug}_{index}.jpeg`); old images
    left behind under the old names must be deleted so `PostingScheduler`
    does not glob and publish them alongside the new ones. A post whose
    slug+index is unchanged keeps its file.
    """
    monkeypatch.setattr(
        tasks, "PlanningManager", _planning_manager_writing(profile, PLANNING_DAYS)
    )
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    day_1 = tasks._publications_dir(profile, Platform.META) / WEEK / "day_1"
    day_2 = tasks._publications_dir(profile, Platform.META) / WEEK / "day_2"
    stale_images = [day_1 / "beach-day_0.jpeg", day_1 / "beach-day_1.jpeg"]
    kept_image = day_2 / "coffee_0.jpeg"
    for path in [*stale_images, kept_image]:
        path.write_bytes(b"previously generated")

    # Day 1's title changes (new slug); day 2's does not.
    renamed_days = [
        {
            "day": 1,
            "posts": [
                {
                    "title": "Sunset",
                    "caption": "sun",
                    "upload_time": "2026-09-01T10:00:00Z",
                    "images": [
                        {"image_description": "a beach"},
                        {"image_description": "a wave"},
                    ],
                }
            ],
        },
        PLANNING_DAYS[1],
    ]
    _force_replan(profile)
    monkeypatch.setattr(
        tasks, "PlanningManager", _planning_manager_writing(profile, renamed_days)
    )

    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    for path in stale_images:
        assert not path.exists()
        # Its job goes too, so `jobs status` stops counting the image.
        assert store.status(tasks._image_job_id(profile, Platform.META, path)) is None
    assert kept_image.exists()
    assert store.status(tasks._image_job_id(profile, Platform.META, kept_image))


@pytest.mark.asyncio
async def test_a_plan_already_done_does_not_remove_any_images(
    profile, store, monkeypatch
):
    """Stale-image cleanup only runs after an actual (re)plan, never on the
    "already done" resume path — nothing changed, so nothing is stale."""
    monkeypatch.setattr(
        tasks, "PlanningManager", _planning_manager_writing(profile, PLANNING_DAYS)
    )
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    day_1 = tasks._publications_dir(profile, Platform.META) / WEEK / "day_1"
    leftover = day_1 / "some-unrelated-file.jpeg"
    leftover.write_bytes(b"not part of the current plan either")

    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert leftover.exists()


@pytest.mark.asyncio
async def test_a_description_change_under_the_same_file_name_deletes_the_stale_image(
    profile, store, monkeypatch
):
    """
    `_remove_stale_images` only catches a changed *file name*. If a re-plan
    keeps the same title (same slug+index) but changes the image
    description, the old file is still sitting at the same path. The image
    job's params_hash changes, so it is not `DONE`; `_fan_out_images` must
    delete that stale file itself so `run_generate_image`'s plain
    `output_path.exists()` check does not skip regenerating it.
    """
    monkeypatch.setattr(
        tasks, "PlanningManager", _planning_manager_writing(profile, PLANNING_DAYS)
    )
    queue = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile),
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )
    image_job = [job for t, job in queue.enqueued if t == JobType.GENERATE_IMAGE.value][
        0
    ]
    backend = FakeBackend()
    await tasks.run_generate_image(image_job, store, FakeQueue(), backend, "run1")
    assert image_job.payload.output_path.exists()

    changed_days = [
        {
            **PLANNING_DAYS[0],
            "posts": [
                {
                    **PLANNING_DAYS[0]["posts"][0],
                    "images": [
                        {"image_description": "a completely different scene"},
                        {"image_description": "a wave"},
                    ],
                }
            ],
        },
        PLANNING_DAYS[1],
    ]
    _force_replan(profile)
    monkeypatch.setattr(
        tasks, "PlanningManager", _planning_manager_writing(profile, changed_days)
    )

    second_queue = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile),
        store,
        second_queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    # Same output path, but it must have been deleted (and re-enqueued),
    # not silently left with the stale content from the old description.
    assert image_job.payload.output_path.name.startswith("beach-day_0")
    assert not image_job.payload.output_path.exists()
    reenqueued_ids = second_queue.ids(JobType.GENERATE_IMAGE)
    assert image_job.id in reenqueued_ids

    backend2 = FakeBackend()
    await tasks.run_generate_image(image_job, store, FakeQueue(), backend2, "run1")
    assert image_job.payload.output_path.exists()
    # Actually regenerated (not skipped via the exists() short-circuit): the
    # backend was called for this path.
    assert image_job.payload.output_path in backend2.generated


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
    job_id = tasks.schedule_job_id(profile, Platform.META, WEEK)
    store.create(job_id, JobType.SCHEDULE, profile.name, Platform.META)
    job = Job(
        id=job_id,
        payload=tasks.ProfileJob(profile=profile, platform=Platform.META, week=WEEK),
    )

    await tasks.run_schedule(job, store, publisher="publisher-cls", run_id="run1")

    assert seen == [
        {
            "template_profiles": [profile],
            "platform_name": Platform.META,
            "publisher": "publisher-cls",
            "weeks": {WEEK},
        }
    ]
    assert store.status(job_id) is JobStatus.DONE


class _ContinuityFakeBaseLLM:
    """
    Records what each `PlanningManager.plan()` call constructed it with, and
    replies with a full week keyed to whatever target week it was given —
    close enough to the real LLM reply shape for `WeekPlan.pin_to_week` to
    accept it.
    """

    instances: list["_ContinuityFakeBaseLLM"] = []

    def __init__(
        self, prompts, previous_storyline, platform_name, model_router, week_start
    ):
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name
        self.model_router = model_router
        self.week_start = week_start
        _ContinuityFakeBaseLLM.instances.append(self)

    def generate_dict_from_prompts(self) -> dict:
        week_key = self.week_start.isoformat()
        return {
            week_key: [
                {
                    "day": n,
                    "posts": [
                        {"title": "Beach day", "caption": "sun", "upload_time": ""}
                    ],
                }
                for n in range(1, 8)
            ]
        }


class _NoopModelRouter:
    def __init__(self, **kwargs):
        self.last_model: tuple[str, str] | None = None

    def initialize_model_classifiers(self, **kwargs):
        pass


@pytest.mark.asyncio
async def test_weeks_n_continuity_second_weeks_prompt_sees_first_weeks_recap(
    profile, store, monkeypatch
):
    """
    Two real `run_plan` calls, week 1 then week 2, through the real
    `PlanningManager`/`build_previous_storyline` — only the LLM boundary
    (`ModelRouter`/`BaseLLM`/`api_keys`) is faked, unlike `_fake_planning_manager`
    above which replaces `PlanningManager` itself and would bypass
    `build_previous_storyline` entirely, proving nothing about continuity.
    """
    _ContinuityFakeBaseLLM.instances = []
    monkeypatch.setattr(planning_manager_module, "ModelRouter", _NoopModelRouter)
    monkeypatch.setattr(planning_manager_module, "BaseLLM", _ContinuityFakeBaseLLM)
    monkeypatch.setattr(
        planning_manager_module.api_keys, "extract_openrouter_keys", lambda: ["key"]
    )
    monkeypatch.setattr(
        planning_manager_module.api_keys, "extract_deepseek_key", lambda: "key"
    )

    week1 = WEEK
    week2 = (date.fromisoformat(WEEK) + timedelta(days=7)).isoformat()

    await tasks.run_plan(
        _plan_job(profile, week=week1),
        store,
        FakeQueue(),
        use_initial_conditions=False,
        repository=repository_for(profile),
        run_id="run1",
    )
    await tasks.run_plan(
        _plan_job(profile, week=week2),
        store,
        FakeQueue(),
        use_initial_conditions=False,
        repository=repository_for(profile),
        run_id="run1",
    )

    week2_llm = next(
        inst
        for inst in _ContinuityFakeBaseLLM.instances
        if inst.platform_name is Platform.META and inst.week_start.isoformat() == week2
    )
    assert f"## Last week ({week1})" in week2_llm.previous_storyline
    assert "Beach day" in week2_llm.previous_storyline


# ---------------- job_events recording ----------------


def _events(store, job_type: JobType | None = None) -> list[dict]:
    events = store.events_for_run("run1")
    if job_type is None:
        return events
    return [e for e in events if e["type"] == job_type.value]


@pytest.mark.asyncio
async def test_run_plan_records_a_plan_done_event_with_outcome_detail(
    profile, store, monkeypatch
):
    _fake_planning_manager(monkeypatch, profile, [])
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    events = _events(store, JobType.PLAN)
    assert [e["kind"] for e in events] == ["plan_done"]
    assert events[0]["detail"] == {
        "attempt": 1,
        "max_attempts": 5,
        "model": "openrouter/fake-model",
        "used_fallback": False,
        "pinned_corrections": 0,
    }


@pytest.mark.asyncio
async def test_run_plan_records_a_plan_reused_event_on_resume(
    profile, store, monkeypatch
):
    _fake_planning_manager(monkeypatch, profile, [])
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run2",
    )

    assert [e["kind"] for e in store.events_for_run("run2")] == ["plan_reused"]


@pytest.mark.asyncio
async def test_run_plan_records_a_plan_failed_event_with_invalid_attempts(
    profile, store, monkeypatch
):
    class FailingPlanningManager:
        def __init__(self, **kwargs):
            pass

        def plan(self):
            raise planning_manager_module.PlanningFailedError(
                "not JSON", ["not JSON", "still not JSON"]
            )

    monkeypatch.setattr(tasks, "PlanningManager", FailingPlanningManager)

    with pytest.raises(ValueError):
        await tasks.run_plan(
            _plan_job(profile),
            store,
            FakeQueue(),
            use_initial_conditions=True,
            repository=repository_for(profile),
            run_id="run1",
        )

    events = _events(store, JobType.PLAN)
    assert [e["kind"] for e in events] == ["plan_failed"]
    assert events[0]["detail"]["invalid_attempts"] == ["not JSON", "still not JSON"]
    assert "not JSON" in events[0]["detail"]["error"]


@pytest.mark.asyncio
async def test_a_mid_chain_plan_failure_records_week_not_enqueued(
    profile, store, monkeypatch
):
    class FailingPlanningManager:
        def __init__(self, **kwargs):
            pass

        def plan(self):
            raise ValueError("every attempt was invalid")

    monkeypatch.setattr(tasks, "PlanningManager", FailingPlanningManager)
    job = Job(
        id=tasks.plan_job_id(profile, Platform.META, WEEK),
        payload=tasks.ProfileJob(
            profile=profile, platform=Platform.META, week=WEEK, remaining_weeks=2
        ),
    )

    with pytest.raises(ValueError):
        await tasks.run_plan(
            job,
            store,
            FakeQueue(),
            use_initial_conditions=True,
            repository=repository_for(profile),
            run_id="run1",
        )

    events = _events(store, JobType.PLAN)
    kinds = [e["kind"] for e in events]
    assert "plan_failed" in kinds
    assert "week_not_enqueued" in kinds
    not_enqueued = next(e for e in events if e["kind"] == "week_not_enqueued")
    next_week = (date.fromisoformat(WEEK) + timedelta(days=7)).isoformat()
    assert not_enqueued["detail"]["next_week"] == next_week


@pytest.mark.asyncio
async def test_a_replan_records_image_stale_removed_events(profile, store, monkeypatch):
    monkeypatch.setattr(
        tasks, "PlanningManager", _planning_manager_writing(profile, PLANNING_DAYS)
    )
    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )
    day_1 = tasks._publications_dir(profile, Platform.META) / WEEK / "day_1"
    (day_1 / "beach-day_0.jpeg").write_bytes(b"previously generated")
    (day_1 / "beach-day_1.jpeg").write_bytes(b"previously generated")

    renamed_days = [
        {
            "day": 1,
            "posts": [
                {
                    "title": "Sunset",
                    "caption": "sun",
                    "upload_time": "2026-09-01T10:00:00Z",
                    "images": [
                        {"image_description": "a beach"},
                        {"image_description": "a wave"},
                    ],
                }
            ],
        },
        PLANNING_DAYS[1],
    ]
    _force_replan(profile)
    monkeypatch.setattr(
        tasks, "PlanningManager", _planning_manager_writing(profile, renamed_days)
    )

    await tasks.run_plan(
        _plan_job(profile),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run2",
    )

    events = [
        e for e in store.events_for_run("run2") if e["kind"] == "image_stale_removed"
    ]
    assert len(events) == 2


@pytest.mark.asyncio
async def test_run_generate_image_records_an_image_generated_event(
    profile, store, monkeypatch
):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)
    backend = FakeBackend()

    await tasks.run_generate_image(image_jobs[0], store, queue, backend, "run1")

    events = _events(store, JobType.GENERATE_IMAGE)
    assert [e["kind"] for e in events] == ["image_generated"]


@pytest.mark.asyncio
async def test_run_generate_image_records_an_image_reused_event_for_an_existing_file(
    profile, store, monkeypatch
):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)
    job = image_jobs[0]
    job.payload.output_path.parent.mkdir(parents=True, exist_ok=True)
    job.payload.output_path.write_bytes(b"already there")

    await tasks.run_generate_image(job, store, queue, FakeBackend(), "run1")

    events = _events(store, JobType.GENERATE_IMAGE)
    assert [e["kind"] for e in events] == ["image_reused"]


@pytest.mark.asyncio
async def test_run_generate_image_records_an_image_failed_event(
    profile, store, monkeypatch
):
    queue = FakeQueue()
    image_jobs = await _plan_and_get_image_jobs(profile, store, queue, monkeypatch)

    with pytest.raises(RuntimeError):
        await tasks.run_generate_image(
            image_jobs[0], store, queue, FakeBackend(fail=True), "run1"
        )

    events = _events(store, JobType.GENERATE_IMAGE)
    assert [e["kind"] for e in events] == ["image_failed"]
    assert "comfy exploded" in events[0]["detail"]["error"]


@pytest.mark.asyncio
async def test_run_schedule_records_a_schedule_done_event(profile, store, monkeypatch):
    class FakeScheduler:
        def __init__(self, **kwargs):
            pass

        async def upload(self) -> None:
            pass

    monkeypatch.setattr(tasks, "PostingScheduler", FakeScheduler)
    job_id = tasks.schedule_job_id(profile, Platform.META, WEEK)
    store.create(job_id, JobType.SCHEDULE, profile.name, Platform.META)
    job = Job(
        id=job_id,
        payload=tasks.ProfileJob(profile=profile, platform=Platform.META, week=WEEK),
    )

    await tasks.run_schedule(job, store, publisher="publisher-cls", run_id="run1")

    events = _events(store, JobType.SCHEDULE)
    assert [e["kind"] for e in events] == ["schedule_done"]


@pytest.mark.asyncio
async def test_run_schedule_records_a_schedule_failed_event(
    profile, store, monkeypatch
):
    class FailingScheduler:
        def __init__(self, **kwargs):
            pass

        async def upload(self) -> None:
            raise RuntimeError("fanvue is down")

    monkeypatch.setattr(tasks, "PostingScheduler", FailingScheduler)
    job_id = tasks.schedule_job_id(profile, Platform.META, WEEK)
    store.create(job_id, JobType.SCHEDULE, profile.name, Platform.META)
    job = Job(
        id=job_id,
        payload=tasks.ProfileJob(profile=profile, platform=Platform.META, week=WEEK),
    )

    with pytest.raises(RuntimeError):
        await tasks.run_schedule(job, store, publisher="publisher-cls", run_id="run1")

    events = _events(store, JobType.SCHEDULE)
    assert [e["kind"] for e in events] == ["schedule_failed"]
    assert "fanvue is down" in events[0]["detail"]["error"]


def test_parse_job_id_recovers_week_from_plan_and_schedule_ids(profile):
    plan_id = tasks.plan_job_id(profile, Platform.META, WEEK)
    schedule_id = tasks.schedule_job_id(profile, Platform.META, WEEK)

    assert tasks.parse_job_id(plan_id) == tasks.ParsedJobId(
        type="plan", profile=profile.name, platform="meta", week=WEEK
    )
    assert tasks.parse_job_id(schedule_id) == tasks.ParsedJobId(
        type="schedule", profile=profile.name, platform="meta", week=WEEK
    )


def test_parse_job_id_recovers_week_from_a_generate_image_id(profile):
    output_path = (
        tasks._publications_dir(profile, Platform.META)
        / WEEK
        / "day_1"
        / "beach-day_0.jpeg"
    )
    image_id = tasks._image_job_id(profile, Platform.META, output_path)

    parsed = tasks.parse_job_id(image_id)

    assert parsed.type == "generate_image"
    assert parsed.profile == profile.name
    assert parsed.platform == "meta"
    assert parsed.week == WEEK


def test_parse_job_id_tolerates_a_legacy_schedule_id_with_no_week():
    """`schedule_job_id` grew its week dimension ahead of `--weeks N`; a real
    DB can still hold `schedule:{profile}:{platform}` rows from before that
    (observed against `.cache/jobs/migrated.db`). These must not crash
    `jobs status`."""
    parsed = tasks.parse_job_id("schedule:laura_vigne:fanvue")

    assert parsed.type == "schedule"
    assert parsed.profile == "laura_vigne"
    assert parsed.platform == "fanvue"
    assert parsed.week == "unknown"
