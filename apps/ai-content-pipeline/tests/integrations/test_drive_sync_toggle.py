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

    def _build(enabled: bool) -> GoogleDriveSync:
        monkeypatch.setattr(
            sync_resources,
            "settings",
            SimpleNamespace(folder_id="folder", drive_sync_enabled=enabled),
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
        sync(enabled=True).pull(tmp_path)
