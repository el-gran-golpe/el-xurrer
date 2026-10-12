from datetime import datetime, timezone
from typing import Any

import pytest

from ai_content_pipeline.llm.error_handlers.exceptions import (
    NoCandidateModelsError,
    RateLimitError,
)
from ai_content_pipeline.llm.routing.classification.model_cache import ModelCache
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.llm.routing.providers.base import LLMProvider
from ai_content_pipeline.domain.types import PromptItem

NOW = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)


def _prompt_item(output_as_json: bool = False) -> PromptItem:
    return PromptItem(
        system_prompt="You are a helpful assistant for {day}.",
        prompt="Write a short answer.",
        cache_key="answer",
        output_as_json=output_as_json,
        is_sensitive_content=False,
    )


class _AlwaysRateLimitedProvider(LLMProvider):
    """A free provider whose only model always fails with a long cooldown,
    so the router must exhaust it and fail over to the next group."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.is_paid = False

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [{"id": "always-fails", "limits": {}}]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        raise RateLimitError(cooldown_seconds=9999)


class _SucceedingProvider(LLMProvider):
    """A provider that always answers successfully."""

    def __init__(self, provider_id: str, is_paid: bool) -> None:
        self.provider_id = provider_id
        self.is_paid = is_paid

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [{"id": "deepseek-chat", "limits": {}}]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        return f"reply from {self.provider_id}"


class _UnreachableProvider(LLMProvider):
    """A provider with an empty catalog: the router must never try to call it."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.is_paid = True

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return []

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        raise AssertionError(f"{self.provider_id} should never be called")


class _KeyAwareProvider(LLMProvider):
    """A free provider whose single model fails only for one specific API key,
    so router behavior can be observed per key."""

    def __init__(self, provider_id: str, failing_key: str) -> None:
        self.provider_id = provider_id
        self.is_paid = False
        self.failing_key = failing_key
        self.calls: list[str] = []

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [{"id": "m1", "limits": {}}]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        self.calls.append(api_key)
        if api_key == self.failing_key:
            raise RateLimitError(cooldown_seconds=9999)
        return f"reply from {api_key}"


class _MultiModelProvider(LLMProvider):
    """A free provider with two same-ELO models (model-a ranks first by
    catalog/insertion order), both of which succeed — lets a test observe
    which model answered and verify that excluding one routes to the other."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.is_paid = False
        self.calls: list[str] = []

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [
            {"id": "model-a", "limits": {}},
            {"id": "model-b", "limits": {}},
        ]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        self.calls.append(model_id)
        return f"reply from {model_id}"


class _JsonMisbehavingProvider(LLMProvider):
    """A free provider whose first model claims success but returns malformed
    JSON when JSON mode is requested; its second model behaves correctly."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.is_paid = False

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [
            {"id": "bad-json-model", "limits": {}},
            {"id": "good-json-model", "limits": {}},
        ]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        if model_id == "bad-json-model":
            return '{"hashtags": #not_quoted}'
        return '{"ok": true}'


def test_invalid_json_reply_fails_over_and_marks_model_unsupported(tmp_path):
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    provider = _JsonMisbehavingProvider("openrouter")

    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[provider],
        deepseek_provider=_UnreachableProvider("deepseek"),
    )
    router.initialize_model_classifiers(models_to_scan=None)

    reply = router.get_response(_prompt_item(output_as_json=True))

    assert reply == '{"ok": true}'
    classifier = router.classifiers_for("openrouter")[0]
    assert classifier.models_catalog["bad-json-model"].supports_json_format is False
    assert classifier.models_catalog["good-json-model"].supports_json_format is True


def test_deepseek_fallback_used_only_when_free_provider_fully_exhausted(tmp_path):
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    free_provider = _AlwaysRateLimitedProvider("openrouter")
    deepseek_provider = _SucceedingProvider("deepseek", is_paid=True)

    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[free_provider],
        deepseek_provider=deepseek_provider,
    )
    router.initialize_model_classifiers(models_to_scan=None)

    reply = router.get_response(_prompt_item())

    assert reply == "reply from deepseek"


def test_multi_key_rotation_advances_cursor_on_exhaustion(tmp_path):
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    provider = _KeyAwareProvider("openrouter", failing_key="key1")

    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1", "key2"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[provider],
        deepseek_provider=_UnreachableProvider("deepseek"),
    )
    router.initialize_model_classifiers(models_to_scan=None)

    reply = router.get_response(_prompt_item())
    assert reply == "reply from key2"
    assert router._key_cursor["openrouter"] == 1

    # Subsequent calls should start from the cursor (key2), not retry key1 first.
    reply_again = router.get_response(_prompt_item())
    assert reply_again == "reply from key2"
    assert provider.calls == ["key1", "key2", "key2"]


def _router_with_multi_model_provider(
    tmp_path,
) -> tuple[ModelRouter, _MultiModelProvider]:
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    provider = _MultiModelProvider("openrouter")
    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[provider],
        deepseek_provider=_UnreachableProvider("deepseek"),
    )
    router.initialize_model_classifiers(models_to_scan=None)
    return router, provider


def test_last_model_records_the_model_that_answered(tmp_path):
    router, _ = _router_with_multi_model_provider(tmp_path)

    router.get_response(_prompt_item())

    assert router.last_model == ("openrouter", "model-a")


def test_excluded_model_is_skipped_in_favor_of_the_next_candidate(tmp_path):
    router, provider = _router_with_multi_model_provider(tmp_path)

    router.exclude_model("openrouter", "model-a")
    reply = router.get_response(_prompt_item())

    assert reply == "reply from model-b"
    assert provider.calls == ["model-b"]
    assert router.last_model == ("openrouter", "model-b")


def test_excluding_every_candidate_falls_over_to_the_next_provider_group(tmp_path):
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    free_provider = _MultiModelProvider("openrouter")
    deepseek_provider = _SucceedingProvider("deepseek", is_paid=True)
    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[free_provider],
        deepseek_provider=deepseek_provider,
    )
    router.initialize_model_classifiers(models_to_scan=None)
    router.exclude_model("openrouter", "model-a")
    router.exclude_model("openrouter", "model-b")

    reply = router.get_response(_prompt_item())

    assert reply == "reply from deepseek"
    assert free_provider.calls == []


def _router_with_free_and_deepseek(tmp_path):
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    free_provider = _MultiModelProvider("openrouter")
    deepseek_provider = _SucceedingProvider("deepseek", is_paid=True)
    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[free_provider],
        deepseek_provider=deepseek_provider,
    )
    router.initialize_model_classifiers(models_to_scan=None)
    return router, free_provider


def test_fallback_only_skips_the_free_providers_even_when_they_work(tmp_path):
    router, free_provider = _router_with_free_and_deepseek(tmp_path)

    router.use_fallback_only()
    reply = router.get_response(_prompt_item())

    assert reply == "reply from deepseek"
    assert free_provider.calls == []
    assert router.last_model == ("deepseek", "deepseek-chat")


def test_fallback_only_lifts_an_earlier_exclusion_of_the_fallback_model(tmp_path):
    router, _ = _router_with_free_and_deepseek(tmp_path)
    router.exclude_model("deepseek", "deepseek-chat")

    router.use_fallback_only()

    assert router.get_response(_prompt_item()) == "reply from deepseek"


def test_excluding_the_fallback_model_is_a_no_op(tmp_path):
    """
    The paid fallback is the last resort: excluding it can only make a
    retry loop worse (it may be the only candidate left, e.g. every free
    model is censored for a sensitive prompt), so `exclude_model` ignores
    pairs whose provider is the fallback group's provider.
    """
    router, _ = _router_with_free_and_deepseek(tmp_path)

    router.exclude_model("deepseek", "deepseek-chat")

    assert ("deepseek", "deepseek-chat") not in router._excluded


def test_excluding_the_fallback_model_leaves_it_usable_as_the_only_candidate(tmp_path):
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    free_provider = _UnreachableProvider("openrouter")
    deepseek_provider = _SucceedingProvider("deepseek", is_paid=True)
    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[free_provider],
        deepseek_provider=deepseek_provider,
    )
    router.initialize_model_classifiers(models_to_scan=None)

    router.exclude_model("deepseek", "deepseek-chat")

    assert router.get_response(_prompt_item()) == "reply from deepseek"


def test_get_response_raises_no_candidate_models_error_when_everything_is_exhausted(
    tmp_path,
):
    """
    When every candidate everywhere is filtered out (here: quota-exhausted
    with no recovery, the same "zero candidates, no request ever made"
    shape as excluding every model) but at least one provider group had a
    configured API key, `get_response` must raise the dedicated
    `NoCandidateModelsError` rather than the generic "not configured at
    all" `RuntimeError` — `generate_with_retries` relies on this to keep
    retrying instead of treating it as a hard failure.
    """
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    free_provider = _AlwaysRateLimitedProvider("openrouter")
    deepseek_provider = _AlwaysRateLimitedProvider("deepseek")
    router = ModelRouter(
        free_provider_keys={"openrouter": ["key1"]},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[free_provider],
        deepseek_provider=deepseek_provider,
    )
    router.initialize_model_classifiers(models_to_scan=None)

    # First call: both groups' only model gets rate-limited and marked
    # exhausted (cooldown far beyond the fixed test clock).
    with pytest.raises(RateLimitError):
        router.get_response(_prompt_item())

    # Second call: both models are still exhausted and filtered out before
    # any request is made anywhere, so there is no underlying error to
    # re-raise — this is the "configured but nothing eligible" case.
    with pytest.raises(NoCandidateModelsError):
        router.get_response(_prompt_item())


def test_get_response_raises_plain_runtime_error_when_no_classifiers_exist_anywhere(
    tmp_path,
):
    """
    The "not configured at all" case stays a plain `RuntimeError`, distinct
    from `NoCandidateModelsError` — `ModelRouter.__init__` always creates
    one DeepSeek classifier even with an empty key, so this manipulates
    `classifier_groups` directly afterward to exercise the branch.
    """
    cache = ModelCache(cache_dir=tmp_path, now=lambda: NOW)
    router = ModelRouter(
        free_provider_keys={"openrouter": []},
        deepseek_api_key="deepseek-key",
        model_cache=cache,
        free_providers=[_UnreachableProvider("openrouter")],
        deepseek_provider=_UnreachableProvider("deepseek"),
    )
    router.classifier_groups = [
        (provider_id, []) for provider_id, _ in router.classifier_groups
    ]
    router.initialize_model_classifiers(models_to_scan=None)

    with pytest.raises(RuntimeError) as excinfo:
        router.get_response(_prompt_item())

    assert not isinstance(excinfo.value, NoCandidateModelsError)


class _ScriptedDeepSeek(LLMProvider):
    """The paid fallback, answering each call with the next scripted reply."""

    def __init__(self, replies: list[str]) -> None:
        self.provider_id = "deepseek"
        self.is_paid = True
        self.replies = list(replies)

    def fetch_catalog(self, api_key: str) -> list[dict[str, Any]]:
        return [{"id": "deepseek-chat", "limits": {}}]

    def chat_completion(self, api_key, model_id, conversation, output_as_json) -> str:
        return self.replies.pop(0)


def _router_with_only_deepseek(tmp_path, deepseek: LLMProvider) -> ModelRouter:
    router = ModelRouter(
        free_provider_keys={},
        deepseek_api_key="deepseek-key",
        model_cache=ModelCache(cache_dir=tmp_path, now=lambda: NOW),
        free_providers=[_UnreachableProvider("openrouter")],
        deepseek_provider=deepseek,
    )
    router.initialize_model_classifiers(models_to_scan=None)
    return router


def test_invalid_json_from_the_fallback_does_not_lock_it_out_of_json_prompts(
    tmp_path,
):
    """
    Real run: one malformed JSON reply from deepseek-chat marked it "no JSON"
    in the on-disk cache for 24h, and since it was the only candidate for
    sensitive prompts, every Fanvue plan failed until the cache expired.
    """
    deepseek = _ScriptedDeepSeek(['{"broken": ', '{"ok": true}'])
    router = _router_with_only_deepseek(tmp_path, deepseek)

    with pytest.raises(Exception):
        router.get_response(_prompt_item(output_as_json=True))

    # A fresh router reading the same cache still offers the fallback.
    router = _router_with_only_deepseek(tmp_path, deepseek)
    assert router.get_response(_prompt_item(output_as_json=True)) == '{"ok": true}'


def test_the_fallback_is_offered_for_json_even_if_the_cache_says_it_cannot(
    tmp_path,
):
    deepseek = _ScriptedDeepSeek(['{"ok": true}'])
    router = _router_with_only_deepseek(tmp_path, deepseek)
    [classifier] = router.classifiers_for("deepseek")
    [model] = classifier.get_ranked_models(_prompt_item())
    classifier.mark_model_json_support(model, False)

    assert router.get_response(_prompt_item(output_as_json=True)) == '{"ok": true}'
