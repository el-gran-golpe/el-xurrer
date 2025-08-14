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
    with prompt_json_template_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    # Load as dicts
    prompts = payload["prompts"]
    day = f"Monday {get_closest_monday().strftime('%Y-%m-%d')}"

    # TODO: this previous_storyline in the first one should be checked in profile.py
    if prompts and previous_storyline:
        if "{previous_storyline}" in prompts[0].get("prompt", ""):
            prompts[0]["prompt"] = prompts[0]["prompt"].format(
                previous_storyline=previous_storyline
            )

    for p in prompts:
        if "system_prompt" in p and "{day}" in p["system_prompt"]:
            p["system_prompt"] = p["system_prompt"].format(day=day)

    # Convert to PromptItem models
    prompt_items = [PromptItem.model_validate(p) for p in prompts]
    return prompt_items
