import os
import json
import importlib
from slugify import slugify
from tqdm import tqdm
from utils.utils import get_valid_planning_file_names
from utils.exceptions import WaitAndRetryError
from time import sleep
from generation_tools.image_generator.flux.flux import Flux

class PublicationsGenerator:
    """Universal publications generator for creating content across different platforms."""
    
    def __init__(self, publication_template_folder, platform_name, llm_module_path=None, 
                 llm_class_name=None, llm_method_name=None):
        """
        Initialize the publications generator.
        
        Args:
            publication_template_folder: Path to the folder containing publication templates
            platform_name: Name of the platform (meta, fanvue, etc.)
            llm_module_path: (Optional) Path to the LLM module
            llm_class_name: (Optional) Name of the LLM class
            llm_method_name: (Optional) Name of the generation method
        """
        self.publication_template_folder = publication_template_folder
        self.platform_name = platform_name
        self.llm_module_path = llm_module_path
        self.llm_class_name = llm_class_name
        self.llm_method_name = llm_method_name
        
        # Determine the profiles base path based on platform
        self.profiles_base_path = os.path.join('.', 'resources', f'{platform_name}_profiles')
        
        # Initialize image generator (lazy loading)
        self.image_generator = None
    
    def _get_image_generator(self):
        """Get or initialize the image generator."""
        if self.image_generator is None:
            self.image_generator = Flux(load_on_demand=True)
        return self.image_generator
        
    def find_available_profiles(self):
        """Find all available profiles with planning files."""
        available_profiles = []
        
        # Look for planning files in the profiles folder structure
        if os.path.isdir(self.profiles_base_path):
            for profile_name in os.listdir(self.profiles_base_path):
                profile_path = os.path.join(self.profiles_base_path, profile_name)
                if os.path.isdir(profile_path):
                    outputs_path = os.path.join(profile_path, "outputs")
                    if os.path.isdir(outputs_path):
                        for file_name in os.listdir(outputs_path):
                            if file_name.endswith('_planning.json'):
                                planning_path = os.path.join(outputs_path, file_name)
                                available_profiles.append((profile_name, planning_path))
    
        return available_profiles
    
    def prompt_user_selection(self, available_profiles):
        """Prompt the user to select profiles."""
        if not available_profiles:
            print(f"No planning files found for {self.platform_name}, please generate a planning first")
            return []

        print(f"\nAvailable {self.platform_name} profiles with planning files:")
        for i, (profile, _) in enumerate(available_profiles):
            print(f"{i + 1}: {profile}")
        
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
    
    def create_publication_directories(self, profile_name, json_data_planning, output_folder):
        """Create directory structure for publications."""
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
                    for publication in day_data['posts']:  # Keep 'posts' key name for compatibility
                        captions_file.write(publication['caption'] + "\n\n")
                # Create a .txt file with the upload times for the day
                upload_times_file_path = os.path.join(day_folder, "upload_times.txt")
                with open(upload_times_file_path, 'w', encoding='utf-8') as upload_times_file:
                    for publication in day_data['posts']:  # Keep 'posts' key name for compatibility
                        upload_times_file.write(publication['upload_time'] + "\n")
        
        return output_folder
    
    def generate_images(self, publication_content, output_folder):
        """Generate images for publications based on platform."""
        if self.platform_name == "meta":
            self._generate_meta_images(publication_content, output_folder)
        elif self.platform_name == "fanvue":
            self._generate_fanvue_images(publication_content, output_folder)
        else:
            raise ValueError(f"Unsupported platform: {self.platform_name}")
    
    def _generate_meta_images(self, publication_content, output_folder):
        """Generate images for Meta platforms (Instagram/Facebook)."""
        for item in publication_content:
            post_slug = item["post_slug"]
            for idx, image in enumerate(item["images"]):
                image_description = image["image_description"]
                image_path = os.path.join(output_folder, f"{post_slug}_{idx}.png")
                
                if not os.path.isfile(image_path):
                    print(f"Generating image for ID {post_slug}_{idx} with description '{image_description}'")
                    
                    # Get or initialize the image generator
                    image_generator = self._get_image_generator()
                    
                    # Generate the image
                    for retrial in range(3):  # Retry up to 3 times
                        try:
                            image_generator.generate_image(
                                prompt=image_description, 
                                output_path=image_path, 
                                width=1080, 
                                height=1080, 
                                retries=2
                            )
                            break
                        except Exception as e:
                            if retrial == 2:  # Last attempt failed
                                print(f"Failed to generate image after 3 attempts: {e}")
                                raise
                            print(f"Error generating image (attempt {retrial+1}/3): {e}")
                            sleep(5)
                    
                    assert os.path.isfile(image_path), f"Image file {image_path} was not generated"
                    print(f"Image generated and saved at {image_path}")
    
    def _generate_fanvue_images(self, publication_content, output_folder):
        """Generate images for Fanvue platform."""
        # Similar to _generate_meta_images but with Fanvue-specific customizations
        # For now, we'll use the same implementation as Meta
        self._generate_meta_images(publication_content, output_folder)
    
    def generate_publications_from_planning(self, profile_name, planning_file_path, output_folder):
        """Generate publications for a specific profile based on planning data."""
        print(f"Processing profile: {profile_name}")

        # Load the planning data
        with open(planning_file_path, 'r', encoding='utf-8') as file:
            json_data_planning = json.load(file)
        
        # Create directory structure
        self.create_publication_directories(profile_name, json_data_planning, output_folder)
        
        # Generate publications for the planning data
        for week, days in tqdm(json_data_planning.items(), desc="Processing weeks"):
            week_folder = os.path.join(output_folder, week)
        
            for day_data in tqdm(days, desc=f"Processing days in {week}"):
                day_number = day_data['day']
                day_folder = os.path.join(week_folder, f"day_{day_number}")
        
                for publication_data in day_data['posts']:  
                    publication_title = publication_data.get('title', '')
                    publication_slug = slugify(publication_title) if publication_title else f"publication_{day_number}"
                    caption = publication_data.get('caption', '')
                    hashtags = publication_data.get('hashtags', [])
                    upload_time = publication_data.get('upload_time', '')
        
                    # Prepare the publication content
                    publication_content = [{  
                        "post_title": publication_title,
                        "post_slug": publication_slug,
                        "caption": caption,
                        "hashtags": hashtags,
                        "upload_time": upload_time,
                        "images": []
                    }]
        
                    # Add each image's description to the publication content
                    for image in publication_data.get('images', []):
                        publication_content[0]["images"].append({
                            "image_description": image.get('image_description', '')
                        })
        
                    # Generate images with retry mechanism
                    for retrial in range(25):
                        try:
                            # Directly call our integrated image generation method
                            self.generate_images(publication_content, day_folder)
                            break
                        except WaitAndRetryError as e:
                            sleep_time = e.suggested_wait_time
                            hours, minutes, seconds = sleep_time // 3600, (sleep_time // 60) % 60, sleep_time % 60
                            for _ in tqdm(range(100),
                                      desc=f"Waiting {hours}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"):
                                sleep(sleep_time / 100)
    
    def generate(self):
        """Main method to generate publications."""
        assert os.path.isdir(self.profiles_base_path), \
            f"Profiles base path not found: {self.profiles_base_path}"
        
        # 1) Find available _planning.json files for the different profiles
        available_profiles = self.find_available_profiles()
        
        if not available_profiles:
            print(f"No planning files found for {self.platform_name}. Please generate planning first.")
            return
        
        # 2) Let user select profiles to process
        selected_profiles = self.prompt_user_selection(available_profiles)
        if not selected_profiles:
            return
            
        # 3) Process each selected profile
        for profile_name, planning_file_path in selected_profiles:
            # Define output folder path
            output_folder = os.path.join(self.profiles_base_path, profile_name, 'outputs', 'publications')
            self.generate_publications_from_planning(profile_name, planning_file_path, output_folder)


