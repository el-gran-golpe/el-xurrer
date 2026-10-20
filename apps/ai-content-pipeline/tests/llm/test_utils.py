from datetime import date

import pytest

from ai_content_pipeline.domain.types import PromptItem
from ai_content_pipeline.llm.utils.utils import (
    planning_week_start,
    prepare_prompts,
    validate_start_week,
)


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 12), date(2026, 10, 12)),  # Monday itself
        (date(2026, 10, 13), date(2026, 10, 19)),  # Tuesday
        (date(2026, 10, 14), date(2026, 10, 19)),  # Wednesday
        (date(2026, 10, 15), date(2026, 10, 19)),  # Thursday
        (date(2026, 10, 16), date(2026, 10, 19)),  # Friday
        (date(2026, 10, 17), date(2026, 10, 19)),  # Saturday
        (date(2026, 10, 18), date(2026, 10, 19)),  # Sunday
    ],
)
def test_planning_week_start_returns_the_target_monday(today, expected):
    assert planning_week_start(today) == expected


@pytest.mark.parametrize(
    "start",
    [
        date(2026, 10, 19),  # the current week, already started
        date(2026, 10, 26),  # next week
    ],
)
def test_validate_start_week_accepts_the_current_or_a_later_monday(start):
    assert validate_start_week(start, today=date(2026, 10, 20)) == start


def test_validate_start_week_rejects_a_day_that_is_not_a_monday():
    with pytest.raises(ValueError, match="not a Monday"):
        validate_start_week(date(2026, 10, 21), today=date(2026, 10, 20))


def test_validate_start_week_rejects_a_week_that_already_ended():
    with pytest.raises(ValueError, match="before the current week"):
        validate_start_week(date(2026, 10, 12), today=date(2026, 10, 20))


def _prompt_item(
    system_prompt: str = "Plan starting {day}.", prompt: str = "go"
) -> PromptItem:
    return PromptItem(
        prompt=prompt,
        cache_key="week",
        system_prompt=system_prompt,
        output_as_json=True,
        is_sensitive_content=False,
    )


def test_prepare_prompts_substitutes_day_with_the_given_week_start():
    items = prepare_prompts(
        prompts=[_prompt_item()],
        previous_storyline="",
        week_start=date(2026, 10, 12),
    )

    assert items[0].system_prompt == "Plan starting Monday 2026-10-12."


def test_prepare_prompts_substitutes_previous_storyline_on_the_first_prompt_only():
    items = prepare_prompts(
        prompts=[
            _prompt_item(prompt="So far: {previous_storyline}"),
            _prompt_item(prompt="So far: {previous_storyline}"),
        ],
        previous_storyline="she was in Lisbon",
        week_start=date(2026, 10, 12),
    )

    assert items[0].prompt == "So far: she was in Lisbon"
    assert items[1].prompt == "So far: {previous_storyline}"


def test_prepare_prompts_does_not_mutate_the_originals():
    original = _prompt_item()

    prepare_prompts(
        prompts=[original], previous_storyline="", week_start=date(2026, 10, 12)
    )

    assert original.system_prompt == "Plan starting {day}."
