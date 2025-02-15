import os
from pipeline.pipeline_instagram import PipelineInstagram
from llm.instagram.instagram_llm import InstagramLLM
import json
from slugify import slugify
from tqdm import tqdm
from utils.utils import get_valid_planning_file_names, read_initial_conditions
from utils.exceptions import WaitAndRetryError
from time import sleep
from uploader_services.meta_api.graph_api import GraphAPI


EXECUTE_PLANNING = False   # Set to True for planning
GENERATE_POSTS = True    # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True when you want to run uploads

PLANNING_TEMPLATE_FOLDER = os.path.join('.', 'resources', 'inputs', 'instagram_profiles') 
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'instagram', 'prompts', 'posts')

OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join('.', 'resources', 'outputs','instagram_profiles')
OUTPUT_FOLDER_BASE_PATH_POSTS = os.path.join('.', 'resources', 'outputs','instagram_profiles', 'laura_vigne', 'posts')


def generate_instagram_planning():
    assert os.path.isdir(PLANNING_TEMPLATE_FOLDER), f"Planning template folder not found: {PLANNING_TEMPLATE_FOLDER}"
    
    # 1) Gather all available .json planning te
    # mplates under PLANNING_TEMPLATE_FOLDER
    available_plannings = []
    for root, dirs, files in os.walk(PLANNING_TEMPLATE_FOLDER):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            planning_found = False
            for file_name in os.listdir(dir_path):
                if file_name.endswith('.json'):
                    # The folder name should match the JSON file name (minus '.json')
                    assert file_name[:-len('.json')] == dir_name, f"Mismatch: {dir_name} != {file_name[:-5]}"
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
    
    # 2) Prompt the user to select one or more templates (or 'all')
    template_input = input("Select template numbers separated by commas or type 'all' to process all: ")
    if template_input.lower() == 'all':
        selected_templates = available_plannings
    else:
        template_indices = [int(index.strip()) - 1 for index in template_input.split(',')]
        for index in template_indices:
            assert 0 <= index < len(available_plannings), f"Invalid template number: {index + 1}"
        selected_templates = [available_plannings[index] for index in template_indices]
      
    # 3) Figure out which of these selected templates already have an existing output file
    #    We will store them in a list and ask the user once if they want to overwrite them.
    existing_files = []
    not_existing_files = []
    
    for template_path in selected_templates:
        profile_name = os.path.basename(os.path.dirname(template_path))
        # E.g. 'my_profile' => 'mp_planning.json'
        profile_initials = ''.join([word[0] for word in profile_name.split('_')])
        planning_filename = f"{profile_initials}_planning.json"
        
        output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, profile_name)
        os.makedirs(output_path, exist_ok=True)
        
        full_output_path = os.path.join(output_path, planning_filename)
        if os.path.isfile(full_output_path):
            existing_files.append((template_path, full_output_path))
        else:
            not_existing_files.append((template_path, full_output_path))

    # If we have existing files, ask user for permission to overwrite them
    overwrite_all = False
    if existing_files:
        print("\nThe following planning files already exist and would be overwritten:")
        for (_, fpath) in existing_files:
            print(f"  {fpath}")
        
        overwrite_input = input("Do you want to overwrite these existing files? (y/n): ")
        overwrite_all = overwrite_input.lower() in ('y', 'yes')
    
    # 4) Combine the list of all to-be-processed files,
    #    but skip the existing ones if user doesn't want to overwrite
    final_templates = []
    for (template_path, output_path) in existing_files:
        if overwrite_all:
            final_templates.append((template_path, output_path))
        else:
            print(f"Skipping overwrite for {output_path}")

    # Add the files that don't exist yet (always processed)
    for (template_path, output_path) in not_existing_files:
        final_templates.append((template_path, output_path))
    
    # 5) Now do the actual generation for everything in final_templates
    for (template_path, full_output_path) in final_templates:
        profile_name = os.path.basename(os.path.dirname(template_path))
        profile_initials = ''.join([word[0] for word in profile_name.split('_')])
        planning_filename = os.path.basename(full_output_path)
        
        # Read previous storyline
        previous_storyline = read_initial_conditions(
            os.path.join(os.path.dirname(template_path), 'initial_conditions.md')
        )
        
        # Attempt generation repeatedly if JSONDecodeError occurs
        while True:
            try:
                planning = InstagramLLM().generate_instagram_planning(
                    prompt_template_path=template_path,
                    previous_storyline=previous_storyline
                )
                break
            except (json.decoder.JSONDecodeError, TypeError) as e:
                print(f"Error decoding JSON or TypeError: {e}. Retrying...")
                continue
        
        # Finally, save the plan
        with open(full_output_path, 'w', encoding='utf-8') as file:
            json.dump(planning, file, indent=4, ensure_ascii=False)

        print(f"Planning saved to: {full_output_path}")

def generate_instagram_posts():

    # --- 1st part: Some inital chec
    # ks ---
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
    """
    Upload posts for a selected profile.
    
    Steps:
      1) Ask the user which profile to upload.
      2) Loop through the weeks and days of the selected profile under:
           resources/outputs/instagram_profiles/{profile_name}/posts
         and check that each day folder contains the required files.
      3) For each day, read the upload_times.txt file (and captions.txt).
      4) For each post, wait until the scheduled upload time and then
         upload the post via Meta (GraphAPI).
      5) Also simulate an upload to Fanvue.
    """
    # Instantiate the Meta uploader
    uploader_meta = GraphAPI()
    
    # --- Step 1: Choose profile ---
    profiles_dir = os.path.join('.', 'resources', 'outputs', 'instagram_profiles')
    if not os.path.isdir(profiles_dir):
        print(f"Error: Profiles folder not found at {profiles_dir}")
        return

    available_profiles = [d for d in os.listdir(profiles_dir) if os.path.isdir(os.path.join(profiles_dir, d))]
    if not available_profiles:
        print("No profiles found in the planning outputs.")
        return

    print("Available profiles:")
    for idx, profile in enumerate(available_profiles):
        print(f"  {idx + 1}: {profile}")
    
    profile_input = input("Select profile number to upload: ")
    try:
        profile_idx = int(profile_input.strip()) - 1
        if profile_idx < 0 or profile_idx >= len(available_profiles):
            print("Invalid profile number.")
            return
        selected_profile = available_profiles[profile_idx]
    except Exception as e:
        print("Error processing input:", e)
        return

    posts_folder = os.path.join(profiles_dir, selected_profile, "posts")
    if not os.path.isdir(posts_folder):
        print(f"Posts folder not found for profile '{selected_profile}' at {posts_folder}.")
        return

    # --- Step 2: Iterate over weeks and days ---
    for week in sorted(os.listdir(posts_folder)):
        week_folder = os.path.join(posts_folder, week)
        if not os.path.isdir(week_folder):
            continue
        print(f"\nProcessing week: {week}")
        
        for day in sorted(os.listdir(week_folder)):
            day_folder = os.path.join(week_folder, day)
            if not os.path.isdir(day_folder):
                continue
            print(f"\nProcessing day folder: {day_folder}")

            # Check that required files exist
            captions_file_path = os.path.join(day_folder, "captions.txt")
            upload_times_file_path = os.path.join(day_folder, "upload_times.txt")
            if not os.path.isfile(captions_file_path):
                print(f"Error: captions.txt not found in {day_folder}. Skipping this day.")
                continue
            if not os.path.isfile(upload_times_file_path):
                print(f"Error: upload_times.txt not found in {day_folder}. Skipping this day.")
                continue

            # --- Step 3: Read captions and upload times ---
            try:
                with open(captions_file_path, 'r', encoding='utf-8') as f:
                    captions_content = f.read().strip()
                # Assuming captions are separated by a double newline.
                captions = [cap.strip() for cap in captions_content.split("\n\n") if cap.strip()]
            except Exception as e:
                print(f"Error reading captions.txt in {day_folder}: {e}")
                continue

            try:
                with open(upload_times_file_path, 'r', encoding='utf-8') as f:
                    upload_times = [line.strip() for line in f if line.strip()]
            except Exception as e:
                print(f"Error reading upload_times.txt in {day_folder}: {e}")
                continue

            num_posts = len(upload_times)
            if len(captions) != num_posts:
                print(f"Warning: Number of captions ({len(captions)}) and upload times ({num_posts}) do not match in {day_folder}.")

            # Look for images. Prefer a dedicated 'images' subfolder if it exists.
            images_folder = os.path.join(day_folder, "images")
            if os.path.isdir(images_folder):
                image_files = [os.path.join(images_folder, f) 
                               for f in sorted(os.listdir(images_folder))
                               if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            else:
                image_files = [os.path.join(day_folder, f) 
                               for f in sorted(os.listdir(day_folder))
                               if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

            if not image_files:
                print(f"Error: No image files found in {day_folder}. Skipping this day.")
                continue

            # --- Step 4: Process and upload each post ---
            for i in range(num_posts):
                caption = captions[i] if i < len(captions) else ""
                upload_time_str = upload_times[i]

                # Parse the scheduled upload time (assume "YYYY-MM-DD HH:MM:SS" format)
                try:
                    scheduled_time = datetime.strptime(upload_time_str, "%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    print(f"Error parsing upload time '{upload_time_str}' in {day_folder}: {e}. Skipping post {i+1}.")
                    continue

                now = datetime.now()
                if scheduled_time > now:
                    wait_seconds = (scheduled_time - now).total_seconds()
                    print(f"Waiting for {wait_seconds:.0f} seconds until scheduled time {scheduled_time} for post {i+1}...")
                    sleep(wait_seconds)
                else:
                    print(f"Scheduled time {scheduled_time} for post {i+1} has already passed. Uploading immediately.")

                # Determine the image file for this post.
                if i < len(image_files):
                    image_path = image_files[i]
                else:
                    image_path = image_files[-1]
                    print(f"Warning: Not enough images for post {i+1} in {day_folder}. Using the last available image.")

                # Upload to Meta using GraphAPI.
                print(f"Uploading post {i+1} from {day_folder} to Meta...")
                try:
                    # This assumes that GraphAPI has an upload_post() method.
                    response_meta = uploader_meta.upload_post(caption=caption, image_path=image_path)
                    print(f"Meta upload response: {response_meta}")
                except Exception as e:
                    print(f"Error uploading post {i+1} to Meta: {e}")

                # --- Step 5: Simulate uploading to Fanvue ---
                print(f"Uploading post {i+1} from {day_folder} to Fanvue...")
                try:
                    # Replace the following with an actual Fanvue API call if available.
                    print(f"Simulated Fanvue upload complete for post {i+1}.")
                except Exception as e:
                    print(f"Error uploading post {i+1} to Fanvue: {e}")

    print("Upload process completed.")

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        generate_instagram_planning()

    if GENERATE_POSTS:
        generate_instagram_posts()

    if UPLOAD_POSTS:
        upload_posts()
