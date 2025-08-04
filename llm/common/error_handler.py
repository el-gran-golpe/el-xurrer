from typing import Any, Iterable
from azure.core.exceptions import HttpResponseError
from openai import APIStatusError

from llm.common.request_options import RequestOptions


def handle_api_error(
    e: Exception,
    conversation: list[dict],
    preferred_models: list[str],
    exhausted_models: list[str],
    use_paid_api: bool,
    options: RequestOptions,
    stream_response: bool,
    get_stream_callable: Any,
) -> Iterable[Any]:
    if isinstance(e, APIStatusError):
        error_code, error_message = e.code, e.message
    elif isinstance(e, HttpResponseError):
        error_code = e.error.code if e.error and e.error.code is not None else str(e)
        error_message = (
            e.error.message if e.error and e.error.message is not None else str(e)
        )
    else:
        raise e

    def retry_with_paid():
        return get_stream_callable(
            conversation=conversation,
            preferred_models=preferred_models,
            use_paid_api=True,
            options=options,
            stream_response=stream_response,
        )

    def retry_next_model(current_models: list[str]):
        next_models = current_models[1:]
        return get_stream_callable(
            conversation=conversation,
            preferred_models=next_models,
            use_paid_api=use_paid_api,
            options=options,
            stream_response=stream_response,
        )

    def handle_rate_limit():
        exhausted_models.append(preferred_models[0])
        if len(preferred_models) == 1 and not use_paid_api:
            return retry_with_paid()
        else:
            return retry_next_model(preferred_models)

    handlers = {
        "tokens_limit_reached": lambda: retry_with_paid(),
        "RateLimitReached": handle_rate_limit,
        "content_filter": lambda: (
            retry_next_model(preferred_models)
            if len(preferred_models) > 1
            else (_ for _ in ()).throw(
                RuntimeError("No more models to try after content filter")
            )
        ),
        "unauthorized": lambda: (_ for _ in ()).throw(
            PermissionError(f"Unauthorized: {error_message}")
        ),
    }

    if error_code in handlers:
        return handlers[error_code]()
    raise NotImplementedError(f"Error: {error_code} - {error_message}")
