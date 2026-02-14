import pytest

from automation.fanvue_client.fanvue_api_publisher import FanvueAPIPublisher
from main_components.common.types import Platform, PlatformInfo, Profile


@pytest.fixture
def mock_profile(tmp_path):
    """Create a mock profile for testing."""
    # Create temporary directories for validation
    inputs_path = tmp_path / "resources" / "test_profile" / "fanvue" / "inputs"
    outputs_path = tmp_path / "resources" / "test_profile" / "fanvue" / "outputs"
    inputs_path.mkdir(parents=True)
    outputs_path.mkdir(parents=True)

    platform_info = {
        Platform.FANVUE: PlatformInfo(
            name=Platform.FANVUE,
            inputs_path=inputs_path,
            outputs_path=outputs_path,
            lang="en",
        )
    }
    return Profile(name="test_profile", platform_info=platform_info)


def test_publisher_initialization(mock_profile):
    """Test that FanvueAPIPublisher can be initialized."""
    publisher = FanvueAPIPublisher(mock_profile)

    assert publisher.profile == mock_profile
    assert publisher.token_manager is not None
    assert publisher.token_manager.profile_name == "test_profile"


@pytest.mark.asyncio
async def test_post_publication_uploads_and_creates_post(
    mock_profile, tmp_path, monkeypatch
):
    """Test that post_publication uploads media and creates post."""
    # Create test image file
    test_image = tmp_path / "test.jpg"
    test_image.write_text("fake image data")

    # Mock token manager
    async def mock_ensure_valid_token():
        return "test_access_token"

    # Mock upload_media
    async def mock_upload_media(file_path, access_token):
        return "test_media_uuid"

    # Mock create_post
    async def mock_create_post(text, media_uuids, audience, publish_at, access_token):
        return {
            "id": "test_post_id",
            "text": text,
            "mediaUuids": media_uuids,
        }

    publisher = FanvueAPIPublisher(mock_profile)

    # Monkeypatch methods
    monkeypatch.setattr(
        publisher.token_manager, "ensure_valid_token", mock_ensure_valid_token
    )

    import automation.fanvue_client.fanvue_api_publisher as pub_module

    monkeypatch.setattr(pub_module, "upload_media", mock_upload_media)
    monkeypatch.setattr(pub_module, "create_post", mock_create_post)

    # Call post_publication
    result = await publisher.post_publication(test_image, "Test caption")

    assert result["id"] == "test_post_id"
    assert result["text"] == "Test caption"
    assert result["mediaUuids"] == ["test_media_uuid"]
