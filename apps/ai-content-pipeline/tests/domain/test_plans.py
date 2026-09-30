import pytest

from ai_content_pipeline.domain.plans import WeekPlan

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
                    "images": [{"image_description": "a beach"}],
                }
            ],
        }
    ]
}


def test_a_planning_dict_round_trips_unchanged():
    assert WeekPlan.from_planning_dict(PLANNING).to_planning_dict() == PLANNING


def test_the_top_level_key_becomes_the_week():
    assert WeekPlan.from_planning_dict(PLANNING).week == "week_1"


def test_fields_the_llm_omitted_fall_back_to_todays_defaults():
    plan = WeekPlan.from_planning_dict({"week_1": [{"day": 1, "posts": [{}]}]})

    post = plan.days[0].posts[0]
    assert (post.title, post.caption, post.hashtags, post.upload_time) == (
        "",
        "",
        [],
        "",
    )
    assert post.images == []


@pytest.mark.parametrize("planning", [{}, {"week_1": [], "week_2": []}])
def test_a_planning_that_is_not_exactly_one_week_is_rejected(planning):
    with pytest.raises(ValueError, match="exactly one week"):
        WeekPlan.from_planning_dict(planning)
