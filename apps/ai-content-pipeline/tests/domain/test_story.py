from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from ai_content_pipeline.domain.story import (
    Arc,
    Chapter,
    ChapterDay,
    ChapterOutline,
    ChapterWeekDays,
    StoryConfig,
    chapter_boundaries_for_week,
    determine_new_arc_start,
)
from ai_content_pipeline.domain.types import Platform


def _arc(start_week: str = "2026-10-05", weeks: int = 12) -> Arc:
    return Arc(
        start_week=start_week,
        weeks=weeks,
        title="t",
        premise="p",
        goal="g",
        conflict="c",
        starting_point="s",
        ending_point="e",
        summary="sum",
    )


def _chapter_days(start_week: str, weeks: int) -> list[dict]:
    start = date.fromisoformat(start_week)
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "situation": f"day {i}",
            "angles": {"meta": "m", "fanvue": "f"},
        }
        for i in range(weeks * 7)
    ]


def _chapter(start_week: str = "2026-10-05", weeks: int = 2, **overrides) -> Chapter:
    payload = {
        "arc_start_week": start_week,
        "start_week": start_week,
        "weeks": weeks,
        "title": "t",
        "summary": "s",
        "days": _chapter_days(start_week, weeks),
    }
    payload.update(overrides)
    return Chapter.model_validate(payload)


# ---------------- StoryConfig ----------------


def test_story_config_defaults():
    config = StoryConfig()
    assert config.arc_weeks == 12
    assert config.chapter_weeks == 4


def test_story_config_rejects_non_positive_weeks():
    with pytest.raises(ValidationError):
        StoryConfig(arc_weeks=0)
    with pytest.raises(ValidationError):
        StoryConfig(chapter_weeks=-1)


def test_story_config_rejects_chapter_longer_than_arc():
    with pytest.raises(ValidationError, match="chapter_weeks"):
        StoryConfig(arc_weeks=4, chapter_weeks=8)


def test_story_config_allows_chapter_equal_to_arc():
    config = StoryConfig(arc_weeks=4, chapter_weeks=4)
    assert config.chapter_weeks == config.arc_weeks


# ---------------- Arc ----------------


def test_arc_end_week_is_derived_from_start_and_weeks():
    arc = _arc("2026-10-05", weeks=4)
    assert arc.end_week == "2026-10-26"


def test_arc_end_week_for_a_single_week_arc_equals_its_start():
    arc = _arc("2026-10-05", weeks=1)
    assert arc.end_week == "2026-10-05"


def test_arc_rejects_a_non_monday_start_week():
    with pytest.raises(ValidationError, match="Monday"):
        _arc("2026-10-06")  # a Tuesday


def test_arc_rejects_a_malformed_start_week():
    with pytest.raises(ValidationError):
        _arc("not-a-date")


def test_arc_rejects_zero_weeks():
    with pytest.raises(ValidationError):
        _arc("2026-10-05", weeks=0)


# ---------------- ChapterDay ----------------


def test_chapter_day_requires_an_angle_for_every_platform():
    with pytest.raises(ValidationError, match="angles"):
        ChapterDay(date="2026-10-05", situation="s", angles={"meta": "m"})


def test_chapter_day_rejects_a_malformed_date():
    with pytest.raises(ValidationError):
        ChapterDay(date="nope", situation="s", angles={"meta": "m", "fanvue": "f"})


def test_chapter_day_accepts_exactly_the_platform_set():
    day = ChapterDay(
        date="2026-10-05", situation="s", angles={"meta": "m", "fanvue": "f"}
    )
    assert day.angles[Platform.META.value] == "m"
    assert day.angles[Platform.FANVUE.value] == "f"


# ---------------- Chapter ----------------


def test_chapter_requires_exactly_weeks_times_7_days():
    with pytest.raises(ValidationError, match="Expected 14 days"):
        _chapter("2026-10-05", weeks=2, days=_chapter_days("2026-10-05", 1))


def test_chapter_requires_days_contiguous_from_start_week():
    days = _chapter_days("2026-10-05", 1)
    days[3]["date"] = "2099-01-01"  # breaks contiguity
    with pytest.raises(ValidationError, match="contiguous"):
        _chapter("2026-10-05", weeks=1, days=days)


def test_chapter_rejects_a_non_monday_start_week():
    with pytest.raises(ValidationError, match="Monday"):
        _chapter("2026-10-06", weeks=1, days=_chapter_days("2026-10-06", 1))


def test_week_slice_returns_the_7_days_for_a_week_inside_the_chapter():
    chapter = _chapter("2026-10-05", weeks=2)

    second_week = chapter.week_slice("2026-10-12")

    assert [d.date for d in second_week] == [
        (date(2026, 10, 12) + timedelta(days=i)).isoformat() for i in range(7)
    ]


def test_week_slice_rejects_a_week_not_aligned_to_a_chapter_boundary():
    chapter = _chapter("2026-10-05", weeks=2)

    with pytest.raises(ValueError, match="does not align"):
        chapter.week_slice("2026-10-08")


def test_week_slice_rejects_a_week_outside_the_chapter():
    chapter = _chapter("2026-10-05", weeks=1)

    with pytest.raises(ValueError, match="does not cover"):
        chapter.week_slice("2026-10-19")


# ---------------- ChapterOutline / ChapterWeekDays (split chapter gen) ----


def test_chapter_outline_rejects_empty_week_summaries():
    with pytest.raises(ValidationError, match="week_summaries"):
        ChapterOutline(title="t", summary="s", week_summaries=[])


def test_chapter_outline_accepts_one_summary_per_week():
    outline = ChapterOutline(title="t", summary="s", week_summaries=["w0", "w1"])
    assert outline.week_summaries == ["w0", "w1"]


def test_chapter_week_days_rejects_a_count_other_than_seven():
    days = _chapter_days("2026-10-05", 1)[:-1]  # 6 days
    with pytest.raises(ValidationError, match="Expected 7 days"):
        ChapterWeekDays(days=days)


def test_chapter_week_days_accepts_exactly_seven():
    days = _chapter_days("2026-10-05", 1)
    week_days = ChapterWeekDays(days=days)
    assert len(week_days.days) == 7


# ---------------- determine_new_arc_start ----------------


def test_determine_new_arc_start_with_no_previous_arc_is_the_requested_week():
    assert determine_new_arc_start(None, "2026-10-05") == "2026-10-05"


def test_determine_new_arc_start_continues_right_after_the_previous_arc():
    previous = _arc("2026-01-05", weeks=4)  # ends 2026-01-26

    assert determine_new_arc_start(previous, "2026-02-02") == "2026-02-02"


# ---------------- chapter_boundaries_for_week ----------------


def test_chapter_boundaries_tile_from_the_arcs_start_week():
    arc = _arc("2026-10-05", weeks=12)

    assert chapter_boundaries_for_week(arc, 4, "2026-10-05") == ("2026-10-05", 4)
    assert chapter_boundaries_for_week(arc, 4, "2026-10-19") == ("2026-10-05", 4)
    assert chapter_boundaries_for_week(arc, 4, "2026-11-02") == ("2026-11-02", 4)


def test_chapter_boundaries_shorten_the_last_chapter_when_arc_weeks_not_a_multiple():
    arc = _arc("2026-10-05", weeks=10)  # 10 = 4 + 4 + 2

    assert chapter_boundaries_for_week(arc, 4, "2026-12-07") == ("2026-11-30", 2)


def test_chapter_boundaries_rejects_a_week_outside_the_arc():
    arc = _arc("2026-10-05", weeks=4)

    with pytest.raises(ValueError, match="outside arc"):
        chapter_boundaries_for_week(arc, 4, "2026-11-02")


def test_chapter_boundaries_rejects_a_week_not_aligned_to_a_monday_offset():
    arc = _arc("2026-10-05", weeks=4)

    with pytest.raises(ValueError, match="outside arc"):
        chapter_boundaries_for_week(arc, 4, "2026-10-07")
