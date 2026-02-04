def test_audience_enum_valid_values():
    """Audience should only accept valid enum values."""
    from app.schemas.posts import Audience

    assert Audience.SUBSCRIBERS == "subscribers"
    assert Audience.FOLLOWERS_AND_SUBSCRIBERS == "followers-and-subscribers"


def test_upload_failure_model():
    """UploadFailure should store filename and error."""
    from app.schemas.posts import UploadFailure

    failure = UploadFailure(filename="video.mp4", error="Upload timeout")
    assert failure.filename == "video.mp4"
    assert failure.error == "Upload timeout"


def test_create_post_response_model():
    """CreatePostResponse should include all fields."""
    from app.schemas.posts import CreatePostResponse

    response = CreatePostResponse(
        uuid="post-uuid",
        createdAt="2024-03-15T10:00:00Z",
        text="Hello world",
        audience="subscribers",
        mediaUuids=["uuid-1"],
        uploadFailures=[],
    )
    assert response.uuid == "post-uuid"
    assert response.mediaUuids == ["uuid-1"]
