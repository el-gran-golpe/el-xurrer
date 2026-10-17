from datetime import date

import pytest

from ai_content_pipeline.domain.plans import DayPlan, PostPlan, WeekPlan, summarize_week

PLANNING = {
    "week_1": [
        {
            "day": 1,
            "posts": [
                {
                    "title": "Beach day",
                    "caption": "sun",
                    "hashtags": "#sun",
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
        "",
        "",
    )
    assert post.images == []


def test_a_hashtag_list_from_the_llm_is_joined_into_the_stored_string():
    plan = WeekPlan.from_planning_dict(
        {"week_1": [{"day": 1, "posts": [{"hashtags": ["#sun", " #sea ", ""]}]}]}
    )

    assert plan.days[0].posts[0].hashtags == "#sun #sea"


@pytest.mark.parametrize("planning", [{}, {"week_1": [], "week_2": []}])
def test_a_planning_that_is_not_exactly_one_week_is_rejected(planning):
    with pytest.raises(ValueError, match="exactly one week"):
        WeekPlan.from_planning_dict(planning)


# --- summarize_week --------------------------------------------------------


def test_summarize_week_includes_the_date_title_and_caption():
    plan = WeekPlan(
        week="2026-10-05",
        days=[
            DayPlan(
                day=1,
                posts=[
                    PostPlan(
                        title="Beach day",
                        caption="Sun and sand all day long",
                        upload_time="2026-10-05T10:00:00Z",
                    )
                ],
            )
        ],
    )

    summary = summarize_week(plan)

    assert summary == "- 2026-10-05: Beach day — Sun and sand all day long"


def test_summarize_week_falls_back_to_the_day_number_when_upload_time_is_unparseable():
    plan = WeekPlan(
        week="week_1",
        days=[DayPlan(day=2, posts=[PostPlan(title="Coffee", caption="brew")])],
    )

    summary = summarize_week(plan)

    assert summary == "- day 2: Coffee — brew"


def test_summarize_week_truncates_a_long_caption():
    plan = WeekPlan(
        week="week_1",
        days=[DayPlan(day=1, posts=[PostPlan(caption="x" * 400)])],
    )

    summary = summarize_week(plan)

    line = summary.splitlines()[0]
    assert line.endswith("...")
    assert len(line) <= len("- day 1: ") + 280


def test_summarize_week_skips_days_with_no_posts():
    plan = WeekPlan(
        week="week_1",
        days=[
            DayPlan(day=1, posts=[]),
            DayPlan(day=2, posts=[PostPlan(caption="brew")]),
        ],
    )

    assert summarize_week(plan) == "- day 2: brew"


def _full_week(upload_times: list[str]) -> WeekPlan:
    return WeekPlan.from_planning_dict(
        {
            "week_1": [
                {"day": n, "posts": [{"upload_time": t}]}
                for n, t in enumerate(upload_times, start=1)
            ]
        }
    )


def test_pin_to_week_moves_each_day_to_its_own_date_and_keeps_the_time():
    plan = _full_week(["2026-10-12T09:00:00Z"] * 4 + ["2026-10-13T20:30:00+02:00"] * 3)

    corrections = plan.pin_to_week(date(2026, 10, 12))

    assert [day.posts[0].upload_time for day in plan.days] == [
        "2026-10-12T09:00:00Z",
        "2026-10-13T09:00:00Z",
        "2026-10-14T09:00:00Z",
        "2026-10-15T09:00:00Z",
        "2026-10-16T20:30:00+02:00",
        "2026-10-17T20:30:00+02:00",
        "2026-10-18T20:30:00+02:00",
    ]
    assert len(corrections) == 6  # day 1 was already right


def test_pin_to_week_falls_back_to_utc_evening_and_never_leaves_times_naive():
    plan = _full_week(["", "not a date", "2026-10-14T10:00:00"] + ["x"] * 4)

    plan.pin_to_week(date(2026, 10, 12))

    assert [day.posts[0].upload_time for day in plan.days[:3]] == [
        "2026-10-12T18:00:00Z",
        "2026-10-13T18:00:00Z",
        "2026-10-14T10:00:00Z",
    ]


@pytest.mark.parametrize(
    "days",
    [
        [{"day": n, "posts": [{}]} for n in range(1, 7)],  # day 7 missing
        [{"day": n, "posts": [{}]} for n in [1, 1, 2, 3, 4, 5, 6]],  # repeated
        [{"day": n, "posts": [{}] if n != 3 else []} for n in range(1, 8)],
    ],
)
def test_pin_to_week_rejects_a_week_that_is_not_one_entry_per_day(days):
    plan = WeekPlan.from_planning_dict({"week_1": days})

    with pytest.raises(ValueError):
        plan.pin_to_week(date(2026, 10, 12))
