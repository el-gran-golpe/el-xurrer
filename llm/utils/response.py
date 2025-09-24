import re
import json
from loguru import logger


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

