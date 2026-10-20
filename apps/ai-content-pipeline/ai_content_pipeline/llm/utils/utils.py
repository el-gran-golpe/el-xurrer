from datetime import date, timedelta

from ai_content_pipeline.domain.types import PromptItem


def planning_week_start(today: date) -> date:
    """
    Return the Monday `plan` should target: `today` if `today` is a Monday,
    otherwise the next Monday.

    Deliberately deterministic (a function of the clock only, not of what is
    already planned): "the Monday after the latest planned week" would plan
    a new week on every re-run of `jobs run` and break resume.
    """
    days_until_monday = (7 - today.weekday()) % 7  # Monday == 0
    return (
        today if days_until_monday == 0 else today + timedelta(days=days_until_monday)
    )


def validate_start_week(start: date, today: date) -> date:
    """
    Check an explicit `jobs run --start-week`: it must be a Monday, and not
    before the Monday of the week containing `today`.

    The default target (`planning_week_start`) skips a week that has
    already started, so a week nobody planned in time would otherwise be
    jumped over; this lets a run start on that week instead. Anything
    earlier is rejected so a typo cannot re-plan a week that already ended.
    """
    if start.weekday() != 0:
        raise ValueError(f"{start.isoformat()} is not a Monday")
    current_monday = today - timedelta(days=today.weekday())
    if start < current_monday:
        raise ValueError(
            f"{start.isoformat()} is before the current week "
            f"({current_monday.isoformat()})"
        )
    return start


def prepare_prompts(
    prompts: list[PromptItem],
    previous_storyline: str,
    week_start: date,
) -> list[PromptItem]:
    """
    Apply dynamic fields to already-validated prompts and return copies.
    """
    # Format copies (do not mutate originals)
    day_str = f"Monday {week_start:%Y-%m-%d}"
    formatted_items: list[PromptItem] = []

    for idx, item in enumerate(prompts):
        sys_prompt = item.system_prompt
        if "{day}" in sys_prompt:
            sys_prompt = sys_prompt.format(day=day_str)

        prompt_text = item.prompt
        if (
            idx == 0
            and previous_storyline
            and prompt_text
            and "{previous_storyline}" in prompt_text
        ):
            prompt_text = prompt_text.format(previous_storyline=previous_storyline)

        # model_copy validates updated fields (allowed by relaxed validator)
        formatted_items.append(
            item.model_copy(update={"system_prompt": sys_prompt, "prompt": prompt_text})
        )

    return formatted_items


# def _clean_chain_of_thought(model: str, assistant_reply: str) -> str:
#     if model in MODELS_INCLUDING_CHAIN_THOUGHT:
#         return re.sub(
#             r"<think>.*?</think>", "", assistant_reply, flags=re.DOTALL
#         ).strip()
#     return assistant_reply
