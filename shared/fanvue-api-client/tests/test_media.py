from fanvue_api_client.media import get_media_type


def test_get_media_type_maps_common_content_types() -> None:
    assert get_media_type("image/jpeg") == "image"
    assert get_media_type("video/mp4") == "video"
    assert get_media_type("audio/mpeg") == "audio"
    assert get_media_type("application/pdf") == "document"
