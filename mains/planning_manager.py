import os
import json
import importlib
from mains.base_main import BaseMain


class PlanningManager(BaseMain):
    """Universal planning manager for generating content across different platforms."""

    def __init__(
        self,
        planning_template_folder,
        platform_name,
        llm_module_path,
        llm_class_name,
        llm_method_name,
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
        self.planning_template_folder = planning_template_folder
        self.llm_module_path = llm_module_path
        self.llm_class_name = llm_class_name
        self.llm_method_name = llm_method_name
        self.use_initial_conditions = use_initial_conditions

    def find_available_plannings(self):
        """Find all available planning templates inside the resources folder."""

        def search_pattern(profile_dir, profile_path):
            inputs_path = os.path.join(profile_path, "inputs")
            if os.path.isdir(inputs_path):
                for file_name in os.listdir(inputs_path):
                    if file_name.endswith(".json"):
                        template_path = os.path.join(inputs_path, file_name)
                        return (profile_dir, template_path)
            return None

        return self.find_available_items(
            base_path=self.planning_template_folder,
            search_pattern=search_pattern,
            item_type="planning templates",
        )

    def prompt_user_selection(self, available_plannings):
        """Prompt the user to select templates."""
        not_found_message = f"No planning templates found for {self.platform_name}."

        return super().prompt_user_selection(
            available_items=available_plannings,
            item_type="templates",
            allow_multiple=True,
            not_found_message=not_found_message,
        )

    def check_existing_files(self, selected_templates):
        """Check which templates already have output files."""

        def output_path_generator(template_item):
            profile_name, template_path = template_item
            profile_initials = "".join([word[0] for word in profile_name.split("_")])
            planning_filename = f"{profile_initials}_planning.json"

            output_path = os.path.join(
                self.planning_template_folder, profile_name, "outputs"
            )
            self.create_directory(output_path)

            return os.path.join(output_path, planning_filename)

        return super().check_existing_files(selected_templates, output_path_generator)

    def prompt_overwrite(self, existing_files):
        """Ask user if they want to overwrite existing files."""
        return super().prompt_overwrite(existing_files, path_index=2)

    def get_initial_conditions_path(self, profile_name):
        """Get the path to initial conditions file."""
        return os.path.join(
            self.planning_template_folder,
            profile_name,
            "inputs",
            "initial_conditions.md",
        )

    def read_initial_conditions(self, file_path: str) -> str:
        """Read initial conditions from a markdown file."""
        try:
            return self.read_file_content(file_path, file_type="text")
        except (FileNotFoundError, IOError) as e:
            raise IOError(f"{e}")

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
        success = self.write_to_file(planning, output_path, file_type="json")
        if success:
            print(f"Planning saved to: {output_path}")

    def plan(self):
        """Main method to generate planning."""
        assert os.path.isdir(self.planning_template_folder), (
            f"Planning template folder not found: {self.planning_template_folder}"
        )

        # 1) Find available planning templates
        available_plannings = self.find_available_plannings()
        print("\nFound planning templates:")
        for i, (profile, template) in enumerate(available_plannings):
            print(
                f"{i + 1}. Profile: \033[92m{profile}\033[0m"
            )  # prints only profile in green color
            print(f"   Template path: {template}")
        print()
        if not available_plannings:
            return

        # 2) Let user select templates
        selected_templates = self.prompt_user_selection(available_plannings)
        if not selected_templates:
            return

        # 3) Check which selected templates have existing output files
        existing_files, not_existing_files = self.check_existing_files(
            selected_templates
        )

        # 4) Ask if user wants to overwrite existing files
        overwrite_all = self.prompt_overwrite(existing_files)

        # 5) Prepare final list of templates to process
        final_templates = []
        for item in existing_files:
            if overwrite_all:
                final_templates.append(item)
            else:
                print(f"Skipping overwrite for {item[2]}")

        # Add the files that don't exist yet (always processed)
        final_templates.extend(not_existing_files)

        # 6) Process each template
        for profile_name, template_path, output_path in final_templates:
            # Read previous storyline if needed
            previous_storyline = ""
            if self.use_initial_conditions:
                initial_conditions_path = self.get_initial_conditions_path(profile_name)
                try:
                    previous_storyline = self.read_initial_conditions(
                        initial_conditions_path
                    )
                except (AssertionError, IOError) as e:
                    print(
                        f"\033[91mWarning: {e}. Proceeding with empty previous storyline.\033[0m"
                    )

            # Generate planning
            while True:
                try:
                    # TODO: check if the previous_storyline is correctly implemented, that is,
                    # it's not being used when the initial conditions are set to false.
                    planning = self.generate_planning_with_llm(
                        template_path, previous_storyline
                    )
                    break
                except (json.decoder.JSONDecodeError, TypeError) as e:
                    print(f"Error decoding JSON or TypeError: {e}. Retrying...")
                    continue

            # Save planning
            self.save_planning(planning, output_path)
