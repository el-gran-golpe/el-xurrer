from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from ai_content_pipeline.config import Settings
from ai_content_pipeline.domain.types import (
    FacebookMediaStagingCredentials,
    MetaCredentials,
)
from ai_content_pipeline.integrations.meta import graph_api
from ai_content_pipeline.integrations.meta.graph_api import (
    FacebookMediaStager,
    InstagramPublisher,
    MetaPublisherError,
    MetaValidationError,
)


def _settings(**extra_values: str) -> Settings:
    return Settings(
        OPENAI_API_KEY="openai-key",
        DEEPSEEK_API_KEY="deepseek-key",
        client_id="google-client",
        client_secret="google-secret",
        folder_id="drive-folder",
        _env_file=None,
        **extra_values,
    )


def _profile(
    *,
    instagram_account_id: str = "17841400000000001",
    facebook_page_id: str = "1234567890",
    facebook_page_access_token: str = "profile-page-token",
):
    return SimpleNamespace(
        name="laura_vigne",
        meta_credentials=MetaCredentials(
            instagram_account_id=instagram_account_id,
            facebook_page_id=facebook_page_id,
            facebook_page_access_token=facebook_page_access_token,
        ),
    )


def test_meta_credentials_load_profile_page_token_fields():
    settings = _settings(
        laura_vigne_instagram_account_id="17841400000000001",
        laura_vigne_facebook_page_id="1234567890",
        laura_vigne_facebook_page_access_token="profile-page-token",
    )

    credentials = settings.get_meta_credentials("laura_vigne")

    assert credentials.instagram_account_id == "17841400000000001"
    assert credentials.facebook_page_id == "1234567890"
    assert credentials.facebook_page_access_token == "profile-page-token"


def test_meta_credentials_require_new_page_token_fields():
    settings = _settings(laura_vigne_instagram_account_id="17841400000000001")

    with pytest.raises(EnvironmentError) as error:
        settings.get_meta_credentials("laura_vigne")

    message = str(error.value)
    assert "LAURA_VIGNE_FACEBOOK_PAGE_ID" in message
    assert "LAURA_VIGNE_FACEBOOK_PAGE_ACCESS_TOKEN" in message
    assert "LAURA_VIGNE_INSTAGRAM_USER_ACCESS_TOKEN" not in message


def test_instagram_publisher_rejects_page_token_for_wrong_instagram_account(
    monkeypatch,
):
    def fake_request_json(method, url, *, params=None, **_kwargs):
        assert method == "GET"
        assert url == "https://graph.facebook.com/v25.0/1234567890"
        assert params == {
            "fields": "instagram_business_account",
            "access_token": "profile-page-token",
        }
        return {"instagram_business_account": {"id": "17841400000000002"}}

    monkeypatch.setattr(graph_api, "_request_json", fake_request_json)

    with pytest.raises(MetaValidationError) as error:
        InstagramPublisher(_profile())

    message = str(error.value)
    assert "Expected 17841400000000001" in message
    assert "got 17841400000000002" in message
    assert "profile-page-token" not in message


@pytest.mark.asyncio
async def test_media_creation_uses_facebook_graph_api_and_profile_page_token(
    monkeypatch,
    tmp_path,
):
    sync_calls = []
    async_calls = []

    def fake_request_json(method, url, *, params=None, **_kwargs):
        sync_calls.append((method, url, params))
        return {"instagram_business_account": {"id": "17841400000000001"}}

    async def fake_async_request_json(
        method, url, *, data=None, params=None, **_kwargs
    ):
        async_calls.append((method, url, data, params))
        if url.endswith("/media") and (data or {}).get("media_type") != "CAROUSEL":
            return {"id": "container-1"}
        if url.endswith("/container-1"):
            return {"status_code": "FINISHED"}
        if url.endswith("/media_publish"):
            return {"id": "published-media-1", "permalink": "https://ig/post"}
        raise AssertionError(f"Unexpected Meta request: {method} {url}")

    class FakeMediaStager:
        async def upload_photo_and_get_cdn_url(self, _img_path):
            return "https://cdn.example.test/post.jpg"

    monkeypatch.setattr(graph_api, "_request_json", fake_request_json)
    monkeypatch.setattr(graph_api, "_async_request_json", fake_async_request_json)

    publisher = InstagramPublisher(_profile())
    result = await publisher.upload_publication(
        [tmp_path / "post.jpg"],
        "caption",
        datetime(2026, 6, 4, tzinfo=timezone.utc),
        FakeMediaStager(),
    )

    assert result["id"] == "published-media-1"
    assert sync_calls == [
        (
            "GET",
            "https://graph.facebook.com/v25.0/1234567890",
            {
                "fields": "instagram_business_account",
                "access_token": "profile-page-token",
            },
        )
    ]
    assert all("graph.facebook.com" in url for _, url, _, _ in async_calls)
    assert all("graph.instagram.com" not in url for _, url, _, _ in async_calls)
    assert async_calls[0][1] == (
        "https://graph.facebook.com/v25.0/17841400000000001/media"
    )
    assert async_calls[0][2]["access_token"] == "profile-page-token"
    assert async_calls[-1][1] == (
        "https://graph.facebook.com/v25.0/17841400000000001/media_publish"
    )
    assert async_calls[-1][2]["access_token"] == "profile-page-token"


@pytest.mark.asyncio
async def test_facebook_media_stager_keeps_using_shared_staging_page_token(
    monkeypatch,
    tmp_path,
):
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"image-bytes")
    async_calls = []

    monkeypatch.setattr(
        graph_api.settings,
        "get_facebook_media_staging_credentials",
        lambda: FacebookMediaStagingCredentials(
            page_id="staging-page-id",
            page_access_token="staging-page-token",
        ),
    )

    async def fake_async_request_json(method, url, *, data=None, params=None, **kwargs):
        async_calls.append((method, url, data, params, kwargs.get("files")))
        if url.endswith("/staging-page-id/photos"):
            return {"id": "staging-photo-id"}
        if url.endswith("/staging-photo-id"):
            return {
                "images": [
                    {"source": "https://cdn.example.test/image.jpg", "width": 640}
                ]
            }
        raise AssertionError(f"Unexpected staging request: {method} {url}")

    monkeypatch.setattr(graph_api, "_async_request_json", fake_async_request_json)

    stager = FacebookMediaStager()
    cdn_url = await stager.upload_photo_and_get_cdn_url(image_path)

    assert cdn_url == "https://cdn.example.test/image.jpg"
    assert async_calls[0][2]["access_token"] == "staging-page-token"
    assert async_calls[1][3]["access_token"] == "staging-page-token"
    assert all(
        (call[2] or call[3] or {}).get("access_token") != "profile-page-token"
        for call in async_calls
    )


def test_meta_request_errors_redact_access_tokens(monkeypatch):
    class FakeResponse:
        text = '{"error": {"message": "Token profile-page-token is invalid"}}'

        def raise_for_status(self):
            error = requests.exceptions.HTTPError(
                "400 Client Error for url: "
                "https://graph.facebook.com/v25.0/123"
                "?access_token=profile-page-token"
            )
            error.response = self
            raise error

    def fake_get(url, *, params=None, timeout=30):
        assert params == {"access_token": "profile-page-token"}
        assert timeout == 30
        return FakeResponse()

    monkeypatch.setattr(graph_api.requests, "get", fake_get)

    with pytest.raises(MetaPublisherError) as error:
        graph_api._request_json(
            "GET",
            "https://graph.facebook.com/v25.0/123",
            params={"access_token": "profile-page-token"},
        )

    message = str(error.value)
    assert "profile-page-token" not in message
    assert "<redacted>" in message
