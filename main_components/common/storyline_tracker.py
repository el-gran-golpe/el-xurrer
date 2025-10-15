from pathlib import Path
from datetime import datetime
from loguru import logger
import json

from llm.base_llm import BaseLLM
from llm.routing.model_router import ModelRouter
from main_components.common.profile import Profile
from main_components.common.types import Platform


class StorylineTracker:
    """Tracks and updates storyline progression for profiles."""

    def __init__(self, profile: Profile, platform: Platform, model_router: ModelRouter):
        self.profile = profile
        self.platform = platform
        self.model_router = model_router

    def update_storyline(self):
        """Main method to update storyline after planning generation."""
        try:
            logger.info(
                "Updating storyline for {} on {}...",
                self.profile.name,
                self.platform.value,
            )
            planning_data = self._read_planning_file()
            captions = self._extract_all_captions(planning_data)
            logger.debug("Found {} captions to summarize", len(captions))
            summary = self._generate_summary(captions)
            logger.debug("Generated summary: {}", summary)
            self._append_to_initial_conditions(summary)
            logger.success("Storyline updated for {}", self.profile.name)

        except Exception as e:
            logger.error("Failed to update storyline: {}", e)
            raise

    def _read_planning_file(self) -> dict:
        """Read the planning JSON file for the profile."""
        # Get initials from profile name (e.g., "laura_vigne" -> "lv")
        name_parts = self.profile.name.split("_")
        initials = f"{name_parts[0][0]}{name_parts[1][0]}".lower()

        planning_file = (
            Path("resources")
            / self.profile.name
            / self.platform.value
            / "outputs"
            / f"{initials}_planning.json"
        )

        with open(planning_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _extract_all_captions(self, planning_data: dict) -> list[str]:
        """Extract all captions from the json planning data."""
        captions = []
        for _, week_data in planning_data.items():
            for day in week_data:
                if "posts" in day:
                    for post in day["posts"]:
                        if "caption" in post:
                            captions.append(post["caption"])
        return captions

    def _generate_summary(self, captions: list[str]) -> str:
        """Generate a concise summary of all captions using LLM."""
        captions_text = "\n\n".join(captions)
        prompt = (
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

        # TODO: Do we really need all of this info here?
        platform_info = self.profile.platform_info[self.platform]
        inputs_path = platform_info.inputs_path
        storyline_path = inputs_path / "initial_conditions.md"
        storyline = (
            storyline_path.read_text(encoding="utf-8").strip()
            if storyline_path.exists()
            else ""
        )

        llm = BaseLLM(
            prompt_json_template_path=inputs_path / f"{self.profile.name}.json",
            previous_storyline=storyline,
            platform_name=self.platform,
            model_router=self.model_router,
        )
        return llm.generate_simple_text(prompt)

    def _append_to_initial_conditions(self, summary: str):
        """Append the summary to initial_conditions.md with timestamp."""
        initial_conditions_file = (
            Path("resources")
            / self.profile.name
            / f"{self.profile.name}_initial_conditions.md"
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entry = f"\n\n---\n**[{timestamp}] - Recent Content Summary:**\n{summary}\n"

        with open(initial_conditions_file, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info("Appended storyline summary to {}", initial_conditions_file)
