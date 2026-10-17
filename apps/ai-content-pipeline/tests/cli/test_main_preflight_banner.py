import sys
from types import SimpleNamespace

from ai_content_pipeline.cli import main as cli_main


def test_main_callback_prints_startup_preflight_markers_around_sync_and_load(
    monkeypatch,
    capsys,
):
    events = []

    class FakeGoogleDriveSync:
        def pull(self, resource_path):
            print("SYNC STARTED", file=sys.stderr)
            events.append(("sync", resource_path))

    class FakeProfileRepository:
        resource_path = "resources"

        def load_profiles(self):
            print("PROFILE LOAD STARTED", file=sys.stderr)
            events.append(("load", None))

    monkeypatch.setattr(cli_main, "get_gdrive_sync", lambda: FakeGoogleDriveSync())
    monkeypatch.setattr(cli_main, "profile_repository", FakeProfileRepository())

    cli_main.main_callback(SimpleNamespace(invoked_subcommand="meta"))

    stderr = capsys.readouterr().err
    assert "CLI STARTUP PREFLIGHT" in stderr
    assert "PREFLIGHT COMPLETE" in stderr
    assert stderr.index("CLI STARTUP PREFLIGHT") < stderr.index("SYNC STARTED")
    assert stderr.index("SYNC STARTED") < stderr.index("PROFILE LOAD STARTED")
    assert stderr.index("PROFILE LOAD STARTED") < stderr.index("PREFLIGHT COMPLETE")
    assert events == [("sync", "resources"), ("load", None)]


def test_jobs_status_skips_drive_pull_and_profile_loading(monkeypatch, capsys):
    """
    `jobs status` is a read-only report off the local jobs DB: it must never
    pull from Google Drive or load profiles (no network side effects), so
    `main_callback` special-cases it before the preflight banner/pull/load.
    """
    events = []

    class FakeGoogleDriveSync:
        def pull(self, resource_path):
            events.append(("sync", resource_path))

    class FakeProfileRepository:
        resource_path = "resources"

        def load_profiles(self):
            events.append(("load", None))

    monkeypatch.setattr(cli_main, "get_gdrive_sync", lambda: FakeGoogleDriveSync())
    monkeypatch.setattr(cli_main, "profile_repository", FakeProfileRepository())
    monkeypatch.setattr(sys, "argv", ["main.py", "jobs", "status"])

    cli_main.main_callback(SimpleNamespace(invoked_subcommand="jobs"))

    assert events == []
    assert capsys.readouterr().err == ""
