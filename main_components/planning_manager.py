import json
from pathlib import Path
from typing import Any
from loguru import logger

from llm.api_keys import api_keys
from llm.base_llm import BaseLLM
from llm.routing.model_router import ModelRouter
from main_components.common.types import Platform
from main_components.common.types import Profile
from main_components.common.storyline_tracker import StorylineTracker


def _save_planning(planning: dict[str, Any], output_path: Path) -> None:
    try:
        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(planning, file, indent=4, ensure_ascii=False)
        logger.success(f"Planning saved to: {output_path}")
    except Exception as e:
        logger.error(f"Error writing to file {output_path}: {e}")
        raise


class PlanningManager:
    """Universal planning manager for generating content across different platforms."""

    def __init__(
        self,
        template_profiles: list[Profile],
        platform_name: Platform,
        use_initial_conditions: bool,
    ):
        self.template_profiles = template_profiles
        self.platform_name = platform_name
        self.use_initial_conditions = use_initial_conditions

    def plan(self) -> None:
        github_api_keys: list[str] = api_keys.extract_github_keys()
        openai_api_keys: list[str] = api_keys.extract_openai_keys()

        model_router = ModelRouter(
            github_api_keys=github_api_keys,
            deepseek_api_key=openai_api_keys,
        )
        # None means scan all available models
        model_router.initialize_model_classifiers(models_to_scan=None)

        for profile in self.template_profiles:
            inputs_path = profile.platform_info[self.platform_name].inputs_path
            outputs_path = profile.platform_info[self.platform_name].outputs_path

            storyline: str = (
                (inputs_path / "initial_conditions.md")
                .read_text(encoding="utf-8")
                .strip()
                if self.use_initial_conditions
                else ""
            )

            # It is a bit odd because I am passing the .json of prompts
            # as a Path, but the previous_storyline as the full text itself (str).
            # Anyway, I'll take it like this for now.
            llm = BaseLLM(
                prompt_json_template_path=inputs_path / f"{profile.name}.json",
                previous_storyline=storyline,
                platform_name=self.platform_name,
                model_router=model_router,
            )
            planning = llm.generate_dict_from_prompts()

            output_filename = "".join(word[0] for word in profile.name.split("_"))
            _save_planning(
                planning,
                outputs_path / f"{output_filename}_planning.json",
            )

            # Update storyline after planning generation
            storyline_tracker = StorylineTracker(profile, self.platform_name, llm)
            storyline_tracker.update_storyline()
