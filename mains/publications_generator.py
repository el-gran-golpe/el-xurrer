import os
import json
import importlib
from slugify import slugify
from tqdm import tqdm
from utils.utils import get_valid_planning_file_names
from utils.exceptions import WaitAndRetryError
from time import sleep

class PublicationsGenerator:
    """Universal publications generator for creating posts across different platforms."""
    
    def __init__(self, post_template_folder, platform_name, llm_module_path, llm_class_name, llm_method_name):
        """
        Initialize the publications generator.
        
        Args:
            post_template_folder: Path to the folder containing post templates
            platform_name: Name of the platform (meta, fanvue, etc.)
            llm_module_path: Path to the LLM module (e.g., "llm.meta_llm")
            llm_class_name: Name of the LLM class (e.g., "MetaLLM")
            llm_method_name: Name of the generation method to call (e.g., "generate_meta_posts")
        """
        
        self.post_template_folder = post_template_folder
        self.platform_name = platform_name
        self.llm_module_path = llm_module_path
        self.llm_class_name = llm_class_name
        self.llm_method_name = llm_method_name
        
        # Determine the profiles base path based on platform
        self.profiles_base_path = os.path.join('.', 'resources', f'{platform_name}_profiles')
        
    def find_available_profiles(self):
        """Find all available profiles with planning files."""
        available_profiles = []
        
        # Look for planning files in the new structure
        if os.path.isdir(self.profiles_base_path):
            for profile_name in os.listdir(self.profiles_base_path):
                profile_path = os.path.join(self.profiles_base_path, profile_name)
                if os.path.isdir(profile_path):
                    outputs_path = os.path.join(profile_path, "outputs")
                    if os.path.isdir(outputs_path):
                        for file_name in os.listdir(outputs_path):
                            if file_name.endswith('_planning.json'):
                                planning_path = os.path.join(outputs_path, file_name)
                                available_profiles.append((profile_name, planning_path, "new"))
        
        # If no profiles found in new structure, check old structure for backward compatibility
        if not available_profiles and self.platform_name == "meta":
            old_outputs_path = os.path.join('resources', 'outputs', 'instagram_profiles')
            if os.path.isdir(old_outputs_path):
                for profile_name in os.listdir(old_outputs_path):
                    profile_path = os.path.join(old_outputs_path, profile_name)
                    if os.path.isdir(profile_path):
                        for file_name in os.listdir(profile_path):
                            if file_name.endswith('_planning.json'):
                                planning_path = os.path.join(profile_path, file_name)
                                available_profiles.append((profile_name, planning_path, "old"))
                                print(f"Warning: Using planning file from old structure: {planning_path}")
        
        return available_profiles
    
    def prompt_user_selection(self, available_profiles):
        """Prompt the user to select profiles."""
        if not available_profiles:
            print(f"No planning files found for {self.platform_name}, please generate a planning first")
            return []

        print(f"\nAvailable {self.platform_name} profiles with planning files:")
        for i, (profile, _, structure) in enumerate(available_profiles):
            print(f"{i + 1}: {profile} {'(old structure)' if structure == 'old' else ''}")
        
        profile_input = input("\nSelect profile numbers separated by commas or type 'all' to process all: ")
        if profile_input.lower() == 'all':
            return available_profiles
        else:
            try:
                profile_indices = [int(index.strip()) - 1 for index in profile_input.split(',')]
                for index in profile_indices:
                    assert 0 <= index < len(available_profiles), f"Invalid profile number: {index + 1}"
                return [available_profiles[index] for index in profile_indices]
            except (ValueError, AssertionError) as e:
                print(f"Error in selection: {e}")
                return []
    
    def _get_pipeline_class(self):
        """
        Dynamically import and return the appropriate pipeline class for the platform.
        """
        # Mapping of platform names to pipeline module paths
        pipeline_module_paths = {
            "meta": "pipeline.pipeline_meta",
            "fanvue": "pipeline.pipeline_fanvue"
        }
        
        # Mapping of platform names to pipeline class names
        pipeline_class_names = {
            "meta": "PipelineMeta",
            "fanvue": "PipelineFanvue"
        }
        
        # For backward compatibility
        if self.platform_name == "meta" and not self._module_exists(pipeline_module_paths["meta"]):
            pipeline_module_path = "pipeline.pipeline_instagram"
            pipeline_class_name = "PipelineInstagram"
            print("Warning: Using PipelineInstagram for backward compatibility")
        else:
            pipeline_module_path = pipeline_module_paths.get(self.platform_name)
            pipeline_class_name = pipeline_class_names.get(self.platform_name)
            
        if not pipeline_module_path or not pipeline_class_name:
            raise ImportError(f"No pipeline configured for platform: {self.platform_name}")
        
        try:
            # Import the module
            pipeline_module = importlib.import_module(pipeline_module_path)
            
            # Get the pipeline class
            pipeline_class = getattr(pipeline_module, pipeline_class_name)
            
            return pipeline_class
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to import {pipeline_class_name} from {pipeline_module_path}: {str(e)}")
    
    def _module_exists(self, module_path):
        """Check if a module exists without importing it."""
        try:
            importlib.util.find_spec(module_path)
            return True
        except (ImportError, AttributeError):
            return False
    
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
    
    def create_post_directories(self, profile_name, json_data_planning, output_folder):
        """Create directory structure for posts."""
        os.makedirs(output_folder, exist_ok=True)
        
        # Create folders for each week and day
        for week_key, week_data in json_data_planning.items():
            week_folder = os.path.join(output_folder, week_key)
            os.makedirs(week_folder, exist_ok=True)
            for day_data in week_data:
                day_folder = os.path.join(week_folder, f"day_{day_data['day']}")
                os.makedirs(day_folder, exist_ok=True)
                # Create a .txt file with the captions for the day
                captions_file_path = os.path.join(day_folder, "captions.txt")
                with open(captions_file_path, 'w', encoding='utf-8') as captions_file:
                    for post in day_data['posts']:
                        captions_file.write(post['caption'] + "\n\n")
                # Create a .txt file with the upload times for the day
                upload_times_file_path = os.path.join(day_folder, "upload_times.txt")
                with open(upload_times_file_path, 'w', encoding='utf-8') as upload_times_file:
                    for post in day_data['posts']:
                        upload_times_file.write(post['upload_time'] + "\n")
        
        return output_folder
    
    def generate_posts_from_planning(self, profile_name, planning_file_path, structure):
        """Generate posts for a specific profile based on planning data."""
        print(f"Processing profile: {profile_name}")

        # Load the planning data
        with open(planning_file_path, 'r', encoding='utf-8') as file:
            json_data_planning = json.load(file)
        
        # Determine output folder based on structure
        if structure == "new":
            output_folder = os.path.join(self.profiles_base_path, profile_name, 'outputs', 'posts')
        else:  # old structure
            output_folder = os.path.join('resources', 'outputs', 'instagram_profiles', profile_name, 'posts')
            # Also create folder in new structure for future use
            new_output_folder = os.path.join(self.profiles_base_path, profile_name, 'outputs', 'posts')
            os.makedirs(new_output_folder, exist_ok=True)
            print(f"Note: Future posts will be saved to new structure at: {new_output_folder}")
        
        # Create directory structure
        self.create_post_directories(profile_name, json_data_planning, output_folder)
        
        # Get the appropriate pipeline class
        PipelineClass = self._get_pipeline_class()
        
        # Generate posts for the planning data
        for week, days in tqdm(json_data_planning.items(), desc="Processing weeks"):
            week_folder = os.path.join(output_folder, week)
        
            for day_data in tqdm(days, desc=f"Processing days in {week}"):
                day_number = day_data['day']
                day_folder = os.path.join(week_folder, f"day_{day_number}")
        
                for post_data in day_data['posts']:
                    post_title = post_data.get('title', '')
                    post_slug = slugify(post_title) if post_title else f"post_{day_number}"
                    caption = post_data.get('caption', '')
                    hashtags = post_data.get('hashtags', [])
                    upload_time = post_data.get('upload_time', '')
        
                    # Prepare the post content
                    post_content = {
                        "post_title": post_title,
                        "post_slug": post_slug,
                        "caption": caption,
                        "hashtags": hashtags,
                        "upload_time": upload_time,
                        "images": []
                    }
        
                    # Add each image's description to the post content
                    for image in post_data.get('images', []):
                        post_content["images"].append({
                            "image_description": image.get('image_description', '')
                        })
        
                    # Run the pipeline for this single post with retrial mechanism
                    for retrial in range(25):
                        try:
                            PipelineClass(post_content=[post_content], output_folder=day_folder).generate_posts()
                            break
                        except WaitAndRetryError as e:
                            sleep_time = e.suggested_wait_time
                            hours, minutes, seconds = sleep_time // 3600, (sleep_time // 60) % 60, sleep_time % 60
                            for _ in tqdm(range(100),
                                      desc=f"Waiting {hours}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"):
                                sleep(sleep_time / 100)
    
    def generate(self):
        """Main method to generate posts."""
        assert os.path.isdir(self.profiles_base_path), \
            f"Profiles base path not found: {self.profiles_base_path}"
        
        # Find available profiles with planning files
        available_profiles = self.find_available_profiles()
        
        if not available_profiles:
            print(f"No planning files found for {self.platform_name}. Please generate planning first.")
            return
        
        # Let user select profiles to process
        selected_profiles = self.prompt_user_selection(available_profiles)
        if not selected_profiles:
            return
            
        # Process each selected profile
        for profile_name, planning_file_path, structure in selected_profiles:
            self.generate_posts_from_planning(profile_name, planning_file_path, structure)


# For backward compatibility - these functions use the new class
def generate_meta_posts(profiles_base_path=None):
    """Generate Meta (Instagram/Facebook) posts based on planning files."""
    generator = PublicationsGenerator(
        post_template_folder=os.path.join('.', 'llm', 'meta', 'prompts', 'posts'),
        platform_name="meta",
        llm_module_path="llm.meta_llm",
        llm_class_name="MetaLLM",
        llm_method_name="generate_meta_posts"
    )
    generator.generate()

def generate_fanvue_posts(profiles_base_path=None):
    """Generate Fanvue posts based on planning files."""
    generator = PublicationsGenerator(
        post_template_folder=os.path.join('.', 'llm', 'fanvue', 'prompts', 'posts'),
        platform_name="fanvue",
        llm_module_path="llm.fanvue_llm",
        llm_class_name="FanvueLLM", 
        llm_method_name="generate_fanvue_posts"
    )
    generator.generate()

# For backward compatibility with older code
def generate_instagram_posts(profiles_base_path=None):
    """Redirect to generate_meta_posts for backward compatibility."""
    print("Warning: generate_instagram_posts is deprecated, use generate_meta_posts instead")
    generate_meta_posts(profiles_base_path)
