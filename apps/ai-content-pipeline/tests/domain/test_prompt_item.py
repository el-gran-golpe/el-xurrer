import pytest

from ai_content_pipeline.domain.types import PromptItem


def _item(prompt: str, system_prompt: str = "You plan for {day}.") -> PromptItem:
    return PromptItem(
        prompt=prompt,
        cache_key="next",
        system_prompt=system_prompt,
        output_as_json=False,
        is_sensitive_content=False,
    )


def test_placeholders_are_replaced_in_place_with_earlier_replies():
    """
    Regression: the replacement used to be computed on a loop variable and
    thrown away, so step 2 of a prompt chain never saw step 1's reply.
    """
    item = _item(
        "Turn this into posts:\n{weekly_storylines}", "Expert in {topic} for {day}."
    )

    item.replace_prompt_placeholders(
        cache={
            "weekly_storylines": "Day 1: rehearsal",
            "topic": "Instagram",
            "day": "Monday",
        }
    )

    assert item.prompt == "Turn this into posts:\nDay 1: rehearsal"
    assert item.system_prompt == "Expert in Instagram for Monday."


def test_an_unknown_placeholder_fails_unless_unfilled_ones_are_accepted():
    with pytest.raises(AssertionError, match="weekly_storylines"):
        _item("{weekly_storylines}").replace_prompt_placeholders(
            cache={"day": "Monday"}
        )

    item = _item("{weekly_storylines} and {known}")
    item.replace_prompt_placeholders(
        cache={"known": "x", "day": "Monday"}, accept_unfilled=True
    )
    assert item.prompt == "{weekly_storylines} and x"
