import os
import json
from slugify import slugify
from tqdm import tqdm
from utils.utils import get_valid_planning_file_names
from utils.exceptions import WaitAndRetryError
from time import sleep
from pipeline.pipeline_instagram import PipelineInstagram

def generate_instagram_posts(profiles_base_path):
    """
    Generate Instagram posts based on planning files.
    """
    assert os.path.isdir(profiles_base_path), f"Profiles base path not found: {profiles_base_path}"
    
    # Get available profiles with planning files
    available_profiles = []
    
    # Look for planning files in the new structure
    for profile_name in os.listdir(profiles_base_path):
        profile_path = os.path.join(profiles_base_path, profile_name)
        if os.path.isdir(profile_path):
            outputs_path = os.path.join(profile_path, "outputs")
            if os.path.isdir(outputs_path):
                for file_name in os.listdir(outputs_path):
                    if file_name.endswith('_planning.json'):
                        planning_path = os.path.join(outputs_path, file_name)
                        available_profiles.append((profile_name, planning_path, "new"))
    
    # If no profiles found in new structure, check old structure for backward compatibility
    if not available_profiles:
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
    
    assert len(available_profiles) > 0, "No planning files found, please generate a planning first"

    # Display available profiles
    print("Available profiles with planning files:")
    for i, (profile, _, structure) in enumerate(available_profiles):
        print(f"{i + 1}: {profile} {'(old structure)' if structure == 'old' else ''}")

    # Prompt the user to select a profile number or choose to process all
    profile_input = input("Select profile numbers separated by commas or type 'all' to process all: ")

    if profile_input.lower() == 'all':
        selected_profiles = available_profiles
    else:
        profile_indices = [int(index.strip()) - 1 for index in profile_input.split(',')]
        for index in profile_indices:
            assert 0 <= index < len(available_profiles), f"Invalid profile number: {index + 1}"
        selected_profiles = [available_profiles[index] for index in profile_indices]

    # Loop through the selected Instagram profiles
    for profile_name, planning_file_path, structure in selected_profiles:
        print(f"Processing profile: {profile_name}")

        # Load the planning data into a variable
        with open(planning_file_path, 'r', encoding='utf-8') as file:
            json_data_planning = json.load(file)
        
        # Create the 'posts' folder in appropriate location based on structure
        if structure == "new":
            output_folder = os.path.join(profiles_base_path, profile_name, 'outputs', 'posts')
        else:  # old structure
            output_folder = os.path.join('resources', 'outputs', 'instagram_profiles', profile_name, 'posts')
            # Also create folder in new structure for future use
            new_output_folder = os.path.join(profiles_base_path, profile_name, 'outputs', 'posts')
            os.makedirs(new_output_folder, exist_ok=True)
            print(f"Note: Future posts will be saved to new structure at: {new_output_folder}")
            
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

        # Generate posts for the planning data
        for week, days in tqdm(json_data_planning.items(), desc="Processing weeks"):
            week_folder = os.path.join(output_folder, week)
        
            for day_data in tqdm(days, desc=f"Processing days in {week}"):
                day_number = day_data['day']
                day_folder = os.path.join(week_folder, f"day_{day_number}")
        
                for post_data in day_data['posts']:
                    post_title = post_data.get('title')
                    post_slug = slugify(post_title)
                    caption = post_data.get('caption')
                    hashtags = post_data.get('hashtags', [])
                    upload_time = post_data.get('upload_time')
        
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
                            "image_description": image.get('image_description')
                        })
        
                    # Run the PipelineInstagram for this single post
                    for retrial in range(25):
                        try:
                            PipelineInstagram(post_content=[post_content], output_folder=day_folder).generate_posts()
                            break
                        except WaitAndRetryError as e:
                            sleep_time = e.suggested_wait_time
                            hours, minutes, seconds = sleep_time // 3600, (sleep_time // 60) % 60, sleep_time % 60
                            for _ in tqdm(range(100),
                                        desc=f"Waiting {hours}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"):
                                sleep(sleep_time / 100)
