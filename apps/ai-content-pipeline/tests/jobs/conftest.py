from pathlib import Path

import pytest

from ai_content_pipeline.domain.types import (
    MetaCredentials,
    Platform,
    PlatformInfo,
    Profile,
)
from ai_content_pipeline.jobs.store import JobStore


def make_profile(tmp_path: Path, name: str = "haru") -> Profile:
    """A profile whose per-platform input/output dirs exist, as PlatformInfo requires."""
    platform_info = {}
    for platform in Platform:
        inputs = tmp_path / name / platform.value / "inputs"
        outputs = tmp_path / name / platform.value / "outputs"
        inputs.mkdir(parents=True)
        outputs.mkdir(parents=True)
        (inputs / f"{name}.json").write_text('{"prompts": []}', encoding="utf-8")
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


@pytest.fixture
def store() -> JobStore:
    return JobStore(":memory:")
