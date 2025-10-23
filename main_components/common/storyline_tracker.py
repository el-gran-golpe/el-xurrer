from pathlib import Path
from datetime import datetime
from loguru import logger
import json
from typing import Any

from llm.base_llm import BaseLLM
from main_components.common.profile import Profile
from main_components.common.types import Platform


class StorylineTracker:
    """Tracks and updates storyline progression for profiles."""

    def __init__(self, profile: Profile, platform: Platform, llm: BaseLLM):
        self.profile: Profile = profile
        self.platform: Platform = platform
        self.llm: BaseLLM = llm
        # Input/output paths
        self.inputs_path: Path = profile.platform_info[self.platform].inputs_path
        self.outputs_path: Path = profile.platform_info[self.platform].outputs_path
        # Initial_conditions.md file
        self.initial_conditions_file: Path = self.inputs_path / "initial_conditions.md"
        self.storyline: str = self.initial_conditions_file.read_text(
            encoding="utf-8"
        ).strip()
        # Planning.json file path
        name_parts = self.profile.name.replace("_", " ").split()
        initials = "".join([word[0].lower() for word in name_parts[:2]])
        self.planning_file: Path = self.outputs_path / f"{initials}_planning.json"

    def update_storyline(self) -> None:
        """Main method to update storyline after planning generation."""
        try:
            logger.info(
                "Updating storyline for {} on {}...",
                self.profile.name,
                self.platform,
            )
            planning_data: dict[str, Any] = self._read_planning_file()
            captions: list[str] = self._extract_all_captions(planning_data)
            logger.debug("Found {} captions to summarize", len(captions))
            summary: str = self._generate_summary(captions)
            logger.debug("Generated summary: {}", summary)
            self._append_to_initial_conditions(summary)
            logger.success("Storyline updated for {}", self.profile.name)

        except Exception as e:
            logger.error("Failed to update storyline: {}", e)
            raise

    def _read_planning_file(self) -> dict[str, Any]:
        with open(self.planning_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _extract_all_captions(self, planning_data: dict[str, Any]) -> list[str]:
        """Extract all captions from the json planning data."""
        captions: list[str] = []
        for _, week_data in planning_data.items():
            for day in week_data:
                if "posts" in day:
                    for post in day["posts"]:
                        if "caption" in post:
                            captions.append(post["caption"])
        return captions

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

    def _append_to_initial_conditions(self, summary: str) -> None:
        """Append the summary to initial_conditions.md with timestamp."""
        timestamp: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry: str = (
            f"\n\n---\n**[{timestamp}] - Recent Content Summary:**\n{summary}\n"
        )
        with open(self.initial_conditions_file, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.debug("Appended storyline summary to {}", self.initial_conditions_file)
