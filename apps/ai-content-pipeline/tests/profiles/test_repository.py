import json

import pytest

from ai_content_pipeline.domain.plans import DayPlan, PostPlan, WeekPlan
from ai_content_pipeline.domain.story import Arc, StoryConfig
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import make_chapter, repository_for, write_persona

PLAN = WeekPlan(
    week="week_1",
    days=[DayPlan(day=1, posts=[PostPlan(title="Beach", caption="sun")])],
)


def _planning_file(profile: Profile, platform: Platform):
    return profile.platform_info[platform].outputs_path / "h_planning.json"


def _history_file(profile: Profile, platform: Platform, week: str):
    return (
        profile.platform_info[platform].outputs_path
        / "history"
        / f"{week}_planning.json"
    )


def test_get_platform_profile_reads_prompts_and_stripped_initial_conditions(
    profile: Profile,
):
    inputs = profile.platform_info[Platform.META].inputs_path
    (inputs / "initial_conditions.md").write_text("  hello world \n", "utf-8")

    platform_profile = repository_for(profile).get_platform_profile(
        profile, Platform.META
    )

    assert platform_profile.platform is Platform.META
    assert platform_profile.lang == "en"
    assert [p.cache_key for p in platform_profile.prompts] == ["week"]
    assert platform_profile.initial_conditions == "hello world"


def test_save_week_plan_keeps_todays_file_name_and_week_keyed_format(
    profile: Profile,
):
    repository_for(profile).save_week_plan(profile, Platform.META, PLAN)

    on_disk = json.loads(_planning_file(profile, Platform.META).read_text("utf-8"))
    assert list(on_disk) == ["week_1"]
    assert on_disk["week_1"][0]["posts"][0]["caption"] == "sun"


def test_week_plan_round_trips_and_platforms_do_not_collide(profile: Profile):
    repo = repository_for(profile)
    fanvue_plan = PLAN.model_copy(update={"week": "week_2"})

    repo.save_week_plan(profile, Platform.META, PLAN)
    repo.save_week_plan(profile, Platform.FANVUE, fanvue_plan)

    assert repo.get_week_plan(profile, Platform.META) == PLAN
    assert repo.get_week_plan(profile, Platform.FANVUE) == fanvue_plan


def test_the_persona_is_shared_by_the_whole_profile(profile: Profile):
    write_persona(profile, "  28, grew up in Porto.  ")

    assert repository_for(profile).get_persona(profile) == "28, grew up in Porto."


def test_a_profile_without_a_persona_reads_empty_rather_than_failing(
    profile: Profile,
):
    assert repository_for(profile).get_persona(profile) == ""


# --- save_week_plan: archiving current -> history -----------------------


def test_saving_a_new_week_archives_the_previous_current_plan(profile: Profile):
    repo = repository_for(profile)
    week_1 = WeekPlan.model_validate({"week": "2026-10-05", "days": PLAN.days})
    week_2 = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})

    repo.save_week_plan(profile, Platform.META, week_1)
    repo.save_week_plan(profile, Platform.META, week_2)

    assert repo.get_week_plan(profile, Platform.META).week == "2026-10-12"
    assert _history_file(profile, Platform.META, "2026-10-05").is_file()
    archived = json.loads(
        _history_file(profile, Platform.META, "2026-10-05").read_text("utf-8")
    )
    assert list(archived) == ["2026-10-05"]


def test_resaving_the_same_week_does_not_archive_anything(profile: Profile):
    repo = repository_for(profile)
    week_1 = WeekPlan.model_validate({"week": "2026-10-05", "days": PLAN.days})
    updated = week_1.model_copy(
        update={"days": [DayPlan(day=1, posts=[PostPlan(caption="updated")])]}
    )

    repo.save_week_plan(profile, Platform.META, week_1)
    repo.save_week_plan(profile, Platform.META, updated)

    history_dir = profile.platform_info[Platform.META].outputs_path / "history"
    assert not history_dir.exists()
    assert repo.get_week_plan(profile, Platform.META).days[0].posts[0].caption == (
        "updated"
    )


def test_archiving_over_an_existing_history_file_overwrites_it_with_a_warning(
    profile: Profile, caplog
):
    repo = repository_for(profile)
    week_1 = WeekPlan.model_validate({"week": "2026-10-05", "days": PLAN.days})
    week_2 = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})
    week_1_updated = week_1.model_copy(
        update={"days": [DayPlan(day=1, posts=[PostPlan(caption="second pass")])]}
    )

    repo.save_week_plan(profile, Platform.META, week_1)
    repo.save_week_plan(profile, Platform.META, week_2)  # archives week_1
    repo.save_week_plan(profile, Platform.META, week_1_updated)  # back to week_1
    repo.save_week_plan(profile, Platform.META, week_2)  # archives week_1 again

    archived = json.loads(
        _history_file(profile, Platform.META, "2026-10-05").read_text("utf-8")
    )
    assert archived["2026-10-05"][0]["posts"][0]["caption"] == "second pass"


def test_saving_an_older_week_while_a_newer_one_is_current_goes_to_history_and_leaves_current_untouched(
    profile: Profile, caplog
):
    """
    With `--weeks N`, week k can be (re-)planned (e.g. retried after a
    failure) after week k+1 already became current. Writing week k as
    current would demote the newer week; it must land straight in
    `history/` instead, leaving current exactly as it was.
    """
    repo = repository_for(profile)
    week_1 = WeekPlan.model_validate({"week": "2026-10-05", "days": PLAN.days})
    week_2 = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})
    repo.save_week_plan(profile, Platform.META, week_2)  # week_2 becomes current

    repo.save_week_plan(profile, Platform.META, week_1)  # older than current

    assert repo.get_week_plan(profile, Platform.META).week == "2026-10-12"
    assert _history_file(profile, Platform.META, "2026-10-05").is_file()
    archived = json.loads(
        _history_file(profile, Platform.META, "2026-10-05").read_text("utf-8")
    )
    assert list(archived) == ["2026-10-05"]


def test_get_week_plan_resolves_a_week_saved_straight_into_history(profile: Profile):
    repo = repository_for(profile)
    week_1 = WeekPlan.model_validate({"week": "2026-10-05", "days": PLAN.days})
    week_2 = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})
    repo.save_week_plan(profile, Platform.META, week_2)
    repo.save_week_plan(profile, Platform.META, week_1)  # saved straight to history

    assert repo.get_week_plan(profile, Platform.META, "2026-10-05") == week_1


def test_a_legacy_current_plan_is_archived_normally_when_a_dated_week_is_saved(
    profile: Profile,
):
    """A legacy (non-dated) current is always older than a dated week, so
    the normal archive-then-write path applies, same as before dated weeks
    existed."""
    repo = repository_for(profile)
    repo.save_week_plan(profile, Platform.META, PLAN)  # week="week_1", legacy
    dated = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})

    repo.save_week_plan(profile, Platform.META, dated)

    assert repo.get_week_plan(profile, Platform.META).week == "2026-10-12"
    assert _history_file(profile, Platform.META, "week_1").is_file()


def test_a_malformed_legacy_current_plan_is_archived_as_is(profile: Profile):
    """A real legacy `run_all` plan had a day whose posts were a flat list of
    strings: it never validated. Saving a new week must still archive it,
    untouched, instead of failing on it."""
    repo = repository_for(profile)
    malformed = {"week_1": [{"day": 1, "posts": ["title", "Saturday Crypt"]}]}
    _planning_file(profile, Platform.META).write_text(json.dumps(malformed))
    dated = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})

    repo.save_week_plan(profile, Platform.META, dated)

    assert repo.get_week_plan(profile, Platform.META).week == "2026-10-12"
    archived = _history_file(profile, Platform.META, "week_1")
    assert json.loads(archived.read_text()) == malformed


# --- get_week_plan: current vs history vs missing ------------------------


def test_get_week_plan_with_a_week_returns_the_current_plan_when_it_matches(
    profile: Profile,
):
    repo = repository_for(profile)
    week_2 = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})
    repo.save_week_plan(profile, Platform.META, week_2)

    assert repo.get_week_plan(profile, Platform.META, "2026-10-12") == week_2


def test_get_week_plan_with_a_week_falls_back_to_history(profile: Profile):
    repo = repository_for(profile)
    week_1 = WeekPlan.model_validate({"week": "2026-10-05", "days": PLAN.days})
    week_2 = WeekPlan.model_validate({"week": "2026-10-12", "days": PLAN.days})
    repo.save_week_plan(profile, Platform.META, week_1)
    repo.save_week_plan(profile, Platform.META, week_2)  # archives week_1

    assert repo.get_week_plan(profile, Platform.META, "2026-10-05") == week_1


def test_get_week_plan_with_an_unknown_week_raises(profile: Profile):
    repo = repository_for(profile)
    repo.save_week_plan(profile, Platform.META, PLAN)

    with pytest.raises(FileNotFoundError):
        repo.get_week_plan(profile, Platform.META, "2099-01-01")


# --- story: config ---------------------------------------------------------


def test_get_story_config_defaults_when_missing(profile: Profile):
    repo = repository_for(profile)

    config = repo.get_story_config(profile)

    assert config == StoryConfig(arc_weeks=12, chapter_weeks=4)


def test_get_story_config_reads_the_config_file(profile: Profile):
    repo = repository_for(profile)
    story_dir = profile.platform_info[Platform.META].inputs_path.parents[1] / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "config.json").write_text(
        json.dumps({"arc_weeks": 8, "chapter_weeks": 2}), encoding="utf-8"
    )

    config = repo.get_story_config(profile)

    assert config == StoryConfig(arc_weeks=8, chapter_weeks=2)


# --- story: arcs -------------------------------------------------------------


def _arc(start_week: str, weeks: int = 12) -> Arc:
    return Arc(
        start_week=start_week,
        weeks=weeks,
        title="Season one",
        premise="premise",
        goal="goal",
        conflict="conflict",
        starting_point="start",
        ending_point="end",
        summary="summary",
    )


def test_save_arc_and_get_arc_covering_round_trip(profile: Profile):
    repo = repository_for(profile)
    arc = _arc("2026-10-05", weeks=4)

    repo.save_arc(profile, arc)

    assert repo.get_arc_covering(profile, "2026-10-12") == arc
    assert repo.get_arc_covering(profile, "2026-10-05") == arc
    assert repo.get_arc_covering(profile, "2026-10-26") == arc  # last week (+3)


def test_get_arc_covering_returns_none_outside_the_arcs_range(profile: Profile):
    repo = repository_for(profile)
    repo.save_arc(profile, _arc("2026-10-05", weeks=4))

    assert repo.get_arc_covering(profile, "2026-11-09") is None
    assert repo.get_arc_covering(profile, "2026-09-28") is None


def test_get_previous_arc_picks_the_latest_arc_strictly_before_the_target(
    profile: Profile,
):
    repo = repository_for(profile)
    repo.save_arc(profile, _arc("2026-01-05", weeks=4))
    repo.save_arc(profile, _arc("2026-10-05", weeks=4))

    previous = repo.get_previous_arc(profile, before="2026-10-12")

    assert previous is not None
    assert previous.start_week == "2026-10-05"


def test_get_previous_arc_returns_none_without_any_arc(profile: Profile):
    repo = repository_for(profile)

    assert repo.get_previous_arc(profile, before="2026-10-12") is None


# --- story: chapters ---------------------------------------------------------


def test_save_chapter_and_get_chapter_covering_round_trip(profile: Profile):
    repo = repository_for(profile)
    chapter = make_chapter("2026-10-05", weeks=2)

    repo.save_chapter(profile, chapter)

    assert repo.get_chapter_covering(profile, "2026-10-05") == chapter
    assert repo.get_chapter_covering(profile, "2026-10-12") == chapter


def test_get_chapter_covering_returns_none_outside_its_range(profile: Profile):
    repo = repository_for(profile)
    repo.save_chapter(profile, make_chapter("2026-10-05", weeks=2))

    assert repo.get_chapter_covering(profile, "2026-10-19") is None


def test_get_chapters_of_arc_returns_only_that_arcs_chapters_sorted(profile: Profile):
    repo = repository_for(profile)
    other_arc_chapter = make_chapter("2026-01-05", weeks=4, arc_start_week="2026-01-05")
    chapter_2 = make_chapter("2026-11-02", weeks=4, arc_start_week="2026-10-05")
    chapter_1 = make_chapter("2026-10-05", weeks=4, arc_start_week="2026-10-05")
    repo.save_chapter(profile, other_arc_chapter)
    repo.save_chapter(profile, chapter_2)
    repo.save_chapter(profile, chapter_1)

    chapters = repo.get_chapters_of_arc(profile, "2026-10-05")

    assert [c.start_week for c in chapters] == ["2026-10-05", "2026-11-02"]
