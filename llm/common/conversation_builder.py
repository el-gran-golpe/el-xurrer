from typing import Union
from llm.common.prompt_utils import replace_prompt_placeholders


def normalize_prompt_spec(raw: Union[dict, object]) -> dict:
    if isinstance(raw, dict):
        return {
            "system_prompt": raw.get("system_prompt", ""),
            "prompt": raw["prompt"],
            "cache_key": raw["cache_key"],
            "json": raw.get("json", False),
            "force_reasoning": raw.get("force_reasoning", False),
            "large_output": raw.get("large_output", False),
            "validate": raw.get("validate", False),
        }
    return {
        "system_prompt": getattr(raw, "system_prompt", ""),
        "prompt": getattr(raw, "prompt"),
        "cache_key": getattr(raw, "cache_key"),
        "json": getattr(raw, "json", False),
        "force_reasoning": getattr(raw, "force_reasoning", False),
        "large_output": getattr(raw, "large_output", False),
        "validate": getattr(raw, "validate", False),
    }


def prepare_conversation(spec: dict, cache: dict[str, str]) -> list[dict]:
    system_content = replace_prompt_placeholders(
        prompt=spec["system_prompt"],
        cache=cache,
        accept_unfilled=False,
    )
    user_content = replace_prompt_placeholders(
        prompt=spec["prompt"],
        cache=cache,
        accept_unfilled=False,
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
