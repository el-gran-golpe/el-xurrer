from typing import Iterable, Union, Any, cast

from azure.ai.inference.models import StreamingChatCompletionsUpdate, ChatCompletions
from openai.types.chat import ChatCompletionChunk, ChatCompletion

from llm.common.clients import get_llm_client
from llm.common.conversation_format import (
    conversation_to_openai_format,
    conversation_to_azure_format,
    merge_system_and_user_messages,
)
from llm.constants import (
    OPENAI,
    AZURE,
    MODELS_NOT_ACCEPTING_STREAM,
    MODELS_NOT_ACCEPTING_SYSTEM_ROLE,
    MODEL_BY_BACKEND,
)

ResponseChunk = Union[
    StreamingChatCompletionsUpdate,
    ChatCompletions,
    ChatCompletionChunk,
    ChatCompletion,
]


def invoke_backend(
    conversation: list[dict],
    model: str,
    stream_response: bool,
    additional_params: dict[str, Any],
    use_paid_api: bool,
    github_api_keys: list[str],
    openai_api_keys: list[str],
) -> Iterable[ResponseChunk]:
    
    # TODO: Implement this inside Model Router
    if model in MODELS_NOT_ACCEPTING_SYSTEM_ROLE:
        conversation = merge_system_and_user_messages(conversation=conversation)

    client, active_backend = get_llm_client(
        github_api_keys=github_api_keys,
        openai_api_keys=openai_api_keys,
        model=model,
        free_api=not use_paid_api,
        MODEL_BY_BACKEND=MODEL_BY_BACKEND,
        OPENAI=OPENAI,
        AZURE=AZURE,
    )

    effective_stream = stream_response and model not in MODELS_NOT_ACCEPTING_STREAM

    if active_backend == AZURE:
        raw = client.complete(
            messages=conversation_to_azure_format(conversation=conversation),
            model=model,
            stream=effective_stream,
            **additional_params,
        )
    elif active_backend == OPENAI:
        if not hasattr(client, "chat"):
            raise ValueError(f"Client is not OpenAI-compatible: {client}")
        raw = client.chat.completions.create(
            messages=conversation_to_openai_format(conversation=conversation),
            model=model,
            stream=effective_stream,
            **additional_params,
        )
    else:
        raise NotImplementedError(f"Backend not implemented: {active_backend}")

    if not effective_stream and not isinstance(raw, Iterable):
        return [raw]  # type: ignore
    return cast(Iterable[ResponseChunk], raw)
