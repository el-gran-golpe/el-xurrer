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

    class FakeProfileManager:
        resource_path = "resources"

        def load_profiles(self):
            print("PROFILE LOAD STARTED", file=sys.stderr)
            events.append(("load", None))

    monkeypatch.setattr(cli_main, "get_gdrive_sync", lambda: FakeGoogleDriveSync())
    monkeypatch.setattr(cli_main, "profile_manager", FakeProfileManager())

    cli_main.main_callback(SimpleNamespace(invoked_subcommand="meta"))

    stderr = capsys.readouterr().err
    assert "CLI STARTUP PREFLIGHT" in stderr
    assert "PREFLIGHT COMPLETE" in stderr
    assert stderr.index("CLI STARTUP PREFLIGHT") < stderr.index("SYNC STARTED")
    assert stderr.index("SYNC STARTED") < stderr.index("PROFILE LOAD STARTED")
    assert stderr.index("PROFILE LOAD STARTED") < stderr.index("PREFLIGHT COMPLETE")
    assert events == [("sync", "resources"), ("load", None)]
