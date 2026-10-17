import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.story import Arc
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import (
    make_chapter,
    repository_for,
    write_arc,
    write_chapter,
    write_persona,
)
from ai_content_pipeline.generation.publications_generator import ImageSpec
from ai_content_pipeline.jobs import tasks
from ai_content_pipeline.jobs.queue import Job
from ai_content_pipeline.jobs.store import JobStatus, JobType
from ai_content_pipeline.llm.utils.utils import planning_week_start
from ai_content_pipeline.planning import planning_manager as planning_manager_module
from ai_content_pipeline.planning.planning_manager import PlanOutcome
from ai_content_pipeline.planning.story_manager import ArcOutcome, ChapterOutcome

# The target week these tests plan for: always several weeks ahead of
# whatever day the suite actually runs on, so a `plan` job already `done`
# is never accidentally "frozen" (see the dedicated frozen-week tests below,
# which use a deliberately past week instead).
WEEK = (planning_week_start(date.today()) + timedelta(weeks=10)).isoformat()

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


@pytest.fixture(autouse=True)
def _chapter_for_week(profile: Profile):
    """
    `run_plan`'s `build_previous_storyline` requires a chapter covering the
    target week, and `PlanningManager._ensure_story` (used by the real
    `PlanningManager`, which a couple of tests below exercise directly
    rather than through `_fake_planning_manager`) checks for an arc too
    before it would try to generate one over the network. One 12-week arc
    and one 4-week chapter from `WEEK` cover every week any test in this
    file plans for (`WEEK`, `WEEK + 7d`, `WEEK + 14d`).
    """
    write_arc(profile, WEEK, weeks=12)
    write_chapter(profile, WEEK, weeks=4)


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

    next_week = (date.fromisoformat(WEEK) + timedelta(days=7)).isoformat()
    await tasks.run_plan(
        _plan_job(profile, week=next_week),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_run_plan_replans_when_the_chapter_slice_for_this_week_changed(
    profile, store, monkeypatch
):
    """
    run_plan hashes exactly what the prompt gets, which now includes this
    week's chapter slice (`build_previous_storyline`). Editing the chapter
    must invalidate the resume hash for the week whose slice changed.
    """
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
    assert len(calls) == 1

    # Edit the chapter's situation for this same week.
    write_chapter(profile, WEEK, weeks=4, situation="A completely different thing")

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
async def test_frozen_week_is_not_replanned_even_if_its_hash_changed(
    profile, store, monkeypatch
):
    """
    A `plan` job already `done` whose week's Monday has already arrived
    must never be re-planned, even though something that would normally
    trigger a replan (the chapter slice) changed.
    """
    past_week = (planning_week_start(date.today()) - timedelta(weeks=2)).isoformat()
    write_chapter(profile, past_week, weeks=1, situation="original situation")
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    await tasks.run_plan(
        _plan_job(profile, week=past_week),
        store,
        FakeQueue(),
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )
    assert len(calls) == 1

    write_chapter(profile, past_week, weeks=1, situation="a changed situation")
    queue = FakeQueue()
    await tasks.run_plan(
        _plan_job(profile, week=past_week),
        store,
        queue,
        use_initial_conditions=True,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(calls) == 1  # not re-planned, despite the changed chapter
    events = _events(store, JobType.PLAN)
    assert [e["kind"] for e in events] == ["plan_done", "plan_frozen"]


@pytest.mark.asyncio
async def test_unchanged_started_week_is_reused_not_frozen(profile, store, monkeypatch):
    """
    A started week whose inputs did not change is plain "reused": "frozen"
    only means a changed hash that was deliberately ignored.
    """
    past_week = (planning_week_start(date.today()) - timedelta(weeks=2)).isoformat()
    write_chapter(profile, past_week, weeks=1, situation="original situation")
    calls: list = []
    _fake_planning_manager(monkeypatch, profile, calls)
    for _ in range(2):
        await tasks.run_plan(
            _plan_job(profile, week=past_week),
            store,
            FakeQueue(),
            use_initial_conditions=True,
            repository=repository_for(profile),
            run_id="run1",
        )

    assert len(calls) == 1
    events = _events(store, JobType.PLAN)
    assert [e["kind"] for e in events] == ["plan_done", "plan_reused"]


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
async def test_two_weeks_of_the_same_chapter_each_see_their_own_slice_only(
    profile, store, monkeypatch
):
    """
    Two real `run_plan` calls, week 1 then week 2 of the autouse fixture's
    4-week chapter, through the real `PlanningManager`/`build_previous_storyline`
    — only the LLM boundary (`ModelRouter`/`BaseLLM`/`api_keys`) is faked,
    unlike `_fake_planning_manager` above which replaces `PlanningManager`
    itself and would bypass `build_previous_storyline` entirely, proving
    nothing about the chapter slice actually reaching the prompt.
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

    week1_llm = next(
        inst
        for inst in _ContinuityFakeBaseLLM.instances
        if inst.week_start.isoformat() == week1
    )
    week2_llm = next(
        inst
        for inst in _ContinuityFakeBaseLLM.instances
        if inst.week_start.isoformat() == week2
    )
    # Week 1 (days 1-7 of the chapter) sees only its own days...
    assert "(day 1)" in week1_llm.previous_storyline
    assert "(day 8)" not in week1_llm.previous_storyline
    # ...and week 2 (days 8-14) sees only its own, never week 1's.
    assert "(day 8)" in week2_llm.previous_storyline
    assert "(day 1)" not in week2_llm.previous_storyline


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


def test_parse_job_id_recovers_week_from_a_story_id(profile):
    story_id = tasks.story_job_id(profile, WEEK)

    parsed = tasks.parse_job_id(story_id)

    assert parsed == tasks.ParsedJobId(
        type="story", profile=profile.name, platform="", week=WEEK
    )


# ---------------- run_story ----------------


def _fake_arc_outcome(profile: Profile, start_week: str) -> ArcOutcome:
    return ArcOutcome(
        profile=profile.name,
        start_week=start_week,
        attempt=1,
        max_attempts=5,
        model="openrouter/fake-model",
        used_fallback=False,
        invalid_attempts=[],
    )


def _fake_chapter_outcome(profile: Profile, start_week: str) -> ChapterOutcome:
    return ChapterOutcome(
        profile=profile.name,
        start_week=start_week,
        attempt=1,
        max_attempts=5,
        model="openrouter/fake-model",
        used_fallback=False,
        invalid_attempts=[],
    )


def _story_job(profile: Profile, week: str = WEEK, remaining_weeks: int = 0) -> Job:
    return Job(
        id=tasks.story_job_id(profile, week),
        payload=tasks.StoryJob(
            profile=profile, week=week, remaining_weeks=remaining_weeks
        ),
    )


def _fake_arc(start_week: str) -> Arc:
    return Arc(
        start_week=start_week,
        weeks=12,
        title="t",
        premise="p",
        goal="g",
        conflict="c",
        starting_point="s",
        ending_point="e",
        summary="sum",
    )


class _GeneratingStoryManager:
    """Both the arc and chapter are "missing" and get generated."""

    instances: list["_GeneratingStoryManager"] = []

    def __init__(self, profile, repository, refresh_model_cache=False):
        self.profile = profile
        self.repository = repository
        _GeneratingStoryManager.instances.append(self)

    def ensure_arc(self, week, force=False):
        arc = _fake_arc(week)
        return arc, True, _fake_arc_outcome(self.profile, week)

    def ensure_chapter(self, arc, week, force=False):
        chapter = make_chapter(week, weeks=4, arc_start_week=arc.start_week)
        return chapter, True, _fake_chapter_outcome(self.profile, week)


class _ReusingStoryManager:
    """Both the arc and chapter already exist and are simply reused."""

    def __init__(self, profile, repository, refresh_model_cache=False):
        self.profile = profile
        self.repository = repository

    def ensure_arc(self, week, force=False):
        return _fake_arc(week), False, None

    def ensure_chapter(self, arc, week, force=False):
        return make_chapter(week, weeks=4, arc_start_week=arc.start_week), False, None


class _FailingArcStoryManager:
    def __init__(self, profile, repository, refresh_model_cache=False):
        pass

    def ensure_arc(self, week, force=False):
        raise ValueError("arc generation blew up")

    def ensure_chapter(self, arc, week, force=False):
        raise AssertionError("must not be reached if the arc failed")


@pytest.mark.asyncio
async def test_run_story_generates_and_enqueues_plan_jobs_for_every_platform(
    profile, store, monkeypatch
):
    monkeypatch.setattr(tasks, "StoryManager", _GeneratingStoryManager)
    queue = FakeQueue()

    await tasks.run_story(
        _story_job(profile),
        store,
        queue,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert sorted(queue.ids(JobType.PLAN)) == sorted(
        tasks.plan_job_id(profile, platform, WEEK) for platform in Platform
    )
    events = _events(store, JobType.STORY)
    assert [e["kind"] for e in events] == ["arc_done", "chapter_done"]


@pytest.mark.asyncio
async def test_run_story_reuses_an_existing_arc_and_chapter(
    profile, store, monkeypatch
):
    monkeypatch.setattr(tasks, "StoryManager", _ReusingStoryManager)
    queue = FakeQueue()

    await tasks.run_story(
        _story_job(profile),
        store,
        queue,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert len(queue.ids(JobType.PLAN)) == len(list(Platform))
    events = _events(store, JobType.STORY)
    assert [e["kind"] for e in events] == ["arc_reused", "chapter_reused"]


@pytest.mark.asyncio
async def test_run_story_enqueues_the_next_week_when_weeks_remain(
    profile, store, monkeypatch
):
    monkeypatch.setattr(tasks, "StoryManager", _GeneratingStoryManager)
    queue = FakeQueue()

    await tasks.run_story(
        _story_job(profile, remaining_weeks=2),
        store,
        queue,
        repository=repository_for(profile),
        run_id="run1",
    )

    next_week = (date.fromisoformat(WEEK) + timedelta(days=7)).isoformat()
    assert queue.ids(JobType.STORY) == [tasks.story_job_id(profile, next_week)]
    enqueued_payload = [
        j.payload for t, j in queue.enqueued if t == JobType.STORY.value
    ][0]
    assert enqueued_payload.week == next_week
    assert enqueued_payload.remaining_weeks == 1


@pytest.mark.asyncio
async def test_run_story_does_not_enqueue_a_next_week_when_none_remain(
    profile, store, monkeypatch
):
    monkeypatch.setattr(tasks, "StoryManager", _GeneratingStoryManager)
    queue = FakeQueue()

    await tasks.run_story(
        _story_job(profile),  # remaining_weeks defaults to 0
        store,
        queue,
        repository=repository_for(profile),
        run_id="run1",
    )

    assert queue.ids(JobType.STORY) == []


@pytest.mark.asyncio
async def test_a_failed_story_enqueues_no_plan_jobs_and_no_next_week(
    profile, store, monkeypatch
):
    """
    If ensuring the arc (or chapter) fails, nothing below it runs for this
    week: no `plan` jobs for any platform, and no next week's `story` job —
    the same "a failed step blocks what depends on it" rule `--weeks N`
    always had, now enforced at the story level instead of at `plan`.
    """
    monkeypatch.setattr(tasks, "StoryManager", _FailingArcStoryManager)
    queue = FakeQueue()

    with pytest.raises(ValueError, match="arc generation blew up"):
        await tasks.run_story(
            _story_job(profile, remaining_weeks=2),
            store,
            queue,
            repository=repository_for(profile),
            run_id="run1",
        )

    assert queue.ids(JobType.PLAN) == []
    assert queue.ids(JobType.STORY) == []
    events = _events(store, JobType.STORY)
    kinds = [e["kind"] for e in events]
    assert "story_failed" in kinds
    assert "week_not_enqueued" in kinds
    not_enqueued = next(e for e in events if e["kind"] == "week_not_enqueued")
    next_week = (date.fromisoformat(WEEK) + timedelta(days=7)).isoformat()
    assert not_enqueued["detail"]["next_week"] == next_week


@pytest.mark.asyncio
async def test_run_story_job_status_is_done_after_a_successful_run(
    profile, store, monkeypatch
):
    monkeypatch.setattr(tasks, "StoryManager", _GeneratingStoryManager)

    await tasks.run_story(
        _story_job(profile),
        store,
        FakeQueue(),
        repository=repository_for(profile),
        run_id="run1",
    )

    assert store.status(tasks.story_job_id(profile, WEEK)) is JobStatus.DONE
