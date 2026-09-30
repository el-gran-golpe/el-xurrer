import json
from pathlib import Path

import pytest

from ai_content_pipeline.domain.types import (
    MetaCredentials,
    Platform,
    PlatformInfo,
    Profile,
)
from ai_content_pipeline.profiles.repository import FilesystemProfileRepository

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
