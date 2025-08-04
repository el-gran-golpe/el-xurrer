from typing import List
from loguru import logger

from llm.common.request_options import RequestOptions
from llm.common.constants import REASONING_MODELS, MODELS_ACCEPTING_JSON_FORMAT


def select_models(
    base_models: List[str],
    exhausted_models: List[str],
    options: RequestOptions,
    use_paid_api: bool,
) -> List[str]:
    """
    Apply filtering/prioritization to models: exhaustion, JSON constraints, forced reasoning.
    """
    models = list(base_models)
    if not use_paid_api:
        models = [m for m in models if m not in exhausted_models]

    if options.as_json:
        models = [m for m in models if m in MODELS_ACCEPTING_JSON_FORMAT]

    if options.force_reasoning:
        reasoning = [m for m in REASONING_MODELS if m in models]
        if reasoning:
            models = reasoning
        else:
            logger.warning(
                "Couldn't force a reasoning model because none available. Using {}",
                models[0] if models else "<none>",
            )

    if not models:
        raise RuntimeError("No models available after selection/filtering")

    return models
