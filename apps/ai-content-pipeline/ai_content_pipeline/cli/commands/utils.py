from typing import Optional

from ai_content_pipeline.integrations.google_drive.sync_resources import GoogleDriveSync
from ai_content_pipeline.paths import RESOURCES_DIR
from ai_content_pipeline.profiles.profile import ProfileManager, Profile


PROFILE_INDEXES_HELP = (
    "Profile indexes (repeat -p to select multiple); overrides -n. "
    "Defaults to all loaded profiles when neither -p nor -n is provided."
)
PROFILE_NAMES_HELP = (
    "Comma-separated profile names. "
    "Defaults to all loaded profiles when neither -p nor -n is provided."
)


def get_gdrive_sync() -> GoogleDriveSync:
    """Returns an instance of GoogleDriveSync."""
    return GoogleDriveSync()


profile_manager = ProfileManager(RESOURCES_DIR)


def resolve_profiles(
    indexes: list[int],
    names: Optional[str],
) -> list[Profile]:
    """
    Pick profiles by indexes or comma-separated names, defaulting to all loaded
    profiles when neither selector is provided. Indexes take precedence.
    """
    if indexes:
        return [profile_manager.get_profile_by_index(i) for i in indexes]
    if names is not None:
        return [
            profile_manager.get_profile_by_name(n.strip()) for n in names.split(",")
        ]
    return profile_manager.get_all_profiles()
