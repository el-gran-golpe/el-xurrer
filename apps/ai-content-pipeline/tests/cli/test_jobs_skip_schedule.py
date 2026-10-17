"""
jobs run --skip-schedule never publishes, so it must not require Meta Page
tokens either: validate_meta_profile_auth should only run when a schedule job
could actually publish something.
"""

from types import SimpleNamespace

import pytest

from ai_content_pipeline.cli.commands import jobs as jobs_cli


def _profile(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, tmp_path):
    observed: list[tuple] = []
    # jobs_cli.run() writes the end-of-run report after _execute(); keep it
    # out of the real repo tree.
    monkeypatch.setattr(jobs_cli.settings, "jobs_report_dir", tmp_path / "runs")

    def fake_resolve_profiles(indexes, names):
        return [_profile("laura_vigne")]

    def fake_validate_meta_profile_auth(profile):
        observed.append(("validate", profile.name))

    async def fake_execute(
        profiles, use_initial_conditions, refresh_model_cache, skip_schedule, weeks
    ):
        observed.append(("execute", [p.name for p in profiles], skip_schedule, weeks))
        return "run1", []

    class FakeDriveSync:
        def push(self, resources_dir):
            observed.append(("push", resources_dir))

    monkeypatch.setattr(jobs_cli, "resolve_profiles", fake_resolve_profiles)
    monkeypatch.setattr(
        jobs_cli, "validate_meta_profile_auth", fake_validate_meta_profile_auth
    )
    monkeypatch.setattr(jobs_cli, "_execute", fake_execute)
    monkeypatch.setattr(jobs_cli, "get_gdrive_sync", lambda: FakeDriveSync())
    return observed


def test_skip_schedule_never_validates_meta_auth(wired):
    jobs_cli.run(
        profile_indexes=[],
        profile_names=None,
        use_initial_conditions=True,
        refresh_model_cache=False,
        skip_schedule=True,
        weeks=1,
    )

    assert ("validate", "laura_vigne") not in wired
    assert ("execute", ["laura_vigne"], True, 1) in wired


def test_without_skip_schedule_still_validates_meta_auth(wired):
    """Pins today's behavior: publishing runs must still validate Meta auth
    up front, same as before --skip-schedule existed."""
    jobs_cli.run(
        profile_indexes=[],
        profile_names=None,
        use_initial_conditions=True,
        refresh_model_cache=False,
        skip_schedule=False,
        weeks=1,
    )

    assert ("validate", "laura_vigne") in wired
    assert ("execute", ["laura_vigne"], False, 1) in wired
