from typing import List, Dict, Any
from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage


def conversation_to_openai_format(
    conversation: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    OpenAI expects a list of dicts like {"role": "...", "content": "..."}.
    """
    formatted: List[Dict[str, Any]] = []
    for message in conversation:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ValueError(f"Unknown role in conversation: {role}")
        formatted.append({"role": role, "content": content})
    return formatted


def conversation_to_azure_format(conversation: List[Dict[str, Any]]) -> List:
    formatted = []
    for message in conversation:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            formatted.append(SystemMessage(content=content))
        elif role == "user":
            formatted.append(UserMessage(content=content))
        elif role == "assistant":
            formatted.append(AssistantMessage(content=content))
        else:
            raise ValueError(f"Unknown role in conversation: {role}")
    return formatted


def merge_system_and_user_messages(
    conversation: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged_conversation: list[Dict[str, Any]] = []
    last_system_message: str | None = None

    for message in conversation:
        role = message.get("role")
        content = message.get("content", "")
        if role == "system":
            if last_system_message is not None:
                raise AssertionError(
                    "Previous system message was not consumed before new one"
                )
            last_system_message = content
        elif role == "user":
            if last_system_message is not None:
                new_message = last_system_message + "\n\n" + content
                merged_conversation.append({"role": "user", "content": new_message})
                last_system_message = None
            else:
                merged_conversation.append(message)
        else:  # assistant or other
            if last_system_message is not None:
                raise AssertionError(
                    "Last system message is dangling and was not merged"
                )
            merged_conversation.append(message)

    assert last_system_message is None, "Last message was a system message. Unexpected"
    return merged_conversation
