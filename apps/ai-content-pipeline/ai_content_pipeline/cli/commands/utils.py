from typing import Optional

import typer

from ai_content_pipeline.integrations.google_drive.sync_resources import GoogleDriveSync
from ai_content_pipeline.paths import RESOURCES_DIR
from ai_content_pipeline.profiles.profile import ProfileManager, Profile


def get_gdrive_sync() -> GoogleDriveSync:
    """Returns an instance of GoogleDriveSync."""
    return GoogleDriveSync()


profile_manager = ProfileManager(RESOURCES_DIR)


def resolve_profiles(
    indexes: list[int],
    names: Optional[str],
    *,
    default_all: bool = False,
) -> list[Profile]:
    """
    Pick profiles by index list or comma‑separated names. Indexes win.
    """
    if indexes:
        return [profile_manager.get_profile_by_index(i) for i in indexes]
    if names:
        return [
            profile_manager.get_profile_by_name(n.strip()) for n in names.split(",")
        ]
    if default_all:
        return profile_manager.get_all_profiles()
    raise typer.BadParameter("Provide --profile-indexes or --profile-names.")
