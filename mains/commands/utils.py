import typer
from pathlib import Path
from typing import Optional

from automation.gdrive.sync_resources import GoogleDriveSync
from main_components.common.profile import ProfileManager, Profile


# project root is three levels up from this file
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
RESOURCES_DIR = ROOT_DIR / "resources"


def get_gdrive_sync() -> GoogleDriveSync:
    """Returns an instance of GoogleDriveSync."""
    return GoogleDriveSync()


profile_manager = ProfileManager(RESOURCES_DIR)


def resolve_profiles(
    indexes: list[int],
    names: Optional[str],
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
    raise typer.BadParameter("Provide --profile-indexes or --profile-names.")
