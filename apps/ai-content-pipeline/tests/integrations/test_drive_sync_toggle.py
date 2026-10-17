from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_content_pipeline.integrations.google_drive import sync_resources
from ai_content_pipeline.integrations.google_drive.sync_resources import GoogleDriveSync


def _explode():
    raise RuntimeError("Drive was contacted while sync was disabled")


@pytest.fixture
def sync(monkeypatch: pytest.MonkeyPatch):
    """
    A GoogleDriveSync whose settings say sync is off, and that explodes if it
    ever reaches the network: the point of the flag is that it authenticates
    with nobody.
    """

    def _build(enabled: bool, allow_custom_root: bool = False) -> GoogleDriveSync:
        monkeypatch.setattr(
            sync_resources,
            "settings",
            SimpleNamespace(
                folder_id="folder",
                drive_sync_enabled=enabled,
                drive_sync_allow_custom_root=allow_custom_root,
            ),
        )
        instance = GoogleDriveSync()
        monkeypatch.setattr(
            instance,
            "_get_drive_service",
            _explode,
        )
        return instance

    return _build


def test_pull_does_nothing_when_sync_is_disabled(sync, tmp_path: Path):
    sync(enabled=False).pull(tmp_path)


def test_push_does_nothing_when_sync_is_disabled(sync, tmp_path: Path):
    sync(enabled=False).push(tmp_path)


def test_pull_leaves_the_local_tree_untouched_when_disabled(sync, tmp_path: Path):
    local = tmp_path / "haru" / "persona.md"
    local.parent.mkdir(parents=True)
    local.write_text("locally migrated, not yet on Drive", encoding="utf-8")

    sync(enabled=False).pull(tmp_path)

    assert local.read_text(encoding="utf-8") == "locally migrated, not yet on Drive"


def test_sync_still_runs_when_enabled(sync, tmp_path: Path):
    """The flag defaults to on; disabling must be the deliberate choice."""
    with pytest.raises(RuntimeError, match="Drive was contacted"):
        sync(enabled=True, allow_custom_root=True).pull(tmp_path)


def test_pull_refuses_a_non_default_resources_root(sync, tmp_path: Path):
    """
    A non-default resources directory (e.g. a migration sandbox reached via
    AI_CONTENT_RESOURCES_DIR) must not reach Drive at all, even though sync
    is enabled, unless the override is set.
    """
    with pytest.raises(ValueError, match="non-default resources"):
        sync(enabled=True, allow_custom_root=False).pull(tmp_path)


def test_push_refuses_a_non_default_resources_root(sync, tmp_path: Path):
    with pytest.raises(ValueError, match="non-default resources"):
        sync(enabled=True, allow_custom_root=False).push(tmp_path)


def test_custom_root_guard_is_bypassed_when_explicitly_allowed(sync, tmp_path: Path):
    """DRIVE_SYNC_ALLOW_CUSTOM_ROOT=true lets a non-default directory through
    to the point of authenticating (which then explodes, proving it got
    there)."""
    with pytest.raises(RuntimeError, match="Drive was contacted"):
        sync(enabled=True, allow_custom_root=True).pull(tmp_path)


def test_default_resources_root_is_always_allowed(
    sync, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The repo's own resources/ directory never needs the override."""
    monkeypatch.setattr(sync_resources, "REPO_ROOT", tmp_path)
    default_root = tmp_path / "resources"

    with pytest.raises(RuntimeError, match="Drive was contacted"):
        sync(enabled=True, allow_custom_root=False).pull(default_root)


def test_sync_disabled_wins_over_the_custom_root_guard(sync, tmp_path: Path):
    """DRIVE_SYNC_ENABLED=false must stay a silent no-op even for a
    non-default directory, so the two guards never fight each other."""
    sync(enabled=False, allow_custom_root=False).pull(tmp_path)
    sync(enabled=False, allow_custom_root=False).push(tmp_path)
