import os
import importlib
from datetime import datetime, timezone
from time import sleep

class PostingScheduler:
    """Universal posting scheduler for uploading content across different platforms."""
    
    def __init__(self, publication_base_folder, platform_name, api_module_path, api_class_name):
        """
        Initialize the posting scheduler.
        
        Args:
            publication_base_folder: Path to the folder containing publications
            platform_name: Name of the platform (meta, fanvue, etc.)
            api_module_path: Path to the API module 
            api_class_name: Name of the API class
        """
        self.publication_base_folder = publication_base_folder
        self.platform_name = platform_name
        self.api_module_path = api_module_path
        self.api_class_name = api_class_name
        
        # Determine the profiles base path based on platform
        self.profiles_base_path = os.path.join('.', 'resources', f'{platform_name}_profiles')
    
    def _get_api_instance(self):
        """Dynamically import and create an instance of the specified API class."""
        try:
            # Import the module
            api_module = importlib.import_module(self.api_module_path)
            
            # Get the class from the module
            api_class = getattr(api_module, self.api_class_name)
            
            # For Fanvue, we don't create the instance here since it requires a driver
            if self.platform_name == "fanvue":
                return api_class  # Return class rather than instance
            
            # For other platforms (like Meta), create an instance directly
            return api_class()
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to import {self.api_class_name} from {self.api_module_path}: {str(e)}")
    
    def find_available_profiles(self):
        """Find all available profiles with publications to upload."""
        available_profiles = []
        
        # Look for publication folders in the profiles directory structure
        if os.path.isdir(self.profiles_base_path):
            for profile_name in os.listdir(self.profiles_base_path):
                profile_path = os.path.join(self.profiles_base_path, profile_name)
                if os.path.isdir(profile_path):
                    outputs_path = os.path.join(profile_path, "outputs", "publications")
                    if os.path.isdir(outputs_path) and os.listdir(outputs_path):
                        available_profiles.append(profile_name)
        
        return available_profiles
    
    def prompt_user_selection(self, available_profiles):
        """Prompt the user to select profiles for uploading."""
        if not available_profiles:
            print(f"No profiles found with publications to upload for {self.platform_name}.")
            return []

        print(f"\nAvailable {self.platform_name} profiles with publications:")
        for i, profile in enumerate(available_profiles):
            print(f"{i + 1}: {profile}")
        
        profile_input = input("\nSelect profile number to upload: ")
        
        try:
            profile_idx = int(profile_input.strip()) - 1
            assert 0 <= profile_idx < len(available_profiles), f"Invalid profile number: {profile_idx + 1}"
            return [available_profiles[profile_idx]]
        except (ValueError, AssertionError) as e:
            print(f"Error in selection: {e}")
            return []
    
    def _read_publication_files(self, day_folder):
        """Read caption, upload time and image files from a day folder."""
        # Check that captions and upload_times files exist
        captions_file_path = os.path.join(day_folder, "captions.txt")
        upload_times_file_path = os.path.join(day_folder, "upload_times.txt")
        
        if not os.path.isfile(captions_file_path) or not os.path.isfile(upload_times_file_path):
            print(f"Error: Missing caption or upload time file in {day_folder}")
            return None, None, []
        
        # Read captions
        try:
            with open(captions_file_path, 'r', encoding='utf-8') as f:
                caption = f.read().strip()
        except Exception as e:
            print(f"Error reading captions.txt in {day_folder}: {e}")
            return None, None, []

        # Read upload times
        try:
            with open(upload_times_file_path, 'r', encoding='utf-8') as f:
                upload_time_str = f.read().strip()
        except Exception as e:
            print(f"Error reading upload_times.txt in {day_folder}: {e}")
            return None, None, []

        # Look for images in the day folder
        image_files = [os.path.join(day_folder, f) 
                      for f in sorted(os.listdir(day_folder))
                      if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        
        if not image_files:
            print(f"Error: No image files found in {day_folder}")
            return None, None, []

        return caption, upload_time_str, image_files
    
    def _wait_for_scheduled_time(self, upload_time_str, day_folder):
        """Wait until the scheduled upload time if needed."""
        try:
            scheduled_time = datetime.strptime(upload_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception as e:
            print(f"Error parsing upload time '{upload_time_str}' in {day_folder}: {e}")
            return False

        # Wait until scheduled time if needed
        now = datetime.now(timezone.utc)
        if scheduled_time > now:
            wait_seconds = (scheduled_time - now).total_seconds()
            print(f"Waiting for {wait_seconds:.0f} seconds until scheduled time {scheduled_time}...")
            sleep(wait_seconds)
        else:
            print(f"Scheduled time {scheduled_time} has already passed. Uploading immediately.")
        
        return True
    
    def _process_meta_publications(self, profile_name, api_instance):
        """Process and upload Meta publications for the given profile."""
        publications_folder = os.path.join(self.profiles_base_path, profile_name, "outputs", "publications")
        
        # Iterate over weeks and days
        for week in sorted(os.listdir(publications_folder)):
            week_folder = os.path.join(publications_folder, week)
            if not os.path.isdir(week_folder):
                continue
            print(f"\nProcessing week: {week}")
            
            for day in sorted(os.listdir(week_folder)):
                day_folder = os.path.join(week_folder, day)
                if not os.path.isdir(day_folder):
                    continue
                print(f"\nProcessing day folder: {day}")
                
                # Read the publication files
                caption, upload_time_str, image_files = self._read_publication_files(day_folder)
                if not caption or not upload_time_str or not image_files:
                    continue
                
                # Wait for the scheduled time
                if not self._wait_for_scheduled_time(upload_time_str, day_folder):
                    continue
                
                # Upload to Meta using GraphAPI
                print(f"Uploading publication from {day_folder} to Meta...")
                try:
                    response_instagram = api_instance.upload_instagram_publication(image_files, caption)
                    response_facebook = api_instance.upload_facebook_publication(image_files, caption)
                    
                    if response_instagram and response_facebook:
                        print(f"Publication uploaded successfully to Instagram: {response_instagram}")
                        print(f"Publication uploaded successfully to Facebook: {response_facebook}")
                    else:
                        print(f"Failed to upload publication.")
                except Exception as e:
                    print(f"Error uploading publication: {e}")
    
    def _process_fanvue_publications(self, profile_name, fanvue_class):
        """Process and upload Fanvue publications for the given profile."""
        publications_folder = os.path.join(self.profiles_base_path, profile_name, "outputs", "publications")
        
        # Import SeleniumBase for Fanvue
        from seleniumbase import SB
        
        # Use SeleniumBase context manager to handle browser lifecycle
        with SB(uc=True, test=True, locale_code="en") as driver:
            # Create Fanvue publisher instance with the driver
            publisher = fanvue_class(driver)
            
            # Login to Fanvue
            try:
                print(f"Logging in to Fanvue as {profile_name}...")
                publisher.login(profile_name)
                print("Login successful")
            except Exception as e:
                print(f"Failed to login to Fanvue: {e}")
                return
            
            # Process publications by week and day
            for week in sorted(os.listdir(publications_folder)):
                week_folder = os.path.join(publications_folder, week)
                if not os.path.isdir(week_folder):
                    continue
                print(f"\nProcessing week: {week}")
                
                for day in sorted(os.listdir(week_folder)):
                    day_folder = os.path.join(week_folder, day)
                    if not os.path.isdir(day_folder):
                        continue
                    print(f"\nProcessing day folder: {day}")
                    
                    # Read the publication files
                    caption, upload_time_str, image_files = self._read_publication_files(day_folder)
                    if not caption or not upload_time_str or not image_files:
                        continue
                    
                    # Wait for the scheduled time
                    if not self._wait_for_scheduled_time(upload_time_str, day_folder):
                        continue
                    
                    # For Fanvue, upload each image as a separate post
                    for image_file in image_files:
                        try:
                            print(f"Uploading {image_file} to Fanvue...")
                            publisher.post_publication(image_file, caption)
                            print(f"Successfully uploaded {image_file} to Fanvue")
                            # Wait a bit between posts to avoid rate limiting
                            sleep(5)
                        except Exception as e:
                            print(f"Error uploading {image_file} to Fanvue: {e}")
    
    def upload(self):
        """Main method to upload publications."""
        assert os.path.isdir(self.profiles_base_path), \
            f"Profiles base path not found: {self.profiles_base_path}"
        
        # 1) Find available profiles with publications
        available_profiles = self.find_available_profiles()
        
        if not available_profiles:
            print(f"No profiles found with publications for {self.platform_name}.")
            return
        
        # 2) Let user select a profile to upload
        selected_profiles = self.prompt_user_selection(available_profiles)
        if not selected_profiles:
            return
        
        # 3) Get the API instance or class
        api_instance_or_class = self._get_api_instance()
        
        # 4) Process each selected profile based on platform
        for profile_name in selected_profiles:
            if self.platform_name == "meta":
                self._process_meta_publications(profile_name, api_instance_or_class)
            elif self.platform_name == "fanvue":
                self._process_fanvue_publications(profile_name, api_instance_or_class)
            else:
                print(f"Unsupported platform: {self.platform_name}")


# Backward compatibility function
def upload_posts(profiles_base_path):
    """Legacy function to upload posts for a selected profile."""
    print("Note: Using legacy upload_posts function. Consider migrating to the PostingScheduler class.")
    
    scheduler = PostingScheduler(
        publication_base_folder=profiles_base_path,
        platform_name="meta",  # Legacy function assumes Meta platform
        api_module_path="bot_services.meta_api.graph_api",
        api_class_name="GraphAPI"
    )
    scheduler.upload()
