from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
)
from azure.ai.inference.models import (
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ChatRequestMessage,
)
from typing import Union, List


def conversation_to_openai_format(
    conversation: List[dict],
) -> List[
    Union[
        ChatCompletionSystemMessageParam,
        ChatCompletionUserMessageParam,
        ChatCompletionAssistantMessageParam,
    ]
]:
    openai_conversation = []
    for message in conversation:
        assert "content" in message and "role" in message
        content, role = message["content"], message["role"]
        if role == "user":
            openai_message = ChatCompletionUserMessageParam(content=content, role=role)
        elif role == "assistant":
            openai_message = ChatCompletionAssistantMessageParam(
                content=content, role=role
            )
        elif role == "system":
            openai_message = ChatCompletionSystemMessageParam(
                content=content, role=role
            )
        else:
            raise ValueError(f"Invalid role: {role}")
        openai_conversation.append(openai_message)
    return openai_conversation


def conversation_to_azure_format(conversation: List[dict]) -> List[ChatRequestMessage]:
    azure_conversation = []
    for message in conversation:
        assert "content" in message and "role" in message
        content, role = message["content"], message["role"]
        if role == "user":
            azure_message = UserMessage(content=content)
        elif role == "assistant":
            azure_message = AssistantMessage(content=content)
        elif role == "system":
            azure_message = SystemMessage(content=content)
        else:
            raise ValueError(f"Invalid role: {role}")
        azure_conversation.append(azure_message)
    return azure_conversation


def merge_system_and_user_messages(conversation: list[dict]) -> list[dict]:
    """
    for each message, if its 'role' is 'system', merge it with the next 'user' message
    :param conversation: The conversation to merge. A list of dictionaries with 'role' and 'content'
    :return: The conversation with the system messages merged with the next user message
    """
    # TODO: why is this a for loop? This is called for a conversation that seems to be composed of system_prompt
    #  and prompt
    merged_conversation, last_system_message = [], None
    for i, message in enumerate(conversation):
        role, content = message["role"], message["content"]
        # If is a system message, keep it in memory to merge it with the next user message
        if role == "system":
            assert i < len(conversation) - 1, (
                f"System message is the last message while merging.\n\n {conversation}"
            )
            assert last_system_message is None, "Two consecutive system messages found"
            last_system_message = content
        # If is a user message, merge it with the previous system message as user message
        elif role == "user":
            # If there was a system message before, merge it with the user message
            if last_system_message is not None:
                new_message = last_system_message + "\n\n" + content
                merged_conversation.append({"role": "user", "content": new_message})
                last_system_message = None
            # Otherwise, just append the user message
            else:
                merged_conversation.append(message)
        # If not a system or user message, just append
        else:
            # First make sure that it is an assistant message
            assert role in ("assistant",), f"Unexpected role: {role}"
            merged_conversation.append(message)

    assert last_system_message is None, "Last message was a system message. Unexpected"

    return merged_conversation
