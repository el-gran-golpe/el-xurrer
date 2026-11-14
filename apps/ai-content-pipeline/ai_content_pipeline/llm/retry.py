"""
Shared retry loop for "generate -> parse/validate -> maybe fail over" against
`ModelRouter`. Extracted from `PlanningManager._generate_valid_plan` so
`StoryManager` (arc/chapter generation) reuses the exact same policy instead
of a second copy: try up to `max_attempts` times, excluding the model that
produced the last invalid reply before each retry, and routing the final
attempt to the paid fallback only (`ModelRouter.use_fallback_only`) because
giving up means content that never gets written at all.

Callers own what "invalid" means for their payload: `parse` raises
`ValueError` (this also covers `json.JSONDecodeError` and pydantic's
`ValidationError`, both `ValueError` subclasses) for anything that should
trigger a retry rather than propagate immediately.
"""

from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

from loguru import logger

from ai_content_pipeline.llm.base_llm import BaseLLM
from ai_content_pipeline.llm.error_handlers.exceptions import NoCandidateModelsError

T = TypeVar("T")


class GenerationFailedError(ValueError):
    """
    Raised when every attempt was invalid. Subclasses `ValueError` so a
    caller that only catches `ValueError` (or asserts with
    `pytest.raises(ValueError, match=...)`) keeps working; `invalid_attempts`
    carries every attempt's error message for callers that want to record
    more than just the last one.
    """

    def __init__(self, message: str, invalid_attempts: list[str]):
        super().__init__(message)
        self.invalid_attempts = invalid_attempts


@dataclass(frozen=True)
class RetryOutcome(Generic[T]):
    """What `generate_with_retries` actually did to produce its value."""

    value: T
    attempt: int
    max_attempts: int
    model: str | None
    used_fallback: bool
    invalid_attempts: list[str] = field(default_factory=list)


def generate_with_retries(
    llm: BaseLLM,
    parse: Callable[[dict], T],
    *,
    max_attempts: int,
    context: str,
) -> RetryOutcome[T]:
    """
    Runs `llm.generate_dict_from_prompts()` then `parse(reply)` up to
    `max_attempts` times. `parse` is where a caller turns the raw dict into
    its own validated value (e.g. `WeekPlan`/`Arc`/`Chapter`) and raises
    `ValueError` for anything invalid — a non-JSON reply, a pydantic
    rejection, or a domain rule like "wrong day count".

    `llm.model_router.get_response` (called inside `generate_dict_from_prompts`)
    can also raise `NoCandidateModelsError` instead of returning a reply at
    all, when every candidate model is currently unavailable (e.g. excluded
    by a previous attempt, or censored for a sensitive prompt). That is
    treated exactly like an invalid reply — one more failed attempt that
    retries — rather than aborting the loop, so it still reaches the
    forced-fallback last attempt below.

    On the last attempt (only when there is more than one attempt),
    `llm.model_router.use_fallback_only()` routes it straight to the paid
    fallback. After every failed attempt, the model that produced that
    attempt's last prompt reply (`llm.model_router.last_model`) is excluded
    from the router instance so the next attempt cannot land on it again —
    `ModelRouter.exclude_model` itself is a no-op for the paid fallback
    provider, so this never strands a later attempt with zero candidates.

    `context` is a short human description (e.g. "plan for haru meta week
    2026-10-12") used only in log lines.
    """
    last_error: ValueError | NoCandidateModelsError | None = None
    invalid_attempts: list[str] = []
    used_fallback = False

    for attempt in range(1, max_attempts + 1):
        if attempt == max_attempts and attempt > 1:
            llm.model_router.use_fallback_only()
            used_fallback = True
            logger.warning("Last attempt for {}: using the paid fallback only", context)
        try:
            value = parse(llm.generate_dict_from_prompts())
            last_model = llm.model_router.last_model
            model_label = f"{last_model[0]}/{last_model[1]}" if last_model else None
            return RetryOutcome(
                value=value,
                attempt=attempt,
                max_attempts=max_attempts,
                model=model_label,
                used_fallback=used_fallback,
                invalid_attempts=list(invalid_attempts),
            )
        except (ValueError, NoCandidateModelsError) as e:
            last_error = e
            invalid_attempts.append(str(e))
            last_model = llm.model_router.last_model
            if last_model is not None:
                provider_id, identifier = last_model
                llm.model_router.exclude_model(provider_id, identifier)
                logger.warning(
                    "Excluding model {} ({}) for the remaining attempts after "
                    "an invalid {}",
                    identifier,
                    provider_id,
                    context,
                )
            logger.warning(
                "Attempt {}/{} for {} was invalid: {}; retrying",
                attempt,
                max_attempts,
                context,
                e,
            )

    assert last_error is not None  # the loop always sets it before falling through
    raise GenerationFailedError(str(last_error), invalid_attempts)
