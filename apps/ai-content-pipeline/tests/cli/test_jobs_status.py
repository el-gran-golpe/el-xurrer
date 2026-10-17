"""
`jobs status` is a read-only report off the local jobs DB. These tests drive
it through the real top-level CLI (`cli_main.app`, via CliRunner), the same
as `test_profile_selection.py`, so they also exercise `main_callback`'s
network-avoidance special case for `jobs status` end to end. Google Drive
sync and profile loading are mocked to blow up loudly if ever called, so a
regression that reintroduces a network call fails the test instead of
silently making a real request.
"""

import sys

import pytest
from typer.testing import CliRunner

from ai_content_pipeline.cli import main as cli_main
from ai_content_pipeline.config import settings
from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.jobs.store import JobEventKind, JobStore, JobType

runner = CliRunner()


def _blow_up(*args, **kwargs):
    raise AssertionError("jobs status must never touch the network")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any attempt to pull from Drive or load profiles fails the test."""
    monkeypatch.setattr(cli_main, "get_gdrive_sync", lambda: _NetworkTripwire())
    monkeypatch.setattr(cli_main.profile_repository, "load_profiles", _blow_up)
    # main_callback's special case keys off real sys.argv, not the CliRunner
    # invocation args, so it must be set to match what the CLI actually sees.
    monkeypatch.setattr(sys, "argv", ["main.py", "jobs", "status"])


class _NetworkTripwire:
    def pull(self, *args, **kwargs):
        _blow_up()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    monkeypatch.setattr(settings, "jobs_db_path", path)
    return path


def test_status_with_no_db_file_reports_that_and_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "jobs_db_path", tmp_path / "missing.db")

    result = runner.invoke(cli_main.app, ["jobs", "status"])

    assert result.exit_code == 0
    assert "No jobs database found" in result.stdout


def test_status_with_an_empty_db_reports_no_runs(db_path):
    JobStore(db_path).close()

    result = runner.invoke(cli_main.app, ["jobs", "status"])

    assert result.exit_code == 0
    assert "No runs recorded yet." in result.stdout
    assert "No jobs recorded yet." in result.stdout


def test_status_shows_the_last_runs_summary_and_the_overview(db_path):
    store = JobStore(db_path)
    run_id = store.start_run({"weeks": 1})
    store.create("plan:haru:meta:2026-09-01", JobType.PLAN, "haru", Platform.META)
    store.mark_done("plan:haru:meta:2026-09-01")
    store.record_event(
        run_id,
        "plan:haru:meta:2026-09-01",
        JobType.PLAN,
        "haru",
        Platform.META,
        "2026-09-01",
        JobEventKind.PLAN_DONE,
        detail={
            "attempt": 1,
            "max_attempts": 5,
            "model": "openrouter/some-model",
            "used_fallback": False,
            "pinned_corrections": 0,
        },
    )
    store.create(
        "generate_image:haru:meta:2026-09-01/day_1/beach_0.jpeg",
        JobType.GENERATE_IMAGE,
        "haru",
        Platform.META,
    )
    store.mark_done("generate_image:haru:meta:2026-09-01/day_1/beach_0.jpeg")
    store.finish_run(run_id, "success")
    store.close()

    result = runner.invoke(cli_main.app, ["jobs", "status"])

    assert result.exit_code == 0
    assert run_id in result.stdout
    assert "haru" in result.stdout
    assert "meta" in result.stdout
    assert "2026-09-01" in result.stdout
    assert "1/1" in result.stdout  # images done/total in the overview


def test_status_dash_dash_run_shows_a_specific_run(db_path):
    store = JobStore(db_path)
    run_a = store.start_run({})
    store.record_event(
        run_a,
        "plan:a",
        JobType.PLAN,
        "a",
        Platform.META,
        "2026-09-01",
        JobEventKind.PLAN_DONE,
        detail={
            "attempt": 1,
            "max_attempts": 5,
            "model": None,
            "used_fallback": False,
            "pinned_corrections": 0,
        },
    )
    run_b = store.start_run({})
    store.record_event(
        run_b,
        "plan:b",
        JobType.PLAN,
        "b",
        Platform.META,
        "2026-09-01",
        JobEventKind.PLAN_REUSED,
    )
    store.close()

    result = runner.invoke(cli_main.app, ["jobs", "status", "--run", run_a])

    assert result.exit_code == 0
    assert run_a in result.stdout
    assert '"a"' not in result.stdout  # sanity: not literally dumping JSON
    assert "a" in result.stdout


def test_status_dash_dash_runs_lists_recent_runs(db_path):
    store = JobStore(db_path)
    store.start_run({})
    second = store.start_run({})
    store.finish_run(second, "failed")
    store.close()

    result = runner.invoke(cli_main.app, ["jobs", "status", "--runs"])

    assert result.exit_code == 0
    assert second in result.stdout
    assert "failed" in result.stdout
