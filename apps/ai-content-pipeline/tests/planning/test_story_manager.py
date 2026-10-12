from datetime import date, timedelta

import pytest

from ai_content_pipeline.domain.story import Arc
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import (
    repository_for,
    write_arc,
    write_chapter,
    write_persona,
)
from ai_content_pipeline.planning import story_manager as story_manager_module
from ai_content_pipeline.planning.story_manager import (
    StoryGenerationFailedError,
    StoryManager,
)

ARC_REPLY = {
    "title": "A new season",
    "premise": "premise text",
    "goal": "goal text",
    "conflict": "conflict text",
    "starting_point": "start text",
    "ending_point": "end text",
    "summary": "summary text",
}


def _chapter_outline_reply(weeks: int = 1, title: str = "A chapter") -> dict:
    return {
        "title": title,
        "summary": "chapter summary",
        "week_summaries": [f"week {i} summary" for i in range(weeks)],
    }


def _chapter_week_reply(start_week: str, week_index: int) -> dict:
    """A valid `ChapterWeekDays`-shaped reply for week `week_index` (0-based)
    of a chapter starting `start_week`. Day content is deterministic and
    distinct per absolute day index (`week_index * 7 + i`), so tests can
    assert on it (e.g. continuity between weeks)."""
    week_start = date.fromisoformat(start_week) + timedelta(weeks=week_index)
    return {
        "days": [
            {
                "date": (week_start + timedelta(days=i)).isoformat(),
                "situation": f"situation {week_index * 7 + i}",
                "angles": {
                    "meta": f"meta {week_index * 7 + i}",
                    "fanvue": f"fanvue {week_index * 7 + i}",
                },
            }
            for i in range(7)
        ],
    }


def _set_chapter_replies(start_week: str, weeks: int = 1, **outline_kwargs) -> None:
    """Populates `FakeBaseLLM.replies` with a valid outline reply plus one
    valid week-days reply per week, matching `plan_chapter`'s call sequence
    (one outline call, then one call per week, in order)."""
    FakeBaseLLM.replies["chapter_outline"] = [
        _chapter_outline_reply(weeks, **outline_kwargs)
    ]
    for week_index in range(weeks):
        FakeBaseLLM.replies[f"chapter_week_{week_index}"] = [
            _chapter_week_reply(start_week, week_index)
        ]


class FakeModelRouter:
    excluded: list[tuple[str, str]] = []
    fallback_only_calls: int = 0

    def __init__(self, **kwargs):
        self.last_model: tuple[str, str] | None = ("openrouter", "some-model")

    def initialize_model_classifiers(self, **kwargs):
        pass

    def exclude_model(self, provider_id: str, identifier: str) -> None:
        FakeModelRouter.excluded.append((provider_id, identifier))

    def use_fallback_only(self) -> None:
        FakeModelRouter.fallback_only_calls += 1


class FakeBaseLLM:
    """
    Replies and failures are keyed by the first prompt's `cache_key`
    ("arc", "chapter_outline", or "chapter_week_{i}"), since `plan_chapter`
    now makes several distinct calls (one outline, one per week) instead of
    one, each needing its own reply shape and its own ability to fail then
    retry independently.

    `replies[key]` is a list: with more than one entry, each call for that
    key pops the front one until only one is left, which then repeats for
    any further call — lets a test script "first reply invalid, second
    reply valid" without needing to raise an exception.
    """

    instances: list["FakeBaseLLM"] = []
    replies: dict[str, list[dict]] = {}
    fail_times: dict[str, int] = {}
    call_count: dict[str, int] = {}

    def __init__(
        self, prompts, previous_storyline, platform_name, model_router, week_start
    ):
        self.prompts = prompts
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name
        self.model_router = model_router
        self.week_start = week_start
        self.cache_key = prompts[0].cache_key
        FakeBaseLLM.instances.append(self)

    def generate_dict_from_prompts(self) -> dict:
        key = self.cache_key
        FakeBaseLLM.call_count[key] = FakeBaseLLM.call_count.get(key, 0) + 1
        if FakeBaseLLM.call_count[key] <= FakeBaseLLM.fail_times.get(key, 0):
            raise ValueError("not JSON")
        queue = FakeBaseLLM.replies[key]
        return queue[0] if len(queue) == 1 else queue.pop(0)

    def generate_simple_text(self, prompt: str) -> str:
        return "summary"


@pytest.fixture(autouse=True)
def _fake_llm_boundary(monkeypatch):
    FakeBaseLLM.instances = []
    FakeBaseLLM.replies = {"arc": [ARC_REPLY]}
    FakeBaseLLM.fail_times = {}
    FakeBaseLLM.call_count = {}
    FakeModelRouter.excluded = []
    FakeModelRouter.fallback_only_calls = 0
    monkeypatch.setattr(story_manager_module, "ModelRouter", FakeModelRouter)
    monkeypatch.setattr(story_manager_module, "BaseLLM", FakeBaseLLM)
    monkeypatch.setattr(
        story_manager_module.api_keys, "extract_openrouter_keys", lambda: ["key"]
    )
    monkeypatch.setattr(
        story_manager_module.api_keys, "extract_deepseek_key", lambda: "key"
    )


def _manager(profile: Profile) -> StoryManager:
    return StoryManager(profile, repository_for(profile))


# ---------------- ensure_arc ----------------


def test_ensure_arc_reuses_an_existing_arc_without_calling_the_llm(profile: Profile):
    existing = write_arc(profile, "2026-10-05", weeks=12)

    arc, generated, outcome = _manager(profile).ensure_arc("2026-10-12")

    assert arc == existing
    assert generated is False
    assert outcome is None
    assert FakeBaseLLM.instances == []


def test_ensure_arc_generates_when_missing(profile: Profile):
    arc, generated, outcome = _manager(profile).ensure_arc("2026-10-05")

    assert generated is True
    assert outcome is not None
    assert outcome.attempt == 1
    assert arc.start_week == "2026-10-05"
    assert arc.weeks == 12  # default StoryConfig
    assert arc.title == "A new season"
    assert repository_for(profile).get_arc_covering(profile, "2026-10-05") == arc


def test_ensure_arc_uses_the_profiles_story_config(profile: Profile):
    story_dir = profile.platform_info[Platform.META].inputs_path.parents[1] / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "config.json").write_text('{"arc_weeks": 6, "chapter_weeks": 2}')

    arc, _, _ = _manager(profile).ensure_arc("2026-10-05")

    assert arc.weeks == 6


def test_ensure_arc_force_regenerates_even_when_one_already_covers_the_week(
    profile: Profile,
):
    write_arc(profile, "2026-10-05", weeks=12)

    arc, generated, outcome = _manager(profile).ensure_arc("2026-10-12", force=True)

    assert generated is True
    assert outcome is not None
    # A forced regeneration keeps the same slot (the existing arc's own
    # start_week), rather than treating the arc being replaced as "the
    # previous arc" and skipping past it.
    assert FakeBaseLLM.instances[0].week_start == date(2026, 10, 5)
    assert arc.start_week == "2026-10-05"


def test_ensure_arc_starts_a_new_arc_the_monday_after_the_previous_one_ends(
    profile: Profile,
):
    write_arc(profile, "2026-01-05", weeks=4)  # ends 2026-01-26

    arc, generated, _ = _manager(profile).ensure_arc("2026-02-02")

    assert generated is True
    assert arc.start_week == "2026-02-02"


def test_plan_arc_rejects_an_invalid_reply_and_retries(profile: Profile):
    FakeBaseLLM.fail_times["arc"] = 1

    arc, generated, outcome = _manager(profile).ensure_arc("2026-10-05")

    assert generated is True
    assert FakeBaseLLM.call_count["arc"] == 2
    assert outcome.attempt == 2
    assert outcome.invalid_attempts == ["not JSON"]
    assert FakeModelRouter.excluded == [("openrouter", "some-model")]


def test_plan_arc_gives_up_after_every_attempt_fails(profile: Profile):
    FakeBaseLLM.fail_times["arc"] = story_manager_module.MAX_ARC_ATTEMPTS

    with pytest.raises(StoryGenerationFailedError) as excinfo:
        _manager(profile).ensure_arc("2026-10-05")

    assert len(excinfo.value.invalid_attempts) == story_manager_module.MAX_ARC_ATTEMPTS
    assert FakeModelRouter.fallback_only_calls == 1
    # Nothing saved on total failure.
    assert repository_for(profile).get_arc_covering(profile, "2026-10-05") is None


def test_arc_context_includes_persona_every_platforms_notes_and_the_previous_arc(
    profile: Profile,
):
    write_persona(profile, "persona text")
    (
        profile.platform_info[Platform.META].inputs_path / "initial_conditions.md"
    ).write_text("meta notes", encoding="utf-8")
    (
        profile.platform_info[Platform.FANVUE].inputs_path / "initial_conditions.md"
    ).write_text("fanvue notes", encoding="utf-8")
    repository_for(profile).save_arc(
        profile,
        Arc(
            start_week="2026-01-05",
            weeks=4,
            title="t",
            premise="p",
            goal="g",
            conflict="c",
            starting_point="s",
            ending_point="e",
            summary="PREVIOUS_ARC_SUMMARY",
        ),
    )

    _manager(profile).ensure_arc("2026-02-02")

    storyline = FakeBaseLLM.instances[0].previous_storyline
    assert "persona text" in storyline
    assert "meta notes" in storyline
    assert "fanvue notes" in storyline
    assert "PREVIOUS_ARC_SUMMARY" in storyline


# ---------------- ensure_chapter ----------------


def test_ensure_chapter_reuses_an_existing_chapter_without_calling_the_llm(
    profile: Profile,
):
    arc = write_arc(profile, "2026-10-05", weeks=12)
    existing = write_chapter(
        profile, "2026-10-05", weeks=4, arc_start_week=arc.start_week
    )

    chapter, generated, outcome = _manager(profile).ensure_chapter(arc, "2026-10-12")

    # Same content; a pre-stamp chapter only gains its stamps.
    assert chapter.model_dump(exclude={"days": {"__all__": {"stamp"}}}) == (
        existing.model_dump(exclude={"days": {"__all__": {"stamp"}}})
    )
    assert all(day.stamp == day.current_stamp() for day in chapter.days)
    assert generated is False
    assert outcome is None
    assert FakeBaseLLM.instances == []


def test_ensure_chapter_generates_when_missing_using_config_boundaries(
    profile: Profile,
):
    arc = write_arc(profile, "2026-10-05", weeks=12)
    _set_chapter_replies("2026-10-05", weeks=4)

    chapter, generated, outcome = _manager(profile).ensure_chapter(arc, "2026-10-05")

    assert generated is True
    assert chapter.start_week == "2026-10-05"
    assert chapter.weeks == 4  # default StoryConfig.chapter_weeks
    assert chapter.arc_start_week == arc.start_week
    assert (
        repository_for(profile).get_chapter_covering(profile, "2026-10-05") == chapter
    )


def test_ensure_chapter_force_regenerates_even_when_one_already_covers_the_week(
    profile: Profile,
):
    arc = write_arc(profile, "2026-10-05", weeks=12)
    write_chapter(profile, "2026-10-05", weeks=4, arc_start_week=arc.start_week)
    _set_chapter_replies("2026-10-05", weeks=4)

    chapter, generated, outcome = _manager(profile).ensure_chapter(
        arc, "2026-10-12", force=True
    )

    assert generated is True
    assert outcome is not None


def test_chapter_context_includes_arc_persona_notes_and_previous_chapters(
    profile: Profile,
):
    arc = write_arc(profile, "2026-10-05", weeks=12)
    write_persona(profile, "persona text")
    (
        profile.platform_info[Platform.META].inputs_path / "initial_conditions.md"
    ).write_text("meta notes", encoding="utf-8")
    write_chapter(
        profile,
        "2026-10-05",
        weeks=4,
        arc_start_week=arc.start_week,
        situation="PREVIOUS_CHAPTER_SITUATION",
    )
    _set_chapter_replies("2026-11-02", weeks=4)

    _manager(profile).ensure_chapter(arc, "2026-11-02")

    # The first BaseLLM instance is the outline call; its storyline is the
    # same base chapter context the old single-call generation used.
    storyline = FakeBaseLLM.instances[0].previous_storyline
    assert "persona text" in storyline
    assert "meta notes" in storyline
    assert arc.title in storyline
    assert "PREVIOUS_CHAPTER_SITUATION" in storyline


def test_plan_chapter_retries_and_excludes_the_failing_model(profile: Profile):
    arc = write_arc(profile, "2026-10-05", weeks=12)
    _set_chapter_replies("2026-10-05", weeks=4)
    FakeBaseLLM.fail_times["chapter_outline"] = 1

    chapter, generated, outcome = _manager(profile).ensure_chapter(arc, "2026-10-05")

    assert generated is True
    assert FakeBaseLLM.call_count["chapter_outline"] == 2
    assert FakeModelRouter.excluded == [("openrouter", "some-model")]


def test_chapter_week_validation_failure_triggers_a_retry(profile: Profile):
    """A week reply with the wrong day count is a `ValueError` (pydantic),
    which the shared retry helper treats the same as a non-JSON reply."""
    arc = write_arc(profile, "2026-10-05", weeks=12)
    _set_chapter_replies("2026-10-05", weeks=1)
    bad_week = _chapter_week_reply("2026-10-05", week_index=0)
    bad_week["days"] = bad_week["days"][:-1]  # one day short
    good_week = _chapter_week_reply("2026-10-05", week_index=0)
    FakeBaseLLM.replies["chapter_week_0"] = [bad_week, good_week]

    chapter, outcome = _manager(profile).plan_chapter(arc, "2026-10-05", weeks=1)

    assert chapter.weeks == 1
    assert outcome.attempt == 2
    assert "Expected 7 days for one week, got 6" in outcome.invalid_attempts[0]


def test_chapter_week_rejects_non_contiguous_dates_and_retries(profile: Profile):
    """A week reply with the right day count but a date that doesn't align
    to that week's Monday is also invalid and retried."""
    arc = write_arc(profile, "2026-10-05", weeks=12)
    _set_chapter_replies("2026-10-05", weeks=1)
    bad_week = _chapter_week_reply("2026-10-05", week_index=0)
    bad_week["days"][3]["date"] = "2099-01-01"  # breaks contiguity
    good_week = _chapter_week_reply("2026-10-05", week_index=0)
    FakeBaseLLM.replies["chapter_week_0"] = [bad_week, good_week]

    chapter, outcome = _manager(profile).plan_chapter(arc, "2026-10-05", weeks=1)

    assert chapter.weeks == 1
    assert outcome.attempt == 2
    assert "must be exactly contiguous" in outcome.invalid_attempts[0]


def test_plan_chapter_assembles_an_outline_plus_one_call_per_week(profile: Profile):
    """
    The core of the split-generation fix: `plan_chapter` makes one outline
    call and exactly `weeks` week calls, in order, and assembles their
    results into one valid `Chapter` — instead of asking one model for the
    whole multi-week chapter in a single reply (what produced "Expected 28
    days ... got 7" in a real run).
    """
    arc = write_arc(profile, "2026-10-05", weeks=12)
    _set_chapter_replies("2026-10-05", weeks=3)

    chapter, outcome = _manager(profile).plan_chapter(arc, "2026-10-05", weeks=3)

    assert chapter.weeks == 3
    assert len(chapter.days) == 21
    assert chapter.title == "A chapter"
    assert chapter.summary == "chapter summary"
    assert len(FakeBaseLLM.instances) == 1 + 3  # outline + one call per week
    assert FakeBaseLLM.instances[0].cache_key == "chapter_outline"
    assert [i.cache_key for i in FakeBaseLLM.instances[1:]] == [
        "chapter_week_0",
        "chapter_week_1",
        "chapter_week_2",
    ]
    assert outcome.attempt == 1
    assert outcome.used_fallback is False
    assert outcome.invalid_attempts == []


def test_week_storyline_includes_the_outline_and_earlier_weeks_days(profile: Profile):
    """The input to a week call is the arc/persona/platform-notes context,
    the chapter outline, and (for week > 0) the days already generated for
    this chapter's earlier weeks — for continuity within the chapter."""
    arc = write_arc(profile, "2026-10-05", weeks=12)
    _set_chapter_replies("2026-10-05", weeks=2)

    _manager(profile).plan_chapter(arc, "2026-10-05", weeks=2)

    week0_llm, week1_llm = FakeBaseLLM.instances[1], FakeBaseLLM.instances[2]
    assert "This chapter's outline" in week0_llm.previous_storyline
    assert "week 0 summary" in week0_llm.previous_storyline
    assert "Earlier days already written" not in week0_llm.previous_storyline

    assert "week 1 summary" in week1_llm.previous_storyline
    assert (
        "Earlier days already written in this chapter" in week1_llm.previous_storyline
    )
    # Week 0's own generated day shows up as week 1's continuity input.
    assert "situation 0" in week1_llm.previous_storyline


def test_a_week_that_fails_every_attempt_saves_nothing(profile: Profile):
    """
    Generation is all-or-nothing per chapter: if any week exhausts its own
    retry budget, nothing is assembled or saved, even though an earlier
    week (and the outline) already succeeded.
    """
    arc = write_arc(profile, "2026-10-05", weeks=12)
    story_dir = profile.platform_info[Platform.META].inputs_path.parents[1] / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "config.json").write_text('{"arc_weeks": 12, "chapter_weeks": 2}')
    _set_chapter_replies("2026-10-05", weeks=2)
    FakeBaseLLM.fail_times["chapter_week_1"] = story_manager_module.MAX_CHAPTER_ATTEMPTS

    with pytest.raises(StoryGenerationFailedError):
        _manager(profile).ensure_chapter(arc, "2026-10-05")

    assert repository_for(profile).get_chapter_covering(profile, "2026-10-05") is None
    # Week 0 and the outline succeeded on their own, but week 1 never did.
    assert FakeBaseLLM.call_count["chapter_outline"] == 1
    assert FakeBaseLLM.call_count["chapter_week_0"] == 1
    assert (
        FakeBaseLLM.call_count["chapter_week_1"]
        == story_manager_module.MAX_CHAPTER_ATTEMPTS
    )


def test_chapter_outline_rejects_a_week_summary_count_mismatch(profile: Profile):
    """The outline reply must have exactly one summary per week; a mismatch
    is caught before any week call is even made."""
    arc = write_arc(profile, "2026-10-05", weeks=12)
    FakeBaseLLM.replies["chapter_outline"] = [_chapter_outline_reply(weeks=1)]

    with pytest.raises(StoryGenerationFailedError) as excinfo:
        _manager(profile).plan_chapter(arc, "2026-10-05", weeks=2)

    assert "Expected 2 week summaries, got 1" in str(excinfo.value)
    # The mismatch is caught in the outline's own retry loop; no week call
    # is ever reached (no "chapter_week_0" instance was constructed).
    assert all(i.cache_key != "chapter_week_0" for i in FakeBaseLLM.instances)


# ---------------- hand edits ----------------


def _stamped_chapter(profile: Profile, start_week: str, weeks: int = 1):
    """A chapter as `plan_chapter` would have saved it: every day stamped."""
    arc = write_arc(profile, start_week, weeks=12)
    chapter = write_chapter(profile, start_week, weeks=weeks, arc_start_week=start_week)
    chapter = chapter.model_copy(update={"days": [d.stamped() for d in chapter.days]})
    repository_for(profile).save_chapter(profile, chapter)
    return arc, chapter


def _edit_day(profile: Profile, chapter, index: int, **changes):
    days = list(chapter.days)
    days[index] = days[index].model_copy(update=changes)
    edited = chapter.model_copy(update={"days": days})
    repository_for(profile).save_chapter(profile, edited)
    return edited


def _future_monday() -> str:
    today = date.today()
    return (today + timedelta(days=7 - today.weekday())).isoformat()


def _past_monday() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday() + 7)).isoformat()


def test_generated_chapter_days_are_stamped(profile: Profile):
    arc = write_arc(profile, "2026-10-05", weeks=12)
    write_persona(profile, "persona")
    _set_chapter_replies("2026-10-05", weeks=4)

    chapter, generated, _ = _manager(profile).ensure_chapter(arc, "2026-10-05")

    assert generated is True
    assert all(day.stamp == day.current_stamp() for day in chapter.days)


def test_edited_situation_regenerates_only_that_days_angles(profile: Profile):
    start = _future_monday()
    arc, chapter = _stamped_chapter(profile, start)
    edited = _edit_day(profile, chapter, 2, situation="She rehearses in a park")
    day = edited.days[2].date
    FakeBaseLLM.replies["chapter_angles_refresh"] = [
        {"days": [{"date": day, "angles": {"meta": "new meta", "fanvue": "new fv"}}]}
    ]

    result, generated, _ = _manager(profile).ensure_chapter(arc, start)

    assert generated is False
    assert [llm.cache_key for llm in FakeBaseLLM.instances] == [
        "chapter_angles_refresh"
    ]
    assert "She rehearses in a park" in FakeBaseLLM.instances[0].previous_storyline
    assert result.days[2].angles == {"meta": "new meta", "fanvue": "new fv"}
    assert result.days[2].stamp == result.days[2].current_stamp()
    assert [d.angles for i, d in enumerate(result.days) if i != 2] == [
        d.angles for i, d in enumerate(chapter.days) if i != 2
    ]
    saved = repository_for(profile).get_chapter_covering(profile, start)
    assert saved == result


def test_edited_angles_are_kept_and_restamped(profile: Profile):
    start = _future_monday()
    arc, chapter = _stamped_chapter(profile, start)
    _edit_day(
        profile,
        chapter,
        2,
        situation="She rehearses in a park",
        angles={"meta": "my meta", "fanvue": "my fanvue"},
    )

    result, _, _ = _manager(profile).ensure_chapter(arc, start)

    assert FakeBaseLLM.instances == []
    assert result.days[2].angles == {"meta": "my meta", "fanvue": "my fanvue"}
    assert result.days[2].stamp == result.days[2].current_stamp()


def test_edited_situation_in_a_started_week_is_left_alone(profile: Profile):
    start = _past_monday()
    arc, chapter = _stamped_chapter(profile, start)
    edited = _edit_day(profile, chapter, 2, situation="She rehearses in a park")

    result, _, _ = _manager(profile).ensure_chapter(arc, start)

    assert FakeBaseLLM.instances == []
    assert result == edited
    assert result.days[2].angles_are_stale


def test_angle_refresh_retries_a_reply_with_the_wrong_days(profile: Profile):
    start = _future_monday()
    arc, chapter = _stamped_chapter(profile, start)
    edited = _edit_day(profile, chapter, 2, situation="She rehearses in a park")
    day = edited.days[2].date
    angles = {"meta": "new meta", "fanvue": "new fv"}
    FakeBaseLLM.replies["chapter_angles_refresh"] = [
        {"days": [{"date": edited.days[3].date, "angles": angles}]},
        {"days": [{"date": day, "angles": angles}]},
    ]

    result, _, _ = _manager(profile).ensure_chapter(arc, start)

    assert result.days[2].angles == angles
    assert len(FakeModelRouter.excluded) == 1
