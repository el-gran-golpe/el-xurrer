import os
from pipeline.pipeline_instagram import PipelineInstagram
from llm.instagram.instagram_llm import InstagramLLM
import json
from slugify import slugify
from tqdm import tqdm
from uploading_apis.instagram import graph_api
from utils.utils import get_valid_planning_file_names, read_initial_conditions
from utils.exceptions import WaitAndRetryError
from time import sleep
from uploading_apis.instagram.graph_api import GraphAPI


EXECUTE_PLANNING = True   # Set to True for planning
GENERATE_POSTS = False    # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True when you want to run uploads

PLANNING_TEMPLATE_FOLDER = os.path.join('.', 'resources', 'inputs', 'instagram_profiles') 
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'instagram', 'prompts', 'posts')

OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join('.', 'resources', 'outputs','instagram_profiles')
OUTPUT_FOLDER_BASE_PATH_POSTS = os.path.join('.', 'resources', 'outputs','instagram_profiles', 'laura_vigne', 'posts')


def generate_instagram_planning():
    assert os.path.isdir(PLANNING_TEMPLATE_FOLDER), f"Planning template folder not found: {PLANNING_TEMPLATE_FOLDER}"
    
    # Check if there are any planning json files in the resources/inputs/instagram_profiles folder
    available_plannings = []
    for root, dirs, files in os.walk(PLANNING_TEMPLATE_FOLDER):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            planning_found = False
            for file_name in os.listdir(dir_path):
                if file_name.endswith('.json'):
                    assert file_name[:-len('.json')] == dir_name, f"Mismatch between folder name and file name: {dir_name} != {file_name[:-len('.json')]}"
                    if file_name == f"{dir_name}.json":
                        available_plannings.append(os.path.join(dir_path, file_name))
                        planning_found = True
            if not planning_found:
                print(f"Warning: No planning file found for folder: {dir_name}")

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
      
    # Generate and save the Instagram planning for each selected template
    for template_path in selected_templates:
        previous_storyline = read_initial_conditions(os.path.join(os.path.dirname(template_path),
                                                                     'initial_conditions.md'))
        while True:
            try:
                planning = InstagramLLM().generate_instagram_planning(
                    prompt_template_path=template_path,
                    previous_storyline=previous_storyline
                )
                break  # Exit the loop if no exception occurs
            except json.decoder.JSONDecodeError:
                continue  # Retry if JSONDecodeError occurs

        # We save the x2letters_planning.json file in the corresponding OUTPUT folder
        profile_name = os.path.basename(os.path.dirname(template_path))
        output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, profile_name)
        os.makedirs(output_path, exist_ok=True)
    
    
        profile_initials = ''.join([word[0] for word in profile_name.split('_')])
        planning_filename = f"{profile_initials}_planning.json"
    
        if os.path.isfile(os.path.join(output_path, planning_filename)):
            print(f"Warning: The planning file already exists in the folder: {output_path}")
            overwrite = input("Do you want to overwrite it? (y/n): ")
            if overwrite.lower() not in ('y', 'yes'):
                print("The planning was not saved")
                continue
    
        with open(os.path.join(output_path, planning_filename), 'w', encoding='utf-8') as file:
            json.dump(planning, file, indent=4, ensure_ascii=False)

def generate_instagram_posts():

    # --- 1st part: Some inital checks ---
    assert os.path.isdir(OUTPUT_FOLDER_BASE_PATH_PLANNING), f"Planning folder not found: {OUTPUT_FOLDER_BASE_PATH_PLANNING}"
    
    # Check if there are any planning json files in the planning folder
    available_plannings = get_valid_planning_file_names(OUTPUT_FOLDER_BASE_PATH_PLANNING)
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

    # --- 2nd part: looping through the Instagram profiles ---
    for template in selected_templates:
        profile_name = os.path.basename(os.path.dirname(template))
        print(f"Processing template: {profile_name}")

        # Load the planning data into a variable
        planning_file_path = template + '.json'
        with open(planning_file_path, 'r', encoding='utf-8') as file:
            json_data_planning = json.load(file)
        
        # Create the 'posts' main folder
        profile_folder = os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, profile_name)
        assert os.path.isdir(profile_folder), f"Profile folder not found: {profile_folder}" #TODO: Not sure if this is needed
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

        # --- Generate posts for the planning data ---
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
                        "post_title": post_title, #TODO: am I using this one?
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
        
                    # Now, run the PipelineInstagram for this single post, 
                    # directing outputs into the day_folder
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

def upload_posts():
    uploader = GraphAPI()

    # Get list of post folders
    post_folders = [
        folder for folder in os.listdir(OUTPUT_FOLDER_BASE_PATH_POSTS)
        if os.path.isdir(os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, folder))
    ]
    assert post_folders, f"No post folders found in {OUTPUT_FOLDER_BASE_PATH_POSTS}"

    for post_folder in sorted(post_folders):
        post_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, post_folder)

        # Read caption
        # caption_path = os.path.join(post_path, 'caption.txt')
        # assert os.path.isfile(caption_path), f"No caption.txt found in {post_folder}."
        # with open(caption_path, 'r', encoding='utf-8') as f:
        #     caption = f.read().strip()
        # assert caption, f"Caption in {post_folder} is empty."

        # # Read upload time
        # upload_time_path = os.path.join(post_path, 'upload_time.txt')
        # assert os.path.isfile(upload_time_path), f"No upload_time.txt found in {post_folder}."
        # with open(upload_time_path, 'r') as f:
        #     upload_time_str = f.read().strip()
        #     # Parse the upload time in ISO 8601 format with 'Z' for UTC
        #     try:
        #         upload_time = datetime.strptime(upload_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        #     except ValueError:
        #         assert False, f"Invalid date format in {upload_time_path}. Expected format: YYYY-MM-DDTHH:MM:SSZ"

        # # Get current time in UTC
        # current_time = datetime.now(timezone.utc)
        # if current_time < upload_time:
        #     time_to_wait = (upload_time - current_time).total_seconds()
        #     print(f"Waiting {time_to_wait} seconds to upload {post_folder}")
        #     time.sleep(time_to_wait)

        # # Get image paths
        # image_files = [
        #     file for file in os.listdir(post_path)
        #     if file.lower().endswith(('.png', '.jpg', '.jpeg'))
        # ]
        # assert image_files, f"No images found in {post_folder}."
        # image_paths = [os.path.join(post_path, image_file) for image_file in sorted(image_files)]

        # # Upload the post
        # uploader.upload_post(image_paths=image_paths, caption=caption)

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        generate_instagram_planning()

    if GENERATE_POSTS:
        generate_instagram_posts()

    if UPLOAD_POSTS:
        upload_posts()
