import os
import json
from slugify import slugify
from tqdm import tqdm
from utils.utils import get_valid_planning_file_names
from utils.exceptions import WaitAndRetryError
from time import sleep
from pipeline.pipeline_instagram import PipelineInstagram

def generate_instagram_posts(output_folder_base_path_planning):
    """
    Generate Instagram posts based on planning files.
    """
    assert os.path.isdir(output_folder_base_path_planning), f"Planning folder not found: {output_folder_base_path_planning}"
    
    # Check if there are any planning json files in the planning folder
    available_plannings = get_valid_planning_file_names(output_folder_base_path_planning)
    assert len(available_plannings) > 0, "No planning files found, please generate a planning first"

    print("Available planning templates:")
    for i, template in enumerate(available_plannings):
        grandparent_folder = os.path.basename(os.path.dirname(os.path.dirname(template)))
        parent_folder = os.path.basename(os.path.dirname(template))
        print(f"{i + 1}: {grandparent_folder}\\{parent_folder}")

    # Prompt the user to select a template number or choose to process all
    template_input = input("Select template numbers separated by commas or type 'all' to process all: ")

    if template_input.lower() == 'all':
        selected_templates = available_plannings
    else:
        template_indices = [int(index.strip()) - 1 for index in template_input.split(',')]
        for index in template_indices:
            assert 0 <= index < len(available_plannings), f"Invalid template number: {index + 1}"
        selected_templates = [available_plannings[index] for index in template_indices]

    # Loop through the Instagram profiles
    for template in selected_templates:
        profile_name = os.path.basename(os.path.dirname(template))
        print(f"Processing template: {profile_name}")

        # Load the planning data into a variable
        planning_file_path = template + '.json'
        with open(planning_file_path, 'r', encoding='utf-8') as file:
            json_data_planning = json.load(file)
        
        # Create the 'posts' main folder
        profile_folder = os.path.join(output_folder_base_path_planning, profile_name)
        assert os.path.isdir(profile_folder), f"Profile folder not found: {profile_folder}"
        output_folder = os.path.join(profile_folder, 'posts')
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
