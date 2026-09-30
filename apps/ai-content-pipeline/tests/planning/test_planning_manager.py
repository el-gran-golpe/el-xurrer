import json
from pathlib import Path

import pytest

from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import repository_for
from ai_content_pipeline.planning import planning_manager as planning_manager_module
from ai_content_pipeline.planning.planning_manager import PlanningManager

PLANNING = {"week_1": [{"day": 1, "posts": [{"caption": "hi"}]}]}


class FakeModelRouter:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def initialize_model_classifiers(self, **kwargs):
        pass


class FakeBaseLLM:
    instances: list["FakeBaseLLM"] = []
    reply: dict = PLANNING

    def __init__(self, prompts, previous_storyline, platform_name, model_router):
        self.prompts = prompts
        self.previous_storyline = previous_storyline
        self.platform_name = platform_name
        self.model_router = model_router
        FakeBaseLLM.instances.append(self)

    def generate_dict_from_prompts(self) -> dict:
        return FakeBaseLLM.reply

    def generate_simple_text(self, prompt: str) -> str:
        return "a short summary"


@pytest.fixture(autouse=True)
def _fake_llm_boundary(monkeypatch):
    """
    Fakes the 3 external boundaries `plan()` talks to (ModelRouter, api_keys,
    BaseLLM) so these tests exercise only the repository wiring, not the LLM
    stack.
    """
    FakeBaseLLM.instances = []
    FakeBaseLLM.reply = PLANNING
    monkeypatch.setattr(planning_manager_module, "ModelRouter", FakeModelRouter)
    monkeypatch.setattr(planning_manager_module, "BaseLLM", FakeBaseLLM)
    monkeypatch.setattr(
        planning_manager_module.api_keys, "extract_openrouter_keys", lambda: ["key"]
    )
    monkeypatch.setattr(
        planning_manager_module.api_keys, "extract_deepseek_key", lambda: "key"
    )


def _plan(profile: Profile, platform: Platform, use_initial_conditions=True) -> None:
    PlanningManager(
        template_profiles=[profile],
        platform_name=platform,
        use_initial_conditions=use_initial_conditions,
    ).plan()


def _initial_conditions(profile: Profile) -> Path:
    return profile.platform_info[Platform.META].inputs_path / "initial_conditions.md"


def test_plan_feeds_the_platform_prompts_and_initial_conditions_to_the_llm(
    profile: Profile,
):
    _initial_conditions(profile).write_text("the story so far", encoding="utf-8")

    _plan(profile, Platform.META)

    llm = FakeBaseLLM.instances[0]
    assert llm.previous_storyline == "the story so far"
    assert [p.cache_key for p in llm.prompts] == ["week"]


def test_plan_skips_initial_conditions_when_disabled(profile: Profile):
    _plan(profile, Platform.META, use_initial_conditions=False)

    assert FakeBaseLLM.instances[0].previous_storyline == ""


def test_plan_saves_the_generated_week_plan(profile: Profile):
    _plan(profile, Platform.FANVUE)

    saved = repository_for(profile).get_week_plan(profile, Platform.FANVUE)
    assert saved == WeekPlan.from_planning_dict(PLANNING)


def test_plan_rejects_an_llm_reply_that_is_not_a_week_plan(profile: Profile):
    FakeBaseLLM.reply = {"week_1": [{"posts": []}]}  # no "day"
    outputs = profile.platform_info[Platform.META].outputs_path

    with pytest.raises(ValueError):
        _plan(profile, Platform.META)

    assert list(outputs.iterdir()) == []  # nothing half-saved


def test_plan_appends_the_storyline_summary(profile: Profile):
    before = _initial_conditions(profile).read_text(encoding="utf-8")

    _plan(profile, Platform.META)

    after = _initial_conditions(profile).read_text(encoding="utf-8")
    assert after.startswith(before)
    assert "a short summary" in after


def test_saved_file_keeps_the_week_keyed_shape_consumers_read(profile: Profile):
    _plan(profile, Platform.META)

    outputs = profile.platform_info[Platform.META].outputs_path
    assert json.loads((outputs / "h_planning.json").read_text("utf-8")) == {
        "week_1": [
            {
                "day": 1,
                "posts": [
                    {
                        "title": "",
                        "caption": "hi",
                        "hashtags": [],
                        "upload_time": "",
                        "images": [],
                    }
                ],
            }
        ]
    }
