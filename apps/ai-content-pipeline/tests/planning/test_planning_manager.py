import json
from datetime import date
from pathlib import Path

import pytest

from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.story import Arc
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import repository_for, write_arc, write_chapter, write_persona
from ai_content_pipeline.planning import planning_manager as planning_manager_module
from ai_content_pipeline.planning import story_manager as story_manager_module
from ai_content_pipeline.planning.planning_manager import (
    PlanningFailedError,
    PlanningManager,
)

# A full week, as the planning contract requires, with the dates bunched onto
# two days the way real models sometimes reply.
PLANNING = {
    "week_1": [
        {
            "day": n,
            "posts": [
                {
                    "caption": f"hi {n}",
                    "upload_time": f"2026-10-1{2 if n < 5 else 3}T18:00:00Z",
                }
            ],
        }
        for n in range(1, 8)
    ]
}

# A fixed Monday so assertions never depend on today's real date.
TARGET_WEEK = date(2026, 10, 12)
TARGET_WEEK_KEY = "2026-10-12"


class FakeModelRouter:
    # Which (provider_id, identifier) pairs were excluded, across every
    # FakeModelRouter instance in a test — assertions read this directly
    # rather than threading an instance through.
    excluded: list[tuple[str, str]] = []
    # How many times `use_fallback_only()` was called, across instances.
    fallback_only_calls: int = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.last_model: tuple[str, str] | None = ("openrouter", "some-model")

    def initialize_model_classifiers(self, **kwargs):
        pass

    def exclude_model(self, provider_id: str, identifier: str) -> None:
        FakeModelRouter.excluded.append((provider_id, identifier))

    def use_fallback_only(self) -> None:
        FakeModelRouter.fallback_only_calls += 1


class FakeBaseLLM:
    instances: list["FakeBaseLLM"] = []
    reply: dict = PLANNING
    # Number of leading calls to generate_dict_from_prompts() that raise
    # ValueError before (eventually) returning `reply`, for the retry tests.
    fail_times: int = 0
    call_count: int = 0

    def __init__(
        self, prompts, previous_storyline, platform_name, model_router, week_start
    ):
        self.prompts = prompts
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name
        self.model_router = model_router
        self.week_start = week_start
        FakeBaseLLM.instances.append(self)

    def generate_dict_from_prompts(self) -> dict:
        FakeBaseLLM.call_count += 1
        if FakeBaseLLM.call_count <= FakeBaseLLM.fail_times:
            raise ValueError("not JSON")
        return FakeBaseLLM.reply

    def generate_simple_text(self, prompt: str) -> str:
        return "a short summary"


class _StoryGenerationTripwire:
    """
    `StoryManager.plan_arc`/`plan_chapter` only build a `ModelRouter` (and
    only then construct a `BaseLLM`) when something is actually missing —
    every test in this file has both the arc and the chapter seeded by the
    `_story_for_target_week` autouse fixture below, so any accidental real
    generation attempt must fail loudly here instead of silently reaching
    the network. Tests that specifically exercise self-healing swap this
    out for a real fake that answers.
    """

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "story generation must not run when an arc/chapter already exist"
        )


@pytest.fixture(autouse=True)
def _fake_llm_boundary(monkeypatch):
    """
    Fakes the 3 external boundaries `plan()` talks to (ModelRouter, api_keys,
    BaseLLM) so these tests exercise only the repository wiring, not the LLM
    stack. Also tripwires `StoryManager`'s own `ModelRouter`/`BaseLLM` (see
    `_StoryGenerationTripwire`) so `PlanningManager._ensure_story` calling
    through to real story generation fails the test instead of the network.
    """
    FakeBaseLLM.instances = []
    FakeBaseLLM.reply = PLANNING
    FakeBaseLLM.fail_times = 0
    FakeBaseLLM.call_count = 0
    FakeModelRouter.excluded = []
    FakeModelRouter.fallback_only_calls = 0
    monkeypatch.setattr(planning_manager_module, "ModelRouter", FakeModelRouter)
    monkeypatch.setattr(planning_manager_module, "BaseLLM", FakeBaseLLM)
    monkeypatch.setattr(
        planning_manager_module.api_keys, "extract_openrouter_keys", lambda: ["key"]
    )
    monkeypatch.setattr(
        planning_manager_module.api_keys, "extract_deepseek_key", lambda: "key"
    )
    monkeypatch.setattr(story_manager_module, "ModelRouter", _StoryGenerationTripwire)
    monkeypatch.setattr(story_manager_module, "BaseLLM", _StoryGenerationTripwire)


@pytest.fixture(autouse=True)
def _story_for_target_week(profile: Profile):
    """
    `build_previous_storyline` requires a chapter covering the target week
    (see isolation tests below for why `plan` reads a chapter rather than
    the arc or the other platform's notes), and `PlanningManager._ensure_story`
    now ensures the arc too before building it. Every test in this file
    plans for `TARGET_WEEK_KEY` by default, so seed both up front; tests
    that care about their exact content overwrite them, and the dedicated
    self-healing tests below delete them again on purpose.
    """
    write_arc(profile, TARGET_WEEK_KEY, weeks=12)
    write_chapter(profile, TARGET_WEEK_KEY)


def _plan(
    profile: Profile,
    platform: Platform,
    use_initial_conditions=True,
    target_week: date = TARGET_WEEK,
) -> list:
    return PlanningManager(
        template_profiles=[profile],
        platform_name=platform,
        use_initial_conditions=use_initial_conditions,
        repository=repository_for(profile),
        target_week=target_week,
    ).plan()


def _initial_conditions(profile: Profile) -> Path:
    return profile.platform_info[Platform.META].inputs_path / "initial_conditions.md"


def _this_week_section(platform: Platform) -> str:
    """The `## This week` text `write_chapter`'s default chapter produces
    for `platform`, for `TARGET_WEEK_KEY` — matches what every plan test
    below gets from the autouse `_story_for_target_week` fixture."""
    angle = "Meta angle" if platform is Platform.META else "Fanvue angle"
    lines = [
        f"- 2026-10-{12 + i}: Situation: Something happens (day {i + 1}) | "
        f"Angle (direction only): {angle} (day {i + 1})"
        for i in range(7)
    ]
    return "## This week\n" + "\n".join(lines)


def test_plan_feeds_the_shared_persona_and_the_platform_notes_to_the_llm(
    profile: Profile,
):
    write_persona(profile, "28, grew up in Porto")
    _initial_conditions(profile).write_text("keep it SFW", encoding="utf-8")

    _plan(profile, Platform.META)

    llm = FakeBaseLLM.instances[0]
    assert llm.previous_storyline == (
        "## Who she is\n28, grew up in Porto\n\n## Platform notes\nkeep it SFW"
        f"\n\n{_this_week_section(Platform.META)}"
    )
    assert [p.cache_key for p in llm.prompts] == ["week"]
    assert llm.week_start == TARGET_WEEK


def test_no_initial_conditions_drops_the_platform_notes_but_keeps_the_persona(
    profile: Profile,
):
    write_persona(profile, "28, grew up in Porto")
    _initial_conditions(profile).write_text("keep it SFW", encoding="utf-8")

    _plan(profile, Platform.META, use_initial_conditions=False)

    storyline = FakeBaseLLM.instances[0].previous_storyline
    assert storyline == (
        f"## Who she is\n28, grew up in Porto\n\n{_this_week_section(Platform.META)}"
    )


def test_sections_the_profile_has_not_got_yet_are_left_out(profile: Profile):
    _initial_conditions(profile).write_text("keep it SFW", encoding="utf-8")

    _plan(profile, Platform.META)

    storyline = FakeBaseLLM.instances[0].previous_storyline
    assert storyline == (
        f"## Platform notes\nkeep it SFW\n\n{_this_week_section(Platform.META)}"
    )


def test_this_week_section_is_the_platforms_slice_of_the_chapter(profile: Profile):
    write_chapter(
        profile,
        TARGET_WEEK_KEY,
        situation="A trip to Lisbon",
        meta_angle="Posts a sunny beach photo",
        fanvue_angle="Shares the private aftermath",
    )

    _plan(profile, Platform.META, use_initial_conditions=False)

    storyline = FakeBaseLLM.instances[0].previous_storyline
    assert "## This week" in storyline
    assert (
        "2026-10-12: Situation: A trip to Lisbon (day 1) | "
        "Angle (direction only): Posts a sunny beach photo (day 1)" in (storyline)
    )
    assert "2026-10-18" in storyline  # day 7, the last day of the week


def test_build_previous_storyline_raises_a_clear_error_when_no_chapter_covers_the_week(
    profile: Profile,
):
    """
    Direct unit test of `build_previous_storyline` itself (not through
    `PlanningManager.plan()`, which now self-heals a missing chapter — see
    `test_plan_self_heals_a_missing_arc_and_chapter_then_plans` below). This
    is still the error a caller gets if it reads a chapter for a week
    `_ensure_story` never covered (e.g. `jobs/tasks.py:run_plan`'s hash
    computation, if the DAG's own guarantee were ever violated).
    """
    repo = repository_for(profile)
    platform_profile = repo.get_platform_profile(profile, Platform.META)

    with pytest.raises(ValueError, match="No chapter covers week"):
        planning_manager_module.build_previous_storyline(
            repo, profile, Platform.META, platform_profile, True, "2099-01-04"
        )


def test_plan_self_heals_a_missing_arc_and_chapter_then_plans(
    profile: Profile, monkeypatch
):
    """
    Standalone callers (`meta plan`, `fanvue plan`, `all run_all`) have no
    DAG "story" step guaranteeing an arc/chapter exists. `PlanningManager`
    must generate both itself — once — before it can build the storyline
    and plan.
    """
    repo = repository_for(profile)
    for path in (
        profile.platform_info[Platform.META].inputs_path.parents[1] / "story"
    ).glob("**/*.json"):
        path.unlink()
    assert repo.get_arc_covering(profile, TARGET_WEEK_KEY) is None
    assert repo.get_chapter_covering(profile, TARGET_WEEK_KEY) is None

    class RealStoryFakeModelRouter(FakeModelRouter):
        pass

    class RealStoryFakeBaseLLM:
        """
        Dispatches on `prompts[0].cache_key` rather than call order, since
        `plan_chapter` now makes several calls (one outline, one per week)
        instead of one: "arc", "chapter_outline", or "chapter_week_{i}".
        """

        instances: list["RealStoryFakeBaseLLM"] = []

        def __init__(
            self, prompts, previous_storyline, platform_name, model_router, week_start
        ):
            self.week_start = week_start
            self.model_router = model_router
            self.cache_key = prompts[0].cache_key
            RealStoryFakeBaseLLM.instances.append(self)

        def generate_dict_from_prompts(self) -> dict:
            from datetime import timedelta

            if self.cache_key == "arc":
                return {
                    "title": "t",
                    "premise": "p",
                    "goal": "g",
                    "conflict": "c",
                    "starting_point": "s",
                    "ending_point": "e",
                    "summary": "sum",
                }
            if self.cache_key == "chapter_outline":
                return {
                    "title": "chapter",
                    "summary": "chapter summary",
                    # Default StoryConfig.chapter_weeks is 4.
                    "week_summaries": ["w0", "w1", "w2", "w3"],
                }
            week_index = int(self.cache_key.rsplit("_", 1)[1])
            start = self.week_start
            return {
                "days": [
                    {
                        "date": (start + timedelta(days=i)).isoformat(),
                        "situation": f"s{week_index * 7 + i}",
                        "angles": {
                            "meta": f"m{week_index * 7 + i}",
                            "fanvue": f"f{week_index * 7 + i}",
                        },
                    }
                    for i in range(7)
                ],
            }

    RealStoryFakeBaseLLM.instances = []
    monkeypatch.setattr(story_manager_module, "ModelRouter", RealStoryFakeModelRouter)
    monkeypatch.setattr(story_manager_module, "BaseLLM", RealStoryFakeBaseLLM)

    _plan(profile, Platform.META)

    # One arc call, one chapter outline call, one call per week (4).
    assert len(RealStoryFakeBaseLLM.instances) == 6
    assert repo.get_arc_covering(profile, TARGET_WEEK_KEY) is not None
    assert repo.get_chapter_covering(profile, TARGET_WEEK_KEY) is not None
    # The plan itself still went through, using the freshly generated chapter.
    saved = repo.get_week_plan(profile, Platform.META)
    assert saved.week == TARGET_WEEK_KEY


def test_plan_makes_no_story_generation_calls_when_arc_and_chapter_already_exist(
    profile: Profile,
):
    """
    The autouse fixtures already seed both the arc and the chapter, and
    tripwire `StoryManager`'s `ModelRouter`/`BaseLLM`
    (`_StoryGenerationTripwire`) so this would fail loudly if `plan()` ever
    reached real story generation. A plain, successful `_plan()` call is
    the proof that it didn't.
    """
    _plan(profile, Platform.META)  # must not raise AssertionError


# --- isolation: Meta never sees the arc, Fanvue's angle, or Fanvue's notes --


def test_meta_storyline_never_contains_the_arc_fanvue_angle_or_fanvue_notes(
    profile: Profile,
):
    write_persona(profile, "persona text")
    _initial_conditions(profile).write_text("Meta: keep it SFW", encoding="utf-8")
    fanvue_notes = profile.platform_info[Platform.FANVUE].inputs_path / (
        "initial_conditions.md"
    )
    fanvue_notes.write_text("FANVUE_MARKER: explicit tone notes", encoding="utf-8")
    repository_for(profile).save_arc(
        profile,
        Arc(
            start_week=TARGET_WEEK_KEY,
            weeks=12,
            title="ARC_MARKER season",
            premise="ARC_MARKER premise",
            goal="goal",
            conflict="conflict",
            starting_point="start",
            ending_point="end",
            summary="ARC_MARKER summary",
        ),
    )
    write_chapter(
        profile,
        TARGET_WEEK_KEY,
        situation="A neutral situation",
        meta_angle="A safe-for-work angle",
        fanvue_angle="FANVUE_MARKER: an explicit angle",
    )

    _plan(profile, Platform.META)
    meta_storyline = FakeBaseLLM.instances[0].previous_storyline

    assert "ARC_MARKER" not in meta_storyline
    assert "FANVUE_MARKER" not in meta_storyline
    assert "A safe-for-work angle" in meta_storyline

    FakeBaseLLM.instances.clear()
    _plan(profile, Platform.FANVUE)
    fanvue_storyline = FakeBaseLLM.instances[0].previous_storyline

    # Fanvue legitimately gets its own angle and its own notes...
    assert "FANVUE_MARKER" in fanvue_storyline
    # ...but never the arc, which no platform ever reads directly.
    assert "ARC_MARKER" not in fanvue_storyline


def test_plan_saves_the_generated_week_plan(profile: Profile):
    _plan(profile, Platform.FANVUE)

    saved = repository_for(profile).get_week_plan(profile, Platform.FANVUE)
    expected = WeekPlan.from_planning_dict(PLANNING)
    expected.week = TARGET_WEEK_KEY
    expected.pin_to_week(TARGET_WEEK)
    assert saved == expected


def test_plan_publishes_one_day_per_calendar_day(profile: Profile):
    """Day N goes out on Monday + (N - 1), whatever date the model chose."""
    _plan(profile, Platform.FANVUE)

    saved = repository_for(profile).get_week_plan(profile, Platform.FANVUE)
    assert [day.posts[0].upload_time for day in saved.days] == [
        f"2026-10-{12 + n}T18:00:00Z" for n in range(7)
    ]


def test_plan_rejects_a_week_with_missing_days(profile: Profile):
    FakeBaseLLM.reply = {"week_1": PLANNING["week_1"][:6]}
    outputs = profile.platform_info[Platform.META].outputs_path

    with pytest.raises(ValueError, match="Expected days 1-7"):
        _plan(profile, Platform.META)

    assert list(outputs.iterdir()) == []  # nothing half-saved


def test_plan_overrides_the_llm_week_key_with_the_target_week(profile: Profile):
    """
    The prompt JSONs under resources*/ still say "week_1"; `plan` must use
    the target week it was asked for, whatever key the model replied with.
    """
    FakeBaseLLM.reply = PLANNING

    _plan(profile, Platform.META)

    saved = repository_for(profile).get_week_plan(profile, Platform.META)
    assert saved.week == TARGET_WEEK_KEY


def test_plan_rejects_an_llm_reply_that_is_not_a_week_plan(profile: Profile):
    FakeBaseLLM.reply = {"week_1": [{"posts": []}]}  # no "day"
    outputs = profile.platform_info[Platform.META].outputs_path

    with pytest.raises(ValueError):
        _plan(profile, Platform.META)

    assert list(outputs.iterdir()) == []  # nothing half-saved


def test_planning_never_writes_back_into_the_profile_inputs(profile: Profile):
    """
    Planning used to append its own summary to initial_conditions.md, which is
    what broke resume: the file it hashed changed on every run.
    """
    before = _initial_conditions(profile).read_text(encoding="utf-8")

    _plan(profile, Platform.META)

    assert _initial_conditions(profile).read_text(encoding="utf-8") == before


def test_saved_file_keeps_the_week_keyed_shape_consumers_read(profile: Profile):
    _plan(profile, Platform.META)

    outputs = profile.platform_info[Platform.META].outputs_path
    saved = json.loads((outputs / "h_planning.json").read_text("utf-8"))
    assert list(saved) == [TARGET_WEEK_KEY]
    assert saved[TARGET_WEEK_KEY][0] == {
        "day": 1,
        "posts": [
            {
                "title": "",
                "caption": "hi 1",
                "hashtags": "",
                "upload_time": "2026-10-12T18:00:00Z",
                "images": [],
            }
        ],
    }


def test_default_target_week_is_deterministic_from_today(monkeypatch, profile: Profile):
    """With no explicit `target_week`, `PlanningManager` computes it from
    `planning_week_start(date.today())`, not from anything already planned."""
    monkeypatch.setattr(
        planning_manager_module, "planning_week_start", lambda today: date(2030, 1, 7)
    )

    manager = PlanningManager(
        template_profiles=[profile],
        platform_name=Platform.META,
        use_initial_conditions=True,
        repository=repository_for(profile),
    )

    assert manager.target_week == date(2030, 1, 7)


def test_plan_retries_an_invalid_reply_and_saves_once_it_succeeds(profile: Profile):
    """One bad reply (e.g. not JSON) then a good one must still save, and
    must have actually re-run the full prompt chain (call_count == 2)."""
    FakeBaseLLM.fail_times = 1

    _plan(profile, Platform.FANVUE)

    assert FakeBaseLLM.call_count == 2
    saved = repository_for(profile).get_week_plan(profile, Platform.FANVUE)
    expected = WeekPlan.from_planning_dict(PLANNING)
    expected.week = TARGET_WEEK_KEY
    expected.pin_to_week(TARGET_WEEK)
    assert saved == expected


def test_plan_gives_up_after_max_attempts_and_saves_nothing(profile: Profile):
    FakeBaseLLM.fail_times = planning_manager_module.MAX_PLAN_ATTEMPTS
    outputs = profile.platform_info[Platform.FANVUE].outputs_path

    with pytest.raises(ValueError, match="not JSON"):
        _plan(profile, Platform.FANVUE)

    assert FakeBaseLLM.call_count == planning_manager_module.MAX_PLAN_ATTEMPTS
    assert list(outputs.iterdir()) == []  # nothing half-saved


def test_plan_excludes_the_model_that_produced_the_invalid_reply_after_a_failed_attempt(
    profile: Profile,
):
    """
    `ModelRouter` always tries candidates highest-ELO first, so without an
    exclusion every retry would hit the same model that just produced an
    invalid reply. `PlanningManager` must exclude it on the router instance
    used for this `plan()` call so the next attempt falls through to a
    different candidate.
    """
    FakeBaseLLM.fail_times = 1

    _plan(profile, Platform.FANVUE)

    assert FakeModelRouter.excluded == [("openrouter", "some-model")]


def test_plan_excludes_once_per_failed_attempt_when_every_attempt_is_invalid(
    profile: Profile,
):
    FakeBaseLLM.fail_times = planning_manager_module.MAX_PLAN_ATTEMPTS

    with pytest.raises(ValueError):
        _plan(profile, Platform.FANVUE)

    assert (
        FakeModelRouter.excluded
        == [("openrouter", "some-model")] * planning_manager_module.MAX_PLAN_ATTEMPTS
    )


def test_plan_excludes_nothing_when_the_first_attempt_succeeds(profile: Profile):
    _plan(profile, Platform.FANVUE)

    assert FakeModelRouter.excluded == []
    assert FakeModelRouter.fallback_only_calls == 0


def test_only_the_last_attempt_goes_to_the_paid_fallback(profile: Profile):
    FakeBaseLLM.fail_times = planning_manager_module.MAX_PLAN_ATTEMPTS - 1

    _plan(profile, Platform.FANVUE)

    assert FakeBaseLLM.call_count == planning_manager_module.MAX_PLAN_ATTEMPTS
    assert FakeModelRouter.fallback_only_calls == 1


def test_an_earlier_success_never_reaches_the_paid_fallback(profile: Profile):
    FakeBaseLLM.fail_times = planning_manager_module.MAX_PLAN_ATTEMPTS - 2

    _plan(profile, Platform.FANVUE)

    assert FakeModelRouter.fallback_only_calls == 0


# ---------------- PlanOutcome ----------------


def test_plan_returns_an_outcome_describing_a_first_try_success(profile: Profile):
    outcomes = _plan(profile, Platform.FANVUE)

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.profile == profile.name
    assert outcome.week == TARGET_WEEK_KEY
    assert outcome.attempt == 1
    assert outcome.max_attempts == planning_manager_module.MAX_PLAN_ATTEMPTS
    assert outcome.model == "openrouter/some-model"
    assert outcome.used_fallback is False
    assert outcome.invalid_attempts == []


def test_plan_outcome_counts_pin_to_weeks_corrections(profile: Profile):
    """`PLANNING`'s upload_times are bunched onto two days; day 1 already
    matches the target week's Monday, so `pin_to_week` corrects the other 6."""
    outcome = _plan(profile, Platform.FANVUE)[0]

    assert outcome.pinned_corrections == 6


def test_plan_outcome_records_every_invalid_attempts_error(profile: Profile):
    FakeBaseLLM.fail_times = 2

    outcome = _plan(profile, Platform.FANVUE)[0]

    assert outcome.attempt == 3
    assert outcome.invalid_attempts == ["not JSON", "not JSON"]


def test_plan_outcome_flags_the_last_attempt_as_using_the_fallback(profile: Profile):
    FakeBaseLLM.fail_times = planning_manager_module.MAX_PLAN_ATTEMPTS - 1

    outcome = _plan(profile, Platform.FANVUE)[0]

    assert outcome.used_fallback is True
    assert outcome.attempt == planning_manager_module.MAX_PLAN_ATTEMPTS


def test_plan_raises_a_planning_failed_error_carrying_every_attempts_error(
    profile: Profile,
):
    FakeBaseLLM.fail_times = planning_manager_module.MAX_PLAN_ATTEMPTS

    with pytest.raises(PlanningFailedError) as excinfo:
        _plan(profile, Platform.FANVUE)

    assert excinfo.value.invalid_attempts == (
        ["not JSON"] * planning_manager_module.MAX_PLAN_ATTEMPTS
    )
    # Still a plain ValueError to any caller that only checks that.
    assert isinstance(excinfo.value, ValueError)
