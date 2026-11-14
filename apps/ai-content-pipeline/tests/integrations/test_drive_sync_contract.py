"""
`GoogleDriveSync`'s pull/push contract for `persona.md` and the `story/`
tree (`config.json`, `arcs/*.json`, `chapters/*.json`), added alongside the
existing per-platform `inputs/` contract. These exercise the manifest
builders directly (`_build_local_manifest`, `_build_remote_pull_manifest`,
`_push_manifest`) rather than the real Drive API — no network, no
credentials, matching the existing `test_drive_sync_toggle.py` style.
"""

from pathlib import Path

import pytest

from ai_content_pipeline.integrations.google_drive.sync_resources import (
    GoogleDriveSync,
    RemoteFile,
    RemoteFolder,
    RemoteIndex,
)


@pytest.fixture
def sync() -> GoogleDriveSync:
    return GoogleDriveSync()


def _write_base_profile(root: Path, name: str = "haru_profile") -> Path:
    """The mandatory part of the contract: workflow JSON + both platforms'
    flat `inputs/`. Returns the profile directory."""
    profile_dir = root / name
    profile_dir.mkdir(parents=True)
    (profile_dir / f"{name}_comfyworkflow.json").write_text("{}", encoding="utf-8")
    for platform in ("meta", "fanvue"):
        inputs = profile_dir / platform / "inputs"
        inputs.mkdir(parents=True)
        (inputs / "initial_conditions.md").write_text("notes", encoding="utf-8")
        (inputs / f"{name}.json").write_text("{}", encoding="utf-8")
    return profile_dir


# ---------------- local manifest: persona.md + story/ (optional) ----------


def test_local_manifest_omits_persona_and_story_when_absent(sync, tmp_path):
    _write_base_profile(tmp_path)

    manifest = sync._build_local_manifest(tmp_path)

    assert Path("haru_profile/persona.md") not in manifest
    assert not any(p.parts[1] == "story" for p in manifest if len(p.parts) > 1)


def test_local_manifest_includes_persona_when_present(sync, tmp_path):
    profile_dir = _write_base_profile(tmp_path)
    (profile_dir / "persona.md").write_text("persona", encoding="utf-8")

    manifest = sync._build_local_manifest(tmp_path)

    assert Path("haru_profile/persona.md") in manifest


def test_local_manifest_includes_story_config_and_dated_arcs_and_chapters(
    sync, tmp_path
):
    profile_dir = _write_base_profile(tmp_path)
    story = profile_dir / "story"
    (story / "arcs").mkdir(parents=True)
    (story / "chapters").mkdir(parents=True)
    (story / "config.json").write_text("{}", encoding="utf-8")
    (story / "arcs" / "2026-10-05.json").write_text("{}", encoding="utf-8")
    (story / "chapters" / "2026-10-05.json").write_text("{}", encoding="utf-8")

    manifest = sync._build_local_manifest(tmp_path)

    assert Path("haru_profile/story/config.json") in manifest
    assert Path("haru_profile/story/arcs/2026-10-05.json") in manifest
    assert Path("haru_profile/story/chapters/2026-10-05.json") in manifest


def test_local_manifest_rejects_a_badly_named_arc_file(sync, tmp_path):
    profile_dir = _write_base_profile(tmp_path)
    arcs = profile_dir / "story" / "arcs"
    arcs.mkdir(parents=True)
    (arcs / "week_1.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="YYYY-MM-DD.json"):
        sync._build_local_manifest(tmp_path)


def test_local_manifest_rejects_a_nested_folder_under_arcs(sync, tmp_path):
    profile_dir = _write_base_profile(tmp_path)
    nested = profile_dir / "story" / "arcs" / "subdir"
    nested.mkdir(parents=True)

    with pytest.raises(ValueError, match="must be flat"):
        sync._build_local_manifest(tmp_path)


def test_local_manifest_rejects_unexpected_entries_in_story_dir(sync, tmp_path):
    profile_dir = _write_base_profile(tmp_path)
    story = profile_dir / "story"
    story.mkdir()
    (story / "notes.txt").write_text("stray", encoding="utf-8")

    with pytest.raises(ValueError, match="story"):
        sync._build_local_manifest(tmp_path)


# ---------------- remote pull manifest: mirror of the above ---------------


def _remote_index_for(profile_name: str, *, with_story: bool = False) -> RemoteIndex:
    profile = Path(profile_name)
    folders: dict[Path, RemoteFolder] = {}
    files: dict[Path, RemoteFile] = {}

    def add_folder(path: Path) -> None:
        folders[path] = RemoteFolder(
            id=f"id:{path}", path=path, name=path.name, parent_id="p"
        )

    def add_file(path: Path) -> None:
        files[path] = RemoteFile(
            id=f"id:{path}", path=path, name=path.name, parent_id="p", md5_checksum="x"
        )

    add_folder(profile)
    add_file(profile / f"{profile_name}_comfyworkflow.json")
    for platform in ("meta", "fanvue"):
        add_folder(profile / platform)
        add_folder(profile / platform / "inputs")
        add_file(profile / platform / "inputs" / "initial_conditions.md")
        add_file(profile / platform / "inputs" / f"{profile_name}.json")

    if with_story:
        add_folder(profile / "story")
        add_folder(profile / "story" / "arcs")
        add_file(profile / "story" / "config.json")
        add_file(profile / "story" / "arcs" / "2026-10-05.json")

    return RemoteIndex(folders=folders, files=files)


def test_remote_pull_manifest_omits_story_when_absent(sync):
    index = _remote_index_for("haru_profile", with_story=False)

    manifest = sync._build_remote_pull_manifest(index)

    assert not any(p.parts[1] == "story" for p in manifest if len(p.parts) > 1)


def test_remote_pull_manifest_includes_story_when_present(sync):
    index = _remote_index_for("haru_profile", with_story=True)

    manifest = sync._build_remote_pull_manifest(index)

    assert Path("haru_profile/story/config.json") in manifest
    assert Path("haru_profile/story/arcs/2026-10-05.json") in manifest


def test_remote_pull_manifest_rejects_a_badly_named_chapter_file(sync):
    index = _remote_index_for("haru_profile", with_story=True)
    profile = Path("haru_profile")
    index.folders[profile / "story" / "chapters"] = RemoteFolder(
        id="id:chapters",
        path=profile / "story" / "chapters",
        name="chapters",
        parent_id="p",
    )
    index.files[profile / "story" / "chapters" / "not-a-date.json"] = RemoteFile(
        id="id:bad",
        path=profile / "story" / "chapters" / "not-a-date.json",
        name="not-a-date.json",
        parent_id="p",
        md5_checksum="x",
    )

    with pytest.raises(ValueError, match="YYYY-MM-DD.json"):
        sync._build_remote_pull_manifest(index)


def test_remote_pull_manifest_rejects_a_nested_folder_under_arcs(sync):
    index = _remote_index_for("haru_profile", with_story=True)
    profile = Path("haru_profile")
    nested = profile / "story" / "arcs" / "subdir"
    index.folders[nested] = RemoteFolder(
        id="id:nested", path=nested, name="subdir", parent_id="p"
    )

    with pytest.raises(ValueError, match="flat"):
        sync._build_remote_pull_manifest(index)


def test_remote_pull_manifest_rejects_unexpected_entries_in_story_dir(sync):
    index = _remote_index_for("haru_profile", with_story=True)
    profile = Path("haru_profile")
    stray = profile / "story" / "notes.txt"
    index.files[stray] = RemoteFile(
        id="id:stray", path=stray, name="notes.txt", parent_id="p", md5_checksum="x"
    )

    with pytest.raises(ValueError, match="story"):
        sync._build_remote_pull_manifest(index)


# ---------------- push: story folders are preserved, stray ones are not --


class _RecordingFiles:
    def __init__(self) -> None:
        self.deleted_ids: list[str] = []

    def delete(self, fileId: str):
        self.deleted_ids.append(fileId)

        class _Exec:
            def execute(self_inner):
                return None

        return _Exec()


class _RecordingService:
    def __init__(self) -> None:
        self._files = _RecordingFiles()

    def files(self):
        return self._files


def test_push_preserves_the_story_tree_but_deletes_a_stray_file_outside_the_contract(
    sync, tmp_path
):
    """
    Regression test for the folder-deletion ordering bug: before
    `_push_manifest`'s `keep_folders` included every parent of a locally
    pushed file (not just the fixed profile/platform/inputs tree), a
    profile's `story/` (and `story/arcs/`) folders would be wrongly queued
    for deletion on every push, even though their own files were about to
    be re-uploaded as "kept".
    """
    profile_dir = _write_base_profile(tmp_path, name="haru_profile")
    story = profile_dir / "story"
    arcs = story / "arcs"
    arcs.mkdir(parents=True)
    (story / "config.json").write_text("{}", encoding="utf-8")
    (arcs / "2026-10-05.json").write_text("{}", encoding="utf-8")

    local_manifest = sync._build_local_manifest(tmp_path)

    # Build a RemoteIndex that already matches every local file's content
    # (same md5), so nothing needs to be *uploaded* — this test is only
    # about what push decides to *delete*. Also add one stray file and one
    # stray folder that are genuinely outside the contract.
    folders: dict[Path, RemoteFolder] = {}
    files: dict[Path, RemoteFile] = {}
    for rel_path, local_path in local_manifest.items():
        files[rel_path] = RemoteFile(
            id=f"id:{rel_path}",
            path=rel_path,
            name=rel_path.name,
            parent_id="p",
            md5_checksum=sync._local_md5(local_path),
        )
    profile = Path("haru_profile")
    for folder_path in [
        profile,
        profile / "meta",
        profile / "meta" / "inputs",
        profile / "fanvue",
        profile / "fanvue" / "inputs",
        profile / "story",
        profile / "story" / "arcs",
    ]:
        folders[folder_path] = RemoteFolder(
            id=f"id:{folder_path}",
            path=folder_path,
            name=folder_path.name,
            parent_id="p",
        )

    stray_folder = profile / "story" / "stray_subdir"
    folders[stray_folder] = RemoteFolder(
        id="id:stray-folder", path=stray_folder, name="stray_subdir", parent_id="p"
    )
    stray_file = profile / "random_extra_file.txt"
    files[stray_file] = RemoteFile(
        id="id:stray-file",
        path=stray_file,
        name="random_extra_file.txt",
        parent_id="p",
        md5_checksum="whatever",
    )

    remote_index = RemoteIndex(folders=folders, files=files)
    service = _RecordingService()

    sync._push_manifest(service, local_manifest, remote_index)

    assert "id:stray-file" in service._files.deleted_ids
    assert "id:stray-folder" in service._files.deleted_ids
    # The real story tree (and everything else in the contract) must
    # survive the push untouched.
    for folder_path in [
        profile / "story",
        profile / "story" / "arcs",
        profile / "meta" / "inputs",
    ]:
        assert folders[folder_path].id not in service._files.deleted_ids
    for rel_path in local_manifest:
        assert files[rel_path].id not in service._files.deleted_ids
