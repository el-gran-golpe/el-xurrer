import importlib
import inspect
from types import SimpleNamespace

import pytest
import typer

from ai_content_pipeline.domain.types import Platform


all_commands = importlib.import_module("ai_content_pipeline.cli.commands.all")
utils = importlib.import_module("ai_content_pipeline.cli.commands.utils")


class FakeProfileManager:
    def __init__(self, profiles):
        self.profiles = list(profiles)

    def get_profile_by_index(self, index: int):
        return self.profiles[index]

    def get_profile_by_name(self, name: str):
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise KeyError(name)

    def get_all_profiles(self):
        return list(self.profiles)


def _profile(name, tmp_path):
    return SimpleNamespace(
        name=name,
        platform_info={
            Platform.META: SimpleNamespace(
                outputs_path=tmp_path / name / "meta" / "outputs"
            ),
            Platform.FANVUE: SimpleNamespace(
                outputs_path=tmp_path / name / "fanvue" / "outputs"
            ),
        },
    )


def _seed_outputs(profile):
    for platform in Platform:
        outputs_path = profile.platform_info[platform].outputs_path
        nested_path = outputs_path / "publications" / "week_1"
        nested_path.mkdir(parents=True)
        (outputs_path / "old_planning.json").write_text("{}", encoding="utf-8")
        (nested_path / "old_image.jpeg").write_text("old", encoding="utf-8")


def _output_entries(profile):
    return {
        platform: list(profile.platform_info[platform].outputs_path.iterdir())
        for platform in Platform
    }


def test_resolve_profiles_can_default_to_all_loaded_profiles(monkeypatch, tmp_path):
    profiles = [_profile("laura_vigne", tmp_path), _profile("maria_larsen", tmp_path)]
    monkeypatch.setattr(utils, "profile_manager", FakeProfileManager(profiles))

    assert utils.resolve_profiles([], None, default_all=True) == profiles


def test_resolve_profiles_still_requires_selection_by_default(monkeypatch, tmp_path):
    profiles = [_profile("laura_vigne", tmp_path)]
    monkeypatch.setattr(utils, "profile_manager", FakeProfileManager(profiles))

    with pytest.raises(typer.BadParameter):
        utils.resolve_profiles([], None)


def test_run_all_cleans_selected_profile_outputs_before_pipeline(monkeypatch, tmp_path):
    profiles = [_profile("laura_vigne", tmp_path), _profile("maria_larsen", tmp_path)]
    for profile in profiles:
        _seed_outputs(profile)

    observed = {}

    def fake_resolve_profiles(indexes, names, *, default_all=False):
        observed["default_all"] = default_all
        return profiles

    async def fake_execute_all(
        selected_profiles,
        overwrite,
        use_initial_conditions,
        refresh_model_cache,
    ):
        observed["profiles"] = selected_profiles
        observed["entries_during_execute"] = {
            profile.name: _output_entries(profile) for profile in selected_profiles
        }

    class FakeDriveSync:
        def push(self, resources_dir):
            observed["pushed"] = resources_dir

    monkeypatch.setattr(all_commands, "resolve_profiles", fake_resolve_profiles)
    monkeypatch.setattr(all_commands, "_execute_all", fake_execute_all)
    monkeypatch.setattr(all_commands, "get_gdrive_sync", lambda: FakeDriveSync())

    all_commands.run_all(
        profile_indexes=[],
        profile_names=None,
        overwrite=True,
        use_initial_conditions=True,
        refresh_model_cache=False,
        cleanup_local_outputs=True,
    )

    assert observed["default_all"] is True
    assert observed["profiles"] == profiles
    for profile_entries in observed["entries_during_execute"].values():
        assert profile_entries == {Platform.META: [], Platform.FANVUE: []}


def test_run_all_can_keep_existing_outputs(monkeypatch, tmp_path):
    profiles = [_profile("laura_vigne", tmp_path)]
    _seed_outputs(profiles[0])
    observed = {}

    async def fake_execute_all(
        selected_profiles,
        overwrite,
        use_initial_conditions,
        refresh_model_cache,
    ):
        observed["entries_during_execute"] = _output_entries(selected_profiles[0])

    class FakeDriveSync:
        def push(self, resources_dir):
            observed["pushed"] = resources_dir

    monkeypatch.setattr(
        all_commands,
        "resolve_profiles",
        lambda indexes, names, *, default_all=False: profiles,
    )
    monkeypatch.setattr(all_commands, "_execute_all", fake_execute_all)
    monkeypatch.setattr(all_commands, "get_gdrive_sync", lambda: FakeDriveSync())

    all_commands.run_all(
        profile_indexes=[],
        profile_names=None,
        overwrite=True,
        use_initial_conditions=True,
        refresh_model_cache=False,
        cleanup_local_outputs=False,
    )

    assert len(observed["entries_during_execute"][Platform.META]) == 2
    assert len(observed["entries_during_execute"][Platform.FANVUE]) == 2


def test_run_all_cleanup_defaults_to_clean_outputs():
    cleanup_option = (
        inspect.signature(all_commands.run_all)
        .parameters["cleanup_local_outputs"]
        .default
    )

    assert cleanup_option.default is True
