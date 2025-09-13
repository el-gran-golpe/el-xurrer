import re
import json
from typing import Tuple
from loguru import logger

from llm.constants import VALIDATION_SYSTEM_PROMPT


def decode_json_from_message(message: str) -> dict:
    """Decodes a json from a str that is the response from a model"""
    cleaned = message.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json") :]
    cleaned = cleaned.replace("```json", "").replace("```", "")

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        logger.error(
            "No JSON object found in assistant message. Snippet: {}", cleaned[:500]
        )
        raise ValueError(f"No JSON object found in message: {message[:200]}")

    json_str = match.group(0)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON: {}. Raw: {}", e, json_str)
        fixed = re.sub(r",\s*}", "}", json_str)
        try:
            return json.loads(fixed)
        except Exception:
            raise


def recalculate_finish_reason(
    assistant_reply: str,
    get_model_response_callable,
    preferred_validation_models: list[str],
) -> Tuple[str, str]:
    conversation = [
        {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
        {"role": "user", "content": assistant_reply},
    ]

    try:
        output_dict_str, finish_reason = get_model_response_callable(
            conversation=conversation,
            options=None,
            preferred_models=preferred_validation_models,
            verbose=False,
        )
    except Exception as e:
        logger.warning("Validation model call failed: {}", e)
        return finish_reason, assistant_reply

    try:
        output_dict = decode_json_from_message(output_dict_str)
    except Exception:
        logger.warning("Failed to decode validation output; keeping original")
        return finish_reason, assistant_reply

    if "finish_reason" not in output_dict or "markers" not in output_dict:
        logger.warning("Validation output missing keys: {}", output_dict)
        return finish_reason, assistant_reply

    new_finish_reason = output_dict["finish_reason"]
    markers = output_dict["markers"]

    for marker in markers:
        m = f"{marker}."
        while m not in assistant_reply and m.endswith("."):
            m = m[:-1]
        if m in assistant_reply:
            assistant_reply = assistant_reply.replace(m, "").strip()

    if assistant_reply == "":
        logger.error(
            "Assistant reply empty after removing markers; forcing finish_reason to stop"
        )
        new_finish_reason = "stop"

    return new_finish_reason, assistant_reply
