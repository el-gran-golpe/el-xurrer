import os
import json
import importlib

class PlanningManager:
    """Universal planning manager for generating content across different platforms."""
    
    def __init__(self, planning_template_folder, platform_name, llm_module_path, llm_class_name, llm_method_name):
        """
        Initialize the planning manager.
        
        Args:
            planning_template_folder: Path to the folder containing planning templates
            platform_name: Name of the platform (instagram, fanvue, etc.)
            llm_module_path: Path to the LLM module (e.g., "llm.instagram.instagram_llm")
            llm_class_name: Name of the LLM class (e.g., "InstagramLLM")
            llm_method_name: Name of the generation method to call (e.g., "generate_instagram_planning")
        """
        self.planning_template_folder = planning_template_folder
        self.platform_name = platform_name
        self.llm_module_path = llm_module_path
        self.llm_class_name = llm_class_name
        self.llm_method_name = llm_method_name
        
    def find_available_plannings(self):
        """Find all available planning templates inside the resources folder."""
        available_plannings = []        
        
        for profile_dir in os.listdir(self.planning_template_folder):
            profile_path = os.path.join(self.planning_template_folder, profile_dir)
            if os.path.isdir(profile_path):
                inputs_path = os.path.join(profile_path, "inputs")
                if os.path.isdir(inputs_path):
                    for file_name in os.listdir(inputs_path):
                        if file_name.endswith('.json'):
                            template_path = os.path.join(inputs_path, file_name)
                            available_plannings.append((profile_dir, template_path))    
        return available_plannings
    
    def prompt_user_selection(self, available_plannings):
        """Prompt the user to select templates."""
        if not available_plannings:
            print(f"No planning templates found for {self.platform_name}.")
            return []

        print(f"Available {self.platform_name} planning templates:")
        for i, (profile, template) in enumerate(available_plannings):
            print(f"{i + 1}: {profile}")
        
        template_input = input("Select template numbers separated by commas or type 'all' to process all: ")
        if template_input.lower() == 'all':
            return available_plannings
        else:
            template_indices = [int(index.strip()) - 1 for index in template_input.split(',')]
            for index in template_indices:
                assert 0 <= index < len(available_plannings), f"Invalid template number: {index + 1}"
            return [available_plannings[index] for index in template_indices]
    
    def check_existing_files(self, selected_templates):
        """Check which templates already have output files."""
        existing_files = []
        not_existing_files = []
        
        for profile_name, template_path in selected_templates:
            profile_initials = ''.join([word[0] for word in profile_name.split('_')])
            planning_filename = f"{profile_initials}_planning.json"
            
            output_path = os.path.join(self.planning_template_folder, profile_name, "outputs")
            os.makedirs(output_path, exist_ok=True)
            
            full_output_path = os.path.join(output_path, planning_filename)
            
            if os.path.isfile(full_output_path):
                existing_files.append((profile_name, template_path, full_output_path))
            else:
                not_existing_files.append((profile_name, template_path, full_output_path))
            
        return existing_files, not_existing_files
    
    def prompt_overwrite(self, existing_files):
        """Ask user if they want to overwrite existing files."""
        if not existing_files:
            return False
            
        print("\nThe following planning files already exist and would be overwritten:")
        for (_, _, fpath) in existing_files:
            print(f"  {fpath}")
        
        overwrite_input = input("Do you want to overwrite these existing files? (y/n): ")
        return overwrite_input.lower() in ('y', 'yes')
    
    def get_initial_conditions_path(self, profile_name):
        """Get the path to initial conditions file."""
        return os.path.join(self.planning_template_folder, profile_name, "inputs", "initial_conditions.md")
    
    def read_initial_conditions(self, file_path: str) -> str:
        """Read initial conditions from a markdown file."""
        assert isinstance(file_path, str), "file_path must be a string"
        assert os.path.exists(file_path), f"File does not exist: {file_path}"

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read().strip()
        except Exception as e:
            raise IOError(f"Error reading file {file_path}: {e}")

        return content if content else ""
    
    def _get_llm_instance(self):
        """Dynamically import and create an instance of the specified LLM class."""
        try:
            # Import the module
            llm_module = importlib.import_module(self.llm_module_path)
            
            # Get the class from the module
            llm_class = getattr(llm_module, self.llm_class_name)
            
            # Create an instance of the class
            return llm_class()
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to import {self.llm_class_name} from {self.llm_module_path}: {str(e)}")
    
    def generate_planning_with_llm(self, template_path, previous_storyline):
        """Generate planning content using the configured LLM."""
        llm = self._get_llm_instance()
        llm_method = getattr(llm, self.llm_method_name)
        
        return llm_method(
            prompt_template_path=template_path,
            previous_storyline=previous_storyline
        )
    
    def save_planning(self, planning, output_path):
        """Save planning content to file."""
        with open(output_path, 'w', encoding='utf-8') as file:
            json.dump(planning, file, indent=4, ensure_ascii=False)
        print(f"Planning saved to: {output_path}")
    
    def generate(self):
        """Main method to generate planning."""
        assert os.path.isdir(self.planning_template_folder), \
            f"Planning template folder not found: {self.planning_template_folder}"
        
        # 1) Find available planning templates
        available_plannings = self.find_available_plannings()             
        print("\nFound planning templates:")
        for i, (profile, template) in enumerate(available_plannings):
            print(f"{i + 1}. Profile: \033[92m{profile}\033[0m")  # prints only profile in green color
            print(f"   Template path: {template}")
        print()
        if not available_plannings:
            return
        
        # 2) Let user select templates
        selected_templates = self.prompt_user_selection(available_plannings)
        if not selected_templates:
            return
        
        # 3) Check which selected templates have existing output files
        existing_files, not_existing_files = self.check_existing_files(selected_templates)
        
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
            # Read previous storyline
            initial_conditions_path = self.get_initial_conditions_path(profile_name)
            previous_storyline = self.read_initial_conditions(initial_conditions_path)
            
            # Generate planning
            while True:
                try:
                    planning = self.generate_planning_with_llm(template_path, previous_storyline)
                    break
                except (json.decoder.JSONDecodeError, TypeError) as e:
                    print(f"Error decoding JSON or TypeError: {e}. Retrying...")
                    continue
            
            # Save planning
            self.save_planning(planning, output_path)
