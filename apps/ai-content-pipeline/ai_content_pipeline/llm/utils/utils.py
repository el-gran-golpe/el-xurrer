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
