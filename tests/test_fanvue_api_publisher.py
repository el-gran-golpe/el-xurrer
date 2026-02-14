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
