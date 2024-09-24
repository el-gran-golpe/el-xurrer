import os
from pipeline.pipeline_instagram import PipelineInstagram
from llm.instagram.instagram_llm import InstagramLLM
import json
from slugify import slugify
from tqdm import tqdm

EXECUTE_PLANNING = True  # Set to True for planning, False for generating posts
GENERATE_POSTS = False   # Set to True for generating posts
UPLOAD_POSTS = False     # Set to True when you want to run uploads

PLANNING_TEMPLATE_FOLDER = os.path.join('.', 'resources', 'inputs', 'instagram_profiles', 'laura_vigne', 'prompts', 'planning') 
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'instagram', 'prompts', 'posts')
POST_COUNT = 30

OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join('.', 'resources', 'outputs','instagram_profiles', 'planning')
OUTPUT_FOLDER_BASE_PATH_POSTS = os.path.join('.', 'outputs','instagram_profiles', 'posts')

def generate_instagram_planning():
    # Ensure the planning template folder exists
    assert os.path.isdir(PLANNING_TEMPLATE_FOLDER), f"Planning template folder not found: {PLANNING_TEMPLATE_FOLDER}"
    
    # List all JSON files in the planning template folder
    available_plannings = [template for template in os.listdir(PLANNING_TEMPLATE_FOLDER) if template.endswith('.json')]
    print("Available planning templates:")
    
    # Display available planning templates with their status (new or existing)
    for i, template in enumerate(available_plannings):
        output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, template[:-len('.json')])
        if not os.path.isdir(output_path):
            subtext = "(New)"
        else:
            subtext = f"(Existent posts: {len(os.listdir(output_path))})"
        print(f"{i + 1}: {template[:-len('.json')]} {subtext}")
    
    # Prompt the user to select a template
    template_index = int(input("Select a template number: ")) - 1
    assert 0 <= template_index < len(available_plannings), "Invalid template number"
    template_path = os.path.join(PLANNING_TEMPLATE_FOLDER, available_plannings[template_index]) # TODO: check what this template path does in the future

    # Extract the profile name from the selected template
    profile_name = available_plannings[template_index][:-len('.json')]

    # Generate the story planning using the selected template
    planning = InstagramLLM().generate_storyline(prompt_template_path=template_path, duration=POST_COUNT)

    # Define the output path for the planning
    output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, profile_name)
    os.makedirs(output_path, exist_ok=True)

    # Check if a planning file already exists and prompt for overwrite if it does
    if os.path.isfile(os.path.join(output_path, 'planning.json')):
        print(f"Warning: The planning file already exists in the folder: {output_path}")
        overwrite = input("Do you want to overwrite it? (y/n): ")
        if overwrite.lower() not in ('y', 'yes'):
            print("The planning was not saved")
            return

    # Save the generated planning to a JSON file
    with open(os.path.join(output_path, 'planning.json'), 'w') as file:
        json.dump(planning, file, indent=4, ensure_ascii=False)


def generate_posts():
    assert os.path.isdir(OUTPUT_FOLDER_BASE_PATH_PLANNING), f"Planning folder not found: {OUTPUT_FOLDER_BASE_PATH_PLANNING}"

    available_plannings = [template[:-len('.json')] for template in os.listdir(OUTPUT_FOLDER_BASE_PATH_PLANNING)
                           if template.endswith('.json')]
    assert len(available_plannings) > 0, "No planning files found, please generate a planning first"
    
    print("Available planning files:")
    channel_index = 0 if len(available_plannings) == 1 else int(input("Select a channel number: ")) - 1
    assert 0 <= channel_index < len(available_plannings), "Invalid channel number"
    channel_name = available_plannings[channel_index]

    prompt_template_path = os.path.join(POST_TEMPLATE_FOLDER, f"{channel_name}.json")
    assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"

    output_folder = os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, channel_name)
    os.makedirs(output_folder, exist_ok=True)

    with open(os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, f"{channel_name}.json"), 'r') as file:
        planning = json.load(file)

    for post_name, post_data in tqdm(planning.items(), desc="Generating Instagram posts", total=len(planning)):
        post_slug = slugify(post_name)
        image_description, hashtags = post_data.get('image_description'), post_data.get('hashtags')
        
        output_path = os.path.join(output_folder, post_slug)
        os.makedirs(output_path, exist_ok=True)
        
        if not os.path.isfile(os.path.join(output_path, 'post.json')):
            post_content = InstagramLLM().generate_single_post(
                post_theme=post_name, image_description=image_description, hashtags=hashtags)

            with open(os.path.join(output_path, 'post.json'), 'w') as f:
                json.dump(post_content, f, indent=4, ensure_ascii=False)

            PipelineInstagram(output_folder=output_path).generate_post()


def upload_posts():
    from uploading_apis.instagram.uploader_instagram import InstagramUploader

    uploader = InstagramUploader()

    # Read posts that have already been generated
    post_folders = [folder for folder in os.listdir(OUTPUT_FOLDER_BASE_PATH_POSTS) if os.path.isdir(os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, folder))]

    for post_folder in post_folders:
        post_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, post_folder, 'post.json')
        if os.path.isfile(post_path):
            with open(post_path, 'r') as f:
                post_content = json.load(f)

            image_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_POSTS, post_folder, f'{slugify(post_content["caption"])}.png')
            uploader.upload_post(image_path=image_path, caption=post_content['caption'])


if __name__ == '__main__':
    if EXECUTE_PLANNING:
        generate_instagram_planning()

    if GENERATE_POSTS:
        generate_posts()

    # Only uncomment or set UPLOAD_POSTS to True when you want to upload
    if UPLOAD_POSTS:
        upload_posts()
