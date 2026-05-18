from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from requests import HTTPError

from ai_content_pipeline.llm.error_handlers.exceptions import RateLimitError
from ai_content_pipeline.llm.routing.classification.llm_model import LLMModel
from ai_content_pipeline.llm.routing.classification.model_cache import GitHubModelsCache
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.domain.types import PromptItem


NOW = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)


def _catalog(model_id: str = "openai/gpt-4o-mini") -> list[dict[str, Any]]:
    return [
        {
            "id": model_id,
            "limits": {
                "max_input_tokens": 8192,
                "max_output_tokens": 2048,
            },
        }
    ]


def _prompt_item(output_as_json: bool) -> PromptItem:
    return PromptItem(
        system_prompt="You are a helpful assistant for {day}.",
        prompt="Write a short answer.",
        cache_key="answer",
        output_as_json=output_as_json,
        is_sensitive_content=False,
    )


class _Response:
    def __init__(self, payload: Any):
        self._payload = payload
        self.status_code = 200
        self.reason = "OK"
        self.headers: dict[str, str] = {}
        self.text = ""

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_cached_catalog_initialization_avoids_network_and_probes(tmp_path, monkeypatch):
    cache = GitHubModelsCache(cache_dir=tmp_path, now=lambda: NOW)
    cache.save_catalog(_catalog(), fetched_at=NOW)

    def fail_network(*args, **kwargs):
        raise AssertionError("cached initialization must not call the network")

    monkeypatch.setattr("requests.get", fail_network)
    monkeypatch.setattr("requests.post", fail_network)

    router = ModelRouter(["github-key"], "deepseek-key", model_cache=cache)
    router.initialize_model_classifiers(models_to_scan=None)

    classifier = router.github_classifiers[0]
    model = classifier.models_catalog["openai/gpt-4o-mini"]
    assert model.max_input_tokens == 8192
    assert model.max_output_tokens == 2048
    assert model.supports_json_format is None


def test_expired_catalog_refreshes_once_and_does_not_probe_models(
    tmp_path, monkeypatch
):
    cache = GitHubModelsCache(cache_dir=tmp_path, now=lambda: NOW)
    cache.save_catalog(_catalog("old/model"), fetched_at=NOW - timedelta(hours=25))
    calls = {"catalog": 0}

    def catalog_get(*args, **kwargs):
        calls["catalog"] += 1
        return _Response(_catalog("new/model"))

    def fail_probe(*args, **kwargs):
        raise AssertionError("catalog refresh must not probe chat completions")

    monkeypatch.setattr("requests.get", catalog_get)
    monkeypatch.setattr("requests.post", fail_probe)

    router = ModelRouter(["github-key"], "deepseek-key", model_cache=cache)
    router.initialize_model_classifiers(models_to_scan=None)

    assert calls["catalog"] == 1
    assert list(router.github_classifiers[0].models_catalog) == ["new/model"]


def test_force_refresh_ignores_fresh_catalog(tmp_path, monkeypatch):
    cache = GitHubModelsCache(cache_dir=tmp_path, now=lambda: NOW)
    cache.save_catalog(_catalog("old/model"), fetched_at=NOW)

    monkeypatch.setattr(
        "requests.get", lambda *a, **k: _Response(_catalog("new/model"))
    )
    monkeypatch.setattr(
        "requests.post",
        lambda *a, **k: pytest.fail("force refresh must not probe models"),
    )

    router = ModelRouter(["github-key"], "deepseek-key", model_cache=cache)
    router.initialize_model_classifiers(models_to_scan=None, force_refresh=True)

    assert list(router.github_classifiers[0].models_catalog) == ["new/model"]


def test_rate_limit_exhaustion_is_persisted_by_key_fingerprint(tmp_path, monkeypatch):
    cache = GitHubModelsCache(cache_dir=tmp_path, now=lambda: NOW)
    cache.save_catalog(_catalog(), fetched_at=NOW)
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("cache expected"))
    monkeypatch.setattr("requests.post", lambda *a, **k: pytest.fail("cache expected"))

    router = ModelRouter(["github-key"], "deepseek-key", model_cache=cache)
    router.initialize_model_classifiers(models_to_scan=None)
    classifier = router.github_classifiers[0]
    model = classifier.models_catalog["openai/gpt-4o-mini"]

    def raise_rate_limit(self, conversation, output_as_json):
        raise RateLimitError(cooldown_seconds=120)

    monkeypatch.setattr(LLMModel, "get_model_response", raise_rate_limit)

    router._try_candidates_for_classifier(classifier, [model], [], False)

    next_router = ModelRouter(["github-key"], "deepseek-key", model_cache=cache)
    next_router.initialize_model_classifiers(models_to_scan=None)
    persisted = next_router.github_classifiers[0].models_catalog["openai/gpt-4o-mini"]

    assert persisted.is_quota_exhausted is True
    assert persisted.exhausted_until_datetime == NOW + timedelta(seconds=120)


def test_json_bad_request_marks_model_unsupported_across_github_keys(
    tmp_path, monkeypatch
):
    cache = GitHubModelsCache(cache_dir=tmp_path, now=lambda: NOW)
    cache.save_catalog(_catalog(), fetched_at=NOW)
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("cache expected"))
    monkeypatch.setattr("requests.post", lambda *a, **k: pytest.fail("cache expected"))

    router = ModelRouter(["github-key"], "deepseek-key", model_cache=cache)
    router.initialize_model_classifiers(models_to_scan=None)
    classifier = router.github_classifiers[0]
    model = classifier.models_catalog["openai/gpt-4o-mini"]

    def raise_bad_request(self, conversation, output_as_json):
        raise HTTPError("Bad request for model openai/gpt-4o-mini")

    monkeypatch.setattr(LLMModel, "get_model_response", raise_bad_request)

    router._try_candidates_for_classifier(classifier, [model], [], True)

    next_router = ModelRouter(["another-github-key"], "deepseek-key", model_cache=cache)
    next_router.initialize_model_classifiers(models_to_scan=None)
    next_classifier = next_router.github_classifiers[0]

    assert (
        next_classifier.models_catalog["openai/gpt-4o-mini"].supports_json_format
        is False
    )
    assert next_classifier.get_ranked_models(_prompt_item(output_as_json=True)) == []
