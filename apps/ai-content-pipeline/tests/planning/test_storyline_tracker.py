from ai_content_pipeline.domain.plans import DayPlan, PostPlan, WeekPlan
from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.planning.storyline_tracker import StorylineTracker

PLAN = WeekPlan(
    week="week_1",
    days=[
        DayPlan(
            day=1,
            posts=[
                PostPlan(caption="sunny beach day"),
                PostPlan(caption="coffee with friends"),
                PostPlan(title="no caption"),
            ],
        )
    ],
)


class FakeLLM:
    def __init__(self, summary: str = "a short recap"):
        self.summary = summary
        self.prompts: list[str] = []

    def generate_simple_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.summary


def test_update_storyline_summarizes_the_plan_captions_and_appends_it(
    profile: Profile,
):
    path = profile.platform_info[Platform.META].inputs_path / "initial_conditions.md"
    before = path.read_text(encoding="utf-8")
    llm = FakeLLM(summary="beach days and coffee")

    StorylineTracker(profile, Platform.META, llm).update_storyline(PLAN)

    after = path.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert "beach days and coffee" in after
    assert "sunny beach day\n\ncoffee with friends\n\n" in llm.prompts[0]
