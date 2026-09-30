from loguru import logger

from ai_content_pipeline.llm.base_llm import BaseLLM
from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.paths import RESOURCES_DIR
from ai_content_pipeline.profiles.repository import (
    FilesystemProfileRepository,
    ProfileRepository,
)


class StorylineTracker:
    """Tracks and updates storyline progression for profiles."""

    def __init__(
        self,
        profile: Profile,
        platform: Platform,
        llm: BaseLLM,
        repository: ProfileRepository | None = None,
    ):
        self.profile: Profile = profile
        self.platform: Platform = platform
        self.llm: BaseLLM = llm
        self.repository: ProfileRepository = repository or FilesystemProfileRepository(
            RESOURCES_DIR
        )

    def update_storyline(self, plan: WeekPlan) -> None:
        """Main method to update storyline after planning generation."""
        try:
            logger.info(
                "Updating storyline for {} on {}...",
                self.profile.name,
                self.platform,
            )
            captions: list[str] = self._extract_all_captions(plan)
            logger.debug("Found {} captions to summarize", len(captions))
            summary: str = self._generate_summary(captions)
            logger.debug("Generated summary: {}", summary)
            self.repository.add_storyline_summary(self.profile, self.platform, summary)
            logger.success("Storyline updated for {}", self.profile.name)

        except Exception as e:
            logger.error("Failed to update storyline: {}", e)
            raise

    def _extract_all_captions(self, plan: WeekPlan) -> list[str]:
        return [post.caption for day in plan.days for post in day.posts if post.caption]

    def _generate_summary(self, captions: list[str]) -> str:
        """Generate a concise summary of all captions using and LLMModel."""
        captions_text: str = "\n\n".join(captions)
        prompt: str = (
            "You are analyzing social media captions for an influencer's content planning.\n\n"
            "Read all the following captions and create a VERY SHORT summary (2-3 sentences max) that captures:\n"
            "- The main themes and topics covered\n"
            "- The progression or journey highlighted\n"
            "- Any key activities or milestones mentioned\n\n"
            "Keep it concise and focused on storyline progression.\n\n"
            "Captions:\n"
            f"{captions_text}\n\n"
            "Summary:"
        )
        return self.llm.generate_simple_text(prompt)
