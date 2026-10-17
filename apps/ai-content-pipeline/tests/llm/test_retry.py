"""
Tests for `llm/retry.py:generate_with_retries`, focused on the bug where a
retry could be left with zero candidates and abort the loop entirely
instead of reaching the forced-fallback last attempt (see root `AGENTS.md`
Model Router Behavior and the arc/chapter Jobs DAG bullets for context: every
current free OpenRouter model counts as censored for `is_sensitive_content`
prompts like the arc, chapter, and Fanvue plan, so DeepSeek is the only
candidate — excluding it after one invalid reply used to strand the retry).
"""

from datetime import datetime, timezone
from typing import Any

from ai_content_pipeline.domain.types import PromptItem
from ai_content_pipeline.llm.error_handlers.exceptions import NoCandidateModelsError
from ai_content_pipeline.llm.retry import generate_with_retries
from ai_content_pipeline.llm.routing.classification.model_cache import ModelCache
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.llm.routing.providers.base import LLMProvider

NOW = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)


# ---------------- a minimal fake standing in for BaseLLM ----------------


class _FakeRouter:
    """Just enough of `ModelRouter`'s interface for `generate_with_retries`
    to drive, without a real provider stack."""

    def __init__(self, last_model: tuple[str, str] | None = ("openrouter", "m")):
        self.last_model = last_model
        self.excluded: list[tuple[str, str]] = []
        self.fallback_only_calls = 0

    def exclude_model(self, provider_id: str, identifier: str) -> None:
        self.excluded.append((provider_id, identifier))

    def use_fallback_only(self) -> None:
        self.fallback_only_calls += 1


class _FakeLLM:
    """Replays `replies` in order, one per `generate_dict_from_prompts()`
    call; an entry that is an `Exception` instance is raised instead of
    returned, so a test can script "no candidates, then success" directly
    without a real `ModelRouter`."""

    def __init__(self, router: _FakeRouter, replies: list):
        self.model_router = router
        self._replies = list(replies)
        self.call_count = 0

    def generate_dict_from_prompts(self):
        self.call_count += 1
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _identity(reply):
    return reply


def test_succeeds_on_the_first_try_without_excluding_anything():
    router = _FakeRouter()
    llm = _FakeLLM(router, ["ok"])

    outcome = generate_with_retries(llm, _identity, max_attempts=5, context="ctx")

    assert outcome.value == "ok"
    assert outcome.attempt == 1
    assert outcome.used_fallback is False
    assert router.excluded == []


def test_no_candidate_models_error_is_treated_as_an_invalid_attempt_and_retries():
    """
    Before the fix, `ModelRouter.get_response` raised a bare `RuntimeError`
    when every candidate was excluded, which `generate_with_retries` (only
    catching `ValueError`) let propagate immediately — killing the retry
    loop on attempt 2 instead of reaching the forced-fallback last attempt.
    `NoCandidateModelsError` must be caught the same way an invalid reply
    is: recorded and retried.
    """
    router = _FakeRouter()
    llm = _FakeLLM(router, [NoCandidateModelsError("nothing eligible right now"), "ok"])

    outcome = generate_with_retries(llm, _identity, max_attempts=5, context="ctx")

    assert outcome.value == "ok"
    assert outcome.attempt == 2
    assert outcome.invalid_attempts == ["nothing eligible right now"]
    assert outcome.used_fallback is False
    assert router.fallback_only_calls == 0


def test_no_candidate_models_error_on_every_attempt_still_reaches_the_fallback_attempt():
    router = _FakeRouter()
    llm = _FakeLLM(
        router,
        [
            NoCandidateModelsError("none 1"),
            NoCandidateModelsError("none 2"),
            "ok on the forced-fallback attempt",
        ],
    )

    outcome = generate_with_retries(llm, _identity, max_attempts=3, context="ctx")

    assert outcome.value == "ok on the forced-fallback attempt"
    assert outcome.attempt == 3
    assert outcome.used_fallback is True
    assert router.fallback_only_calls == 1


# ---------------- real ModelRouter integration ----------------
#
# Reproduces the actual reported bug: a sensitive-content prompt whose only
# free-provider model is censored by the name-based heuristic
# (`UNCENSORED_MODEL_GUESSES` only matches "deepseek"/"grok" — unchanged by
# this fix), so DeepSeek is the only candidate. An invalid first reply used
# to get DeepSeek excluded, leaving attempt 2 with zero candidates anywhere.


class _AlwaysCensoredFreeProvider(LLMProvider):
    """Stands in for every current free OpenRouter model under a sensitive
    prompt: its model id contains neither "deepseek" nor "grok", so
    `LLMProvider.is_model_censored` (unchanged) marks it censored and the
    classifier filters it out before any request is made."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.is_paid = False

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [{"id": "censored-model", "limits": {}}]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        raise AssertionError(
            "a censored model must never be called for a sensitive prompt"
        )


class _SequencedDeepSeekProvider(LLMProvider):
    """The paid fallback, returning each reply in order — one per call."""

    def __init__(self, provider_id: str, replies: list[str]) -> None:
        self.provider_id = provider_id
        self.is_paid = True
        self._replies = list(replies)
        self.calls = 0

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [{"id": "deepseek-chat", "limits": {}}]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        reply = self._replies[self.calls]
        self.calls += 1
        return reply


_SENSITIVE_PROMPT_ITEM = PromptItem(
    prompt="write something",
    cache_key="k",
    system_prompt="You write for {day}.",
    output_as_json=False,
    is_sensitive_content=True,
)


class _RouterBackedLLM:
    """Bridges a real `ModelRouter` to the `generate_with_retries` contract
    without pulling in the full `BaseLLM`/prompt-preparation machinery."""

    def __init__(self, router: ModelRouter):
        self.model_router = router

    def generate_dict_from_prompts(self) -> str:
        return self.model_router.get_response(_SENSITIVE_PROMPT_ITEM)


def _reject_bad_reply(reply: str) -> str:
    if reply == "bad reply":
        raise ValueError("invalid reply")
    return reply


def test_sensitive_prompt_with_only_deepseek_available_retries_onto_deepseek_again(
    tmp_path,
):
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    free_provider = _AlwaysCensoredFreeProvider("openrouter")
    deepseek_provider = _SequencedDeepSeekProvider(
        "deepseek", ["bad reply", "good reply"]
    )
    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[free_provider],
        deepseek_provider=deepseek_provider,
    )
    router.initialize_model_classifiers(models_to_scan=None)
    llm = _RouterBackedLLM(router)

    outcome = generate_with_retries(
        llm, _reject_bad_reply, max_attempts=5, context="sensitive test"
    )

    assert outcome.value == "good reply"
    # Landed on attempt 2 of 5 — proof the fallback model was never actually
    # excluded, so the retry found it immediately rather than needing all 5
    # attempts and the forced-fallback branch to get back to it.
    assert outcome.attempt == 2
    assert outcome.used_fallback is False
    assert deepseek_provider.calls == 2
    assert ("deepseek", "deepseek-chat") not in router._excluded
