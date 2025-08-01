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
