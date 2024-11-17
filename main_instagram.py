import os
from pipeline.pipeline_instagram import PipelineInstagram
from llm.instagram.instagram_llm import InstagramLLM
import json
from slugify import slugify
from tqdm import tqdm
from utils.utils import read_previous_storyline
from uploading_apis.instagram.uploader_instagram import InstagramUploader

EXECUTE_PLANNING = False  # Set to True for planning
GENERATE_POSTS = True     # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True when you want to run uploads

PLANNING_TEMPLATE_FOLDER = os.path.join('.', 'resources', 'inputs', 'instagram_profiles') 
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'instagram', 'prompts', 'posts')

OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join('.', 'resources', 'outputs','instagram_profiles')
OUTPUT_FOLDER_BASE_PATH_POSTS = os.path.join('.', 'resources', 'outputs','instagram_profiles', 'laura_vigne', 'posts')


def generate_instagram_planning():
    # Ensure the planning template folder exists
    assert os.path.isdir(PLANNING_TEMPLATE_FOLDER), f"Planning template folder not found: {PLANNING_TEMPLATE_FOLDER}"
    
    # List all JSON files in the planning template folder
    available_plannings = []
    for root, dirs, files in os.walk(PLANNING_TEMPLATE_FOLDER):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            for file_name in os.listdir(dir_path):
                if file_name == f"{dir_name}.json":
                    available_plannings.append(os.path.join(dir_path, file_name))
    
    # Display available planning templates with their status (new or existing)
    for i, template in enumerate(available_plannings):
        output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, template[:-len('.json')])
        if not os.path.isdir(output_path):
            subtext = "(New)"
        else:
            subtext = f"(Existent posts: {len(os.listdir(output_path))})"
        print(f"{i + 1}: {template[:-len('.json')]} {subtext}")
    
    # Automatically select the first template if only one is available
    if len(available_plannings) == 1:
        template_index = 0
    else:
        # Prompt the user to select a template number
        template_index = int(input("Select a template number: ")) - 1
        assert 0 <= template_index < len(available_plannings), "Invalid template number"
    
    template_path = available_plannings[template_index]

    # Extract the profile name from the selected template
    profile_name = os.path.basename(template_path)[:-len('.json')]

    # Define the path to the cumulative storyline file
    storyline_file_path = os.path.join('resources', 'inputs', 'instagram_profiles', 'laura_vigne', 'cumulative_storyline.md')
    
    # Read the previous storyline from the file (if it exists)
    previous_storyline = read_previous_storyline(storyline_file_path)

    # Generate the Instagram planning using the selected template
    planning = InstagramLLM().generate_instagram_planning(
        prompt_template_path=template_path,
        previous_storyline=previous_storyline
    )

    # Create a folder for the planning file
    output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, profile_name)
    os.makedirs(output_path, exist_ok=True)

    # Check if a planning file already exists and prompt for overwrite if it does
    profile_initials = ''.join([word[0] for word in profile_name.split('_')])
    planning_filename = f"{profile_initials}_planning.json"

    if os.path.isfile(os.path.join(output_path, planning_filename)):
        print(f"Warning: The planning file already exists in the folder: {output_path}")
        overwrite = input("Do you want to overwrite it? (y/n): ")
        if overwrite.lower() not in ('y', 'yes'):
            print("The planning was not saved") #TODO: this is wronly overwritting things
            return

    # Save the generated planning to a JSON file
    with open(os.path.join(output_path, planning_filename), 'w', encoding='utf-8') as file:
        json.dump(planning, file, indent=4, ensure_ascii=False)

def generate_instagram_posts():
    # Ensure the planning folder exists
    assert os.path.isdir(OUTPUT_FOLDER_BASE_PATH_PLANNING), f"Planning folder not found: {OUTPUT_FOLDER_BASE_PATH_PLANNING}"

    # List all JSON files in the planning folder
    available_plannings = []
    for root, dirs, files in os.walk(OUTPUT_FOLDER_BASE_PATH_PLANNING):
        for file in files:
            if file.endswith('.json'):
                available_plannings.append(os.path.join(root, file)[:-len('.json')])
    assert len(available_plannings) > 0, "No planning files found, please generate a planning first"

    print("Available planning files:", available_plannings)

    # Automatically select the first profile if only one is available
    profile_index = 0 if len(available_plannings) == 1 else int(input("Select a profile number: ")) - 1
    assert 0 <= profile_index < len(available_plannings), "Invalid profile number"
    profile_name = os.path.basename(os.path.dirname(available_plannings[profile_index]))

    # Define the prompt template for posts
    #prompt_template_path = os.path.join(POST_TEMPLATE_FOLDER, f"{profile_name}.json")
    #assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"

    # Create the output folder for posts if it doesn't exist
    profile_folder = os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, profile_name)
    assert os.path.isdir(profile_folder), f"Profile folder not found: {profile_folder}"
    output_folder = os.path.join(profile_folder, 'posts')
    os.makedirs(output_folder, exist_ok=True)

    # Load the planning data from the selected planning file
    planning_file_path = available_plannings[profile_index] + '.json'
    with open(planning_file_path, 'r', encoding='utf-8') as file:
        json_data_planning = json.load(file)

    # Iterate over the weeks and posts in the JSON data
    for week, days in json_data_planning.items():
        for day_data in days:
            for post_data in tqdm(day_data['posts'], desc=f"Generating Instagram posts for {profile_name}", total=len(day_data['posts'])):
                post_title = post_data.get('title')
                post_slug = slugify(post_title)
                caption = post_data.get('caption')
                hashtags = post_data.get('hashtags', [])
                image_description = post_data.get('image_description')
                image_urls = post_data.get('image_urls', [])
                upload_time = post_data.get('upload_time')

                # Ensure a unique folder for each post
                post_folder = os.path.join(output_folder, post_slug)
                os.makedirs(post_folder, exist_ok=True)

                post_content = [{
                    "post_title": post_title,
                    "caption": caption,
                    "hashtags": hashtags,
                    "image_description": image_description,
                    "image_urls": image_urls,
                    "upload_time": upload_time
                }]

            # Instagram publication generation step
            for retrial in range(25):
                try:
                    PipelineInstagram(post_content, post_folder).generate_posts() #TODO: check output folder variable
                    break
                except WaitAndRetryError as e:
                    sleep_time = e.suggested_wait_time
                    hours, minutes, seconds = sleep_time // 3600, sleep_time // 60 % 60, sleep_time % 60

                    for _ in tqdm(range(100),
                                    desc=f"Waiting {str(hours)}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"):
                        sleep(sleep_time / 100)


def upload_posts():
    uploader = InstagramUploader()

    # Get list of post folders
    post_folders = [
        folder for folder in os.listdir(OUTPUT_FOLDER_BASE_PATH_POSTS)
        if os.path.isdir(os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, folder))
    ]
    assert post_folders, f"No post folders found in {OUTPUT_FOLDER_BASE_PATH_POSTS}"

    for post_folder in sorted(post_folders):
        post_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, post_folder)

        # Read caption
        caption_path = os.path.join(post_path, 'caption.txt')
        assert os.path.isfile(caption_path), f"No caption.txt found in {post_folder}."
        with open(caption_path, 'r', encoding='utf-8') as f:
            caption = f.read().strip()
        assert caption, f"Caption in {post_folder} is empty."

        # Read upload time
        upload_time_path = os.path.join(post_path, 'upload_time.txt')
        assert os.path.isfile(upload_time_path), f"No upload_time.txt found in {post_folder}."
        with open(upload_time_path, 'r') as f:
            upload_time_str = f.read().strip()
            # Parse the upload time in ISO 8601 format with 'Z' for UTC
            try:
                upload_time = datetime.strptime(upload_time_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
            except ValueError:
                assert False, f"Invalid date format in {upload_time_path}. Expected format: YYYY-MM-DDTHH:MM:SSZ"

        # Get current time in UTC
        current_time = datetime.now(timezone.utc)
        if current_time < upload_time:
            time_to_wait = (upload_time - current_time).total_seconds()
            print(f"Waiting {time_to_wait} seconds to upload {post_folder}")
            time.sleep(time_to_wait)

        # Get image paths
        image_files = [
            file for file in os.listdir(post_path)
            if file.lower().endswith(('.png', '.jpg', '.jpeg'))
        ]
        assert image_files, f"No images found in {post_folder}."
        image_paths = [os.path.join(post_path, image_file) for image_file in sorted(image_files)]

        # Upload the post
        uploader.upload_post(image_paths=image_paths, caption=caption)


if __name__ == '__main__':
    if EXECUTE_PLANNING:
        generate_instagram_planning()

    if GENERATE_POSTS:
        generate_instagram_posts()

    if UPLOAD_POSTS:
        upload_posts()
