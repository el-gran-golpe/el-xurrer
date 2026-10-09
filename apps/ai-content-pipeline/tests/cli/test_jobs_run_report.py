"""
`jobs run`'s end-of-run report: a non-zero exit code when any row has an
error, and the Markdown report file written to JOBS_REPORT_DIR either way.
`_execute` itself is faked here (it is covered by `tests/jobs/test_tasks.py`
and `tests/jobs/test_dag_end_to_end.py`), so these tests only exercise
`run()`'s own reporting/exit-code wiring.
"""

from types import SimpleNamespace

import pytest
import typer

from ai_content_pipeline.cli.commands import jobs as jobs_cli
from ai_content_pipeline.jobs import report


def _profile(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, tmp_path):
    pushed = []
    monkeypatch.setattr(
        jobs_cli, "resolve_profiles", lambda indexes, names: [_profile("haru")]
    )
    monkeypatch.setattr(jobs_cli, "validate_meta_profile_auth", lambda profile: None)
    monkeypatch.setattr(
        jobs_cli,
        "get_gdrive_sync",
        lambda: SimpleNamespace(
            push=lambda resources_dir: pushed.append(resources_dir)
        ),
    )
    monkeypatch.setattr(jobs_cli.settings, "jobs_report_dir", tmp_path / "runs")
    return pushed


def _run_kwargs(**overrides):
    base = dict(
        profile_indexes=[],
        profile_names=None,
        use_initial_conditions=True,
        refresh_model_cache=False,
        skip_schedule=False,
        weeks=1,
    )
    base.update(overrides)
    return base


def test_a_clean_run_exits_zero_and_writes_the_report(monkeypatch, wired, tmp_path):
    rows = [
        report.RunRow(
            profile="haru",
            platform="meta",
            week="2026-09-01",
            outcome=report.OUTCOME_PLANNED,
        )
    ]

    async def fake_execute(*args, **kwargs):
        return "run1", rows

    monkeypatch.setattr(jobs_cli, "_execute", fake_execute)

    jobs_cli.run(**_run_kwargs())  # must not raise

    report_dir = tmp_path / "runs"
    written = list(report_dir.glob("*_jobs_run.md"))
    assert len(written) == 1
    content = written[0].read_text(encoding="utf-8")
    assert "haru" in content
    assert "planned now" in content
    assert wired == [jobs_cli.RESOURCES_DIR]  # Drive push still happened


def test_a_run_with_a_failure_exits_non_zero_and_still_writes_the_report(
    monkeypatch, wired, tmp_path
):
    rows = [
        report.RunRow(
            profile="haru",
            platform="meta",
            week="2026-09-01",
            outcome=report.OUTCOME_FAILED,
            error="boom",
        )
    ]

    async def fake_execute(*args, **kwargs):
        return "run1", rows

    monkeypatch.setattr(jobs_cli, "_execute", fake_execute)

    with pytest.raises(typer.Exit) as excinfo:
        jobs_cli.run(**_run_kwargs())

    assert excinfo.value.exit_code == 1
    report_dir = tmp_path / "runs"
    written = list(report_dir.glob("*_jobs_run.md"))
    assert len(written) == 1
    assert "boom" in written[0].read_text(encoding="utf-8")
