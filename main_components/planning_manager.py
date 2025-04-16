import os
import json
from typing import Union
from typing_extensions import LiteralString

from main_components.base_main import BaseMain
from main_components.constants import Platform
from main_components.profile import Profile


class PlanningManager(BaseMain):
    """Universal planning manager for generating content across different platforms."""

    def __init__(
        self,
        # planning_template_folder: str,
        template_profiles: list[Profile],
        platform_name: Platform,
        llm_module_path: str,
        llm_class_name: str,
        llm_method_name: str,
        use_initial_conditions=True,
    ):
        """
        Initialize the planning manager.

        Args:
            planning_template_folder: Path to the folder containing planning templates
            platform_name: Name of the platform (instagram, fanvue, etc.)
            llm_module_path: Path to the LLM module (e.g., "llm.instagram.instagram_llm")
            llm_class_name: Name of the LLM class (e.g., "InstagramLLM")
            llm_method_name: Name of the generation method to call (e.g., "generate_instagram_planning")
            use_initial_conditions: Whether to use initial_conditions.md files (default: True)
        """
        super().__init__(platform_name)
        # self.planning_template_folder = planning_template_folder
        self.template_profiles = template_profiles
        self.llm_module_path = llm_module_path
        self.llm_class_name = llm_class_name
        self.llm_method_name = llm_method_name
        self.use_initial_conditions = use_initial_conditions

    def get_initial_conditions_path(
        self, inputs_path
    ) -> Union[str, LiteralString, bytes]:
        """Get the path to initial conditions file."""
        return os.path.join(
            # self.planning_template_folder,
            inputs_path,
            "initial_conditions.md",  # THOUGHTS: this is hardcoded
        )

    def read_initial_conditions(
        self, file_path: Union[str, LiteralString, bytes]
    ) -> str:
        """Read initial conditions from a markdown file."""
        try:
            return self.read_file_content(file_path, file_type="text")
        except (FileNotFoundError, IOError) as e:
            raise IOError(f"{e}")

    def read_previous_storyline(
        self, file_path: Union[str, LiteralString, bytes]
    ) -> str:
        """Read previous storyline from a markdown file."""
        return ""

    def _get_llm_instance(self):
        """Dynamically import and create an instance of the specified LLM class."""
        return self.load_dynamic_class(self.llm_module_path, self.llm_class_name)

    def generate_planning_with_llm(self, template_path, previous_storyline):
        """Generate planning content using the configured LLM."""
        llm = self._get_llm_instance()
        llm_method = getattr(llm, self.llm_method_name)

        return llm_method(
            prompt_template_path=template_path, previous_storyline=previous_storyline
        )

    def save_planning(self, planning, output_path):
        """Save planning content to file."""
        success = self.write_to_file(
            content=planning, file_path=output_path, file_type="json"
        )
        if success:
            print(f"Planning saved to: {output_path}")

    def plan(self):
        """Main method to generate planning."""
        for profile in self.template_profiles:
            inputs_path = profile.platform_info[self.platform_name].inputs_path
            outputs_path = profile.platform_info[self.platform_name].outputs_path
            # Read previous storyline if needed
            initial_conditions_path = self.get_initial_conditions_path(inputs_path)
            storyline = self.read_initial_conditions(initial_conditions_path)
            try:
                # TODO: check if the previous_storyline is correctly implemented, that is,
                #  it's not being used when the initial conditions are set to false.
                previous_storyline = self.read_previous_storyline(
                    initial_conditions_path
                )
                storyline.join(previous_storyline)
            except (AssertionError, IOError) as e:
                print(
                    f"\033[91mWarning: {e}. Proceeding with empty previous storyline.\033[0m"
                )

            # Generate planning
            while True:
                try:
                    planning = self.generate_planning_with_llm(
                        inputs_path.joinpath(profile.name + ".json"), storyline
                    )

                    # Save planning
                    output_filename = "".join(
                        [word[0] for word in profile.name.split("_")]
                    )
                    self.save_planning(
                        planning,
                        outputs_path.joinpath(output_filename + "_planning.json"),
                    )
                    break
                except (json.decoder.JSONDecodeError, TypeError) as e:
                    print(f"Error decoding JSON or TypeError: {e}. Retrying...")
