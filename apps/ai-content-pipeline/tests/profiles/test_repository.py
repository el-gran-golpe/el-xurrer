import json

from ai_content_pipeline.domain.plans import DayPlan, PostPlan, WeekPlan
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import repository_for, write_persona

PLAN = WeekPlan(
    week="week_1",
    days=[DayPlan(day=1, posts=[PostPlan(title="Beach", caption="sun")])],
)


def _planning_file(profile: Profile, platform: Platform):
    return profile.platform_info[platform].outputs_path / "h_planning.json"


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
