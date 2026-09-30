import json
from pathlib import Path

import pytest

from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.types import Platform, Profile
from conftest import repository_for, write_persona
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
        repository=repository_for(profile),
    ).plan()


def _initial_conditions(profile: Profile) -> Path:
    return profile.platform_info[Platform.META].inputs_path / "initial_conditions.md"


def test_plan_feeds_the_shared_persona_and_the_platform_notes_to_the_llm(
    profile: Profile,
):
    write_persona(profile, "28, grew up in Porto")
    _initial_conditions(profile).write_text("keep it SFW", encoding="utf-8")

    _plan(profile, Platform.META)

    llm = FakeBaseLLM.instances[0]
    assert llm.previous_storyline == (
        "## Who she is\n28, grew up in Porto\n\n## Platform notes\nkeep it SFW"
    )
    assert [p.cache_key for p in llm.prompts] == ["week"]


def test_no_initial_conditions_drops_the_platform_notes_but_keeps_the_persona(
    profile: Profile,
):
    write_persona(profile, "28, grew up in Porto")
    _initial_conditions(profile).write_text("keep it SFW", encoding="utf-8")

    _plan(profile, Platform.META, use_initial_conditions=False)

    storyline = FakeBaseLLM.instances[0].previous_storyline
    assert storyline == "## Who she is\n28, grew up in Porto"


def test_sections_the_profile_has_not_got_yet_are_left_out(profile: Profile):
    _initial_conditions(profile).write_text("keep it SFW", encoding="utf-8")

    _plan(profile, Platform.META)

    storyline = FakeBaseLLM.instances[0].previous_storyline
    assert storyline == "## Platform notes\nkeep it SFW"


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


def test_planning_never_writes_back_into_the_profile_inputs(profile: Profile):
    """
    Planning used to append its own summary to initial_conditions.md, which is
    what broke resume: the file it hashed changed on every run.
    """
    before = _initial_conditions(profile).read_text(encoding="utf-8")

    _plan(profile, Platform.META)

    assert _initial_conditions(profile).read_text(encoding="utf-8") == before


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
