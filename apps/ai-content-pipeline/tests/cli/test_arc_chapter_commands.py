"""
`arc plan` / `chapter plan` CLI commands, driven through the real top-level
CLI (`cli_main.app`, via `CliRunner`), same pattern as `test_profile_selection.py`:
Google Drive sync and profile loading are mocked, and `StoryManager` (the
only thing these commands actually do work through) is replaced with a
fake that records how it was called.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from ai_content_pipeline.cli import main as cli_main
from ai_content_pipeline.cli.commands import arc, chapter, utils
from ai_content_pipeline.llm.utils.utils import planning_week_start

runner = CliRunner()
TODAYS_TARGET_WEEK = planning_week_start(date.today()).isoformat()


@pytest.fixture
def profiles(monkeypatch):
    loaded = [
        SimpleNamespace(name="first_profile"),
        SimpleNamespace(name="second_profile"),
    ]
    monkeypatch.setattr(utils.profile_repository, "_profiles", loaded)
    monkeypatch.setattr(
        utils.profile_repository,
        "_profiles_by_name",
        {p.name: p for p in loaded},
    )
    monkeypatch.setattr(cli_main, "get_gdrive_sync", Mock(return_value=Mock()))
    monkeypatch.setattr(utils.profile_repository, "load_profiles", Mock())
    return loaded


class FakeArc(SimpleNamespace):
    pass


@pytest.fixture
def fake_story_manager(monkeypatch):
    calls: list[dict] = []

    class FakeStoryManager:
        def __init__(self, profile, repository, refresh_model_cache=False):
            self.profile = profile

        def ensure_arc(self, week, force=False):
            calls.append(
                {
                    "method": "ensure_arc",
                    "profile": self.profile.name,
                    "week": week,
                    "force": force,
                }
            )
            arc = FakeArc(start_week=week, weeks=12)
            return arc, True, SimpleNamespace(attempt=1, max_attempts=5)

        def ensure_chapter(self, arc_, week, force=False):
            calls.append(
                {
                    "method": "ensure_chapter",
                    "profile": self.profile.name,
                    "week": week,
                    "force": force,
                }
            )
            chapter_ = FakeArc(start_week=week, weeks=4)
            return chapter_, True, SimpleNamespace(attempt=1, max_attempts=5)

    monkeypatch.setattr(arc, "StoryManager", FakeStoryManager)
    monkeypatch.setattr(chapter, "StoryManager", FakeStoryManager)
    return calls


def test_arc_plan_defaults_to_all_profiles_and_this_runs_target_week(
    profiles, fake_story_manager
):
    result = runner.invoke(cli_main.app, ["arc", "plan"])

    assert result.exit_code == 0, result.output
    assert [c["profile"] for c in fake_story_manager] == [p.name for p in profiles]
    assert all(c["week"] == TODAYS_TARGET_WEEK for c in fake_story_manager)
    assert all(c["force"] is False for c in fake_story_manager)


def test_arc_plan_respects_an_explicit_week(profiles, fake_story_manager):
    result = runner.invoke(
        cli_main.app, ["arc", "plan", "--week", "2026-10-12", "-n", "first_profile"]
    )

    assert result.exit_code == 0, result.output
    assert fake_story_manager == [
        {
            "method": "ensure_arc",
            "profile": "first_profile",
            "week": "2026-10-12",
            "force": False,
        }
    ]


def test_arc_plan_force_flag_is_passed_through(profiles, fake_story_manager):
    result = runner.invoke(
        cli_main.app, ["arc", "plan", "--force", "-n", "first_profile"]
    )

    assert result.exit_code == 0, result.output
    assert fake_story_manager[0]["force"] is True


def test_arc_plan_respects_profile_selection(profiles, fake_story_manager):
    result = runner.invoke(cli_main.app, ["arc", "plan", "-n", "second_profile"])

    assert result.exit_code == 0, result.output
    assert [c["profile"] for c in fake_story_manager] == ["second_profile"]


def test_chapter_plan_ensures_the_arc_without_forcing_it_then_the_chapter(
    profiles, fake_story_manager
):
    result = runner.invoke(
        cli_main.app, ["chapter", "plan", "--force", "-n", "first_profile"]
    )

    assert result.exit_code == 0, result.output
    assert [c["method"] for c in fake_story_manager] == ["ensure_arc", "ensure_chapter"]
    arc_call, chapter_call = fake_story_manager
    assert arc_call["force"] is False  # the arc step is never forced by `chapter plan`
    assert chapter_call["force"] is True


def test_chapter_plan_respects_an_explicit_week(profiles, fake_story_manager):
    result = runner.invoke(
        cli_main.app, ["chapter", "plan", "--week", "2026-10-12", "-n", "first_profile"]
    )

    assert result.exit_code == 0, result.output
    assert all(c["week"] == "2026-10-12" for c in fake_story_manager)


def test_chapter_plan_defaults_to_all_profiles(profiles, fake_story_manager):
    result = runner.invoke(cli_main.app, ["chapter", "plan"])

    assert result.exit_code == 0, result.output
    profiles_touched = {c["profile"] for c in fake_story_manager}
    assert profiles_touched == {p.name for p in profiles}
