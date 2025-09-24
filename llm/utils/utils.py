import json
from datetime import datetime, timedelta
from pathlib import Path

from main_components.common.types import PromptItem


def get_closest_monday():
    """
    Return the closest Monday relative to today.

    - If today is Monday: return today.
    - If today is Tuesday–Thursday: return the previous Monday.
    - If today is Friday–Sunday: return the next Monday.
    """
    today = datetime.now()
    weekday = today.weekday()  # Monday = 0, Sunday = 6

    if weekday == 0:  # If today is Monday
        return today
    elif weekday < 4:  # Tuesday (1), Wednesday (2), Thursday (3)
        # Return Monday of current week (go back to the most recent Monday)
        return today - timedelta(days=weekday)
    else:  # Friday (4), Saturday (5), Sunday (6)
        # Return next Monday (go forward to the upcoming Monday)
        return today + timedelta(days=(7 - weekday))


def load_and_prepare_prompts(
    prompt_json_template_path: Path,
    previous_storyline: str,
) -> list[PromptItem]:
    """
    Load the prompt JSON, apply dynamic fields, and return list[PromptItem].
    """
    # Load raw JSON
    with prompt_json_template_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    prompts_data = payload.get("prompts", [])
    # 1. Validate raw items while placeholders still present
    raw_items = [PromptItem(**p) for p in prompts_data]

    # 2. Format copies (do not mutate originals)
    day_str = f"Monday {get_closest_monday().strftime('%Y-%m-%d')}"
    formatted_items: list[PromptItem] = []

    for idx, item in enumerate(raw_items):
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
