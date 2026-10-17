import json
import socket
from datetime import date, timedelta
from pathlib import Path

import pytest

from ai_content_pipeline.domain.story import Arc, Chapter, ChapterDay
from ai_content_pipeline.domain.types import (
    MetaCredentials,
    Platform,
    PlatformInfo,
    Profile,
)
from ai_content_pipeline.profiles.repository import FilesystemProfileRepository

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
_real_connect = socket.socket.connect


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch):
    """
    Fails any test that tries to open a non-local connection. A test once
    reached real story generation and called DeepSeek with whatever key was
    in the environment; a fake that is missing should fail loudly here, not
    spend quota or touch an external service.
    """

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"Test tried to reach the network: {address!r}")
        return _real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


PROMPTS = {
    "lang": "en",
    "prompts": [
        {
            "prompt": "Plan the week. So far: {previous_storyline}",
            "cache_key": "week",
            "system_prompt": "You plan content starting {day}.",
            "output_as_json": True,
            "is_sensitive_content": False,
        }
    ],
}


def make_profile(tmp_path: Path, name: str = "haru") -> Profile:
    """
    A profile whose per-platform input/output dirs exist under `tmp_path`, as
    `PlatformInfo` requires — a throwaway copy, never the real `resources/`.
    """
    platform_info = {}
    for platform in Platform:
        inputs = tmp_path / name / platform.value / "inputs"
        outputs = tmp_path / name / platform.value / "outputs"
        inputs.mkdir(parents=True)
        outputs.mkdir(parents=True)
        (inputs / f"{name}.json").write_text(json.dumps(PROMPTS), encoding="utf-8")
        (inputs / "initial_conditions.md").write_text("once upon a time", "utf-8")
        platform_info[platform] = PlatformInfo(
            name=platform, inputs_path=inputs, outputs_path=outputs, lang="en"
        )
    return Profile(
        name=name,
        platform_info=platform_info,
        meta_credentials=MetaCredentials(
            instagram_account_id="1",
            facebook_page_id="2",
            facebook_page_access_token="tok",
        ),
    )


@pytest.fixture
def profile(tmp_path: Path) -> Profile:
    return make_profile(tmp_path)


def repository_for(profile: Profile) -> FilesystemProfileRepository:
    """
    A repository over the throwaway tree `make_profile` built, which lays out
    <root>/<name>/<platform>/inputs. Tests never point one at real resources/.
    """
    root = profile.platform_info[Platform.META].inputs_path.parents[2]
    return FilesystemProfileRepository(root)


def write_persona(profile: Profile, text: str) -> None:
    """The shared persona file sits in the profile folder, next to the platforms."""
    profile_dir = profile.platform_info[Platform.META].inputs_path.parents[1]
    (profile_dir / "persona.md").write_text(text, encoding="utf-8")


def make_chapter(
    start_week: str,
    weeks: int = 1,
    arc_start_week: str | None = None,
    situation: str = "Something happens",
    meta_angle: str = "Meta angle",
    fanvue_angle: str = "Fanvue angle",
) -> Chapter:
    """A valid `Chapter` covering `weeks` consecutive weeks from `start_week`,
    with distinct-but-deterministic per-day text so tests can assert on it."""
    start = date.fromisoformat(start_week)
    days = [
        ChapterDay(
            date=(start + timedelta(days=i)).isoformat(),
            situation=f"{situation} (day {i + 1})",
            angles={
                Platform.META.value: f"{meta_angle} (day {i + 1})",
                Platform.FANVUE.value: f"{fanvue_angle} (day {i + 1})",
            },
        )
        for i in range(weeks * 7)
    ]
    return Chapter(
        arc_start_week=arc_start_week or start_week,
        start_week=start_week,
        weeks=weeks,
        title="Test chapter",
        summary="Test chapter summary",
        days=days,
    )


def write_chapter(
    profile: Profile, start_week: str, weeks: int = 1, **kwargs
) -> Chapter:
    """Saves a `make_chapter(...)` into the profile's repository, covering
    `start_week`'s week (and any following weeks of a multi-week chapter)."""
    chapter = make_chapter(start_week, weeks, **kwargs)
    repository_for(profile).save_chapter(profile, chapter)
    return chapter


def make_arc(start_week: str, weeks: int = 12) -> Arc:
    return Arc(
        start_week=start_week,
        weeks=weeks,
        title="Test arc",
        premise="premise",
        goal="goal",
        conflict="conflict",
        starting_point="start",
        ending_point="end",
        summary="Test arc summary",
    )


def write_arc(profile: Profile, start_week: str, weeks: int = 12) -> Arc:
    """Saves a `make_arc(...)` into the profile's repository, covering
    `weeks` consecutive weeks from `start_week`."""
    arc = make_arc(start_week, weeks)
    repository_for(profile).save_arc(profile, arc)
    return arc
