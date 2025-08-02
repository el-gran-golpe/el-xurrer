import re
import json
from llm.common.constants import VALIDATION_SYSTEM_PROMPT
from loguru import logger


def decode_json_from_message(message: str) -> dict:
    if message.startswith("```json"):
        message = message[len("```json") : -len("```")]

        # THOUGHTS: Check why is this used three times, I think is because of the json format but check it anyway
        message = (
            message.replace("\n```json", "")
            .replace("```json\n", "")
            .replace("```json", "")
        )

    message = message.strip('"')
    # Remove trailing commas before closing brackets
    message = re.sub(r",\s*}", "}", message)
    try:
        return json.loads(message)
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from message: {message}")
        raise


def recalculate_finish_reason(
    assistant_reply: str,
    get_model_response,
    preferred_validation_models: list[str],
) -> tuple[str, str]:
    """
    Validate that the finish reason is the expected one.
    Calls the provided get_model_response function.
    """
    conversation = [
        {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
        {"role": "user", "content": assistant_reply},
    ]

    print("\n\n----------------- VALIDATION -----------------")
    output_dict, finish_reason = get_model_response(
        conversation=conversation,
        preferred_models=preferred_validation_models,
        as_json=True,
        validate=False,
        large_output=False,
        force_reasoning=False,
    )
    output_dict = decode_json_from_message(message=output_dict)

    assert "finish_reason" in output_dict, (
        f"Finish reason not found in the output: {output_dict}"
    )
    assert "markers" in output_dict, f"Markers not found in the output: {output_dict}"

    finish_reason, markers = output_dict["finish_reason"], output_dict["markers"]
    if finish_reason == "stop":
        assert len(markers) == 0, (
            f"Markers found in the assistant reply when finish_reason is stop: "
            f"{markers}"
        )
    for marker in markers:
        marker = f"{marker}."
        while marker not in assistant_reply and marker.endswith("."):
            marker = marker[:-1]
        assert marker in assistant_reply, (
            f"Marker not found in the assistant reply: {marker}"
        )
        assistant_reply = assistant_reply.replace(marker, "").strip()
    if assistant_reply == "":
        logger.error("Assistant reply is empty after removing the markers")
        finish_reason = "stop"
    return finish_reason, assistant_reply
