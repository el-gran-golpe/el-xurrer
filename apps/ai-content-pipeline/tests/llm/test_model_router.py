from datetime import datetime, timezone
from typing import Any

from ai_content_pipeline.llm.error_handlers.exceptions import RateLimitError
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
