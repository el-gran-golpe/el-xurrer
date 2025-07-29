import json
from pathlib import Path
from typing import Any
from loguru import logger

from main_components.common.constants import Platform
from main_components.common.profile import Profile
from llm.meta_llm import MetaLLM
from llm.fanvue_llm import FanvueLLM


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

    _llm_map: dict[Platform, tuple[type, str]] = {
        Platform.META: (MetaLLM, "generate_meta_planning"),
        Platform.FANVUE: (FanvueLLM, "generate_fanvue_planning"),
    }

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

            planning = self._generate_planning_with_llm(
                inputs_path / f"{profile.name}.json", storyline
            )
            output_filename = "".join(word[0] for word in profile.name.split("_"))
            _save_planning(
                planning,
                outputs_path / f"{output_filename}_planning.json",
            )

    def _generate_planning_with_llm(
        self, template_path: Path, previous_storyline: str
    ) -> dict[str, Any]:
        llm_class, method_name = self._llm_map[self.platform_name]
        llm = llm_class()
        llm_method = getattr(llm, method_name)
        return llm_method(
            prompt_template_path=template_path, previous_storyline=previous_storyline
        )
