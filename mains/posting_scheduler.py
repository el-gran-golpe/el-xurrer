import os
from datetime import datetime, timezone
from time import sleep
from bot_services.meta_api.graph_api import GraphAPI

def upload_posts(profiles_base_path):
    """
    Upload posts for a selected profile.
    """
    # Instantiate the Meta uploader
    uploader_meta = GraphAPI()
    
    # Get available profiles from new structure
    available_profiles = []
    for profile_name in os.listdir(profiles_base_path):
        profile_path = os.path.join(profiles_base_path, profile_name)
        if os.path.isdir(profile_path):
            outputs_posts_path = os.path.join(profile_path, "outputs", "posts")
            if os.path.isdir(outputs_posts_path) and os.listdir(outputs_posts_path):
                available_profiles.append((profile_name, "new"))
    
    # Check old structure if needed
    old_profiles_path = os.path.join('resources', 'outputs', 'instagram_profiles')
    if os.path.isdir(old_profiles_path):
        for profile_name in os.listdir(old_profiles_path):
            profile_path = os.path.join(old_profiles_path, profile_name)
            if os.path.isdir(profile_path):
                posts_path = os.path.join(profile_path, "posts")
                if os.path.isdir(posts_path) and os.listdir(posts_path):
                    # Only add if not already in new structure
                    if not any(p[0] == profile_name for p in available_profiles):
                        available_profiles.append((profile_name, "old"))
                        print(f"Warning: Using posts from old structure for {profile_name}")

    assert available_profiles, "No profiles found with posts to upload."

    # Display available profiles
    print("Available profiles:")
    for idx, (profile, structure) in enumerate(available_profiles):
        print(f"  {idx + 1}: {profile} {'(old structure)' if structure == 'old' else ''}")
    
    profile_input = input("Select profile number to upload: ")

    try:
        profile_idx = int(profile_input.strip()) - 1
        assert 0 <= profile_idx < len(available_profiles), "Invalid profile number."
        selected_profile, structure = available_profiles[profile_idx]
    except Exception as e:
        print("Error processing input:", e)
        return

    # Determine posts folder based on structure
    if structure == "new":
        posts_folder = os.path.join(profiles_base_path, selected_profile, "outputs", "posts")
    else:  # old structure
        posts_folder = os.path.join('resources', 'outputs', 'instagram_profiles', selected_profile, "posts")

    assert os.path.isdir(posts_folder), f"Posts folder not found for profile '{selected_profile}' at {posts_folder}."

    # Iterate over weeks and days
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

            # Check that captions and upload_times files exist
            captions_file_path = os.path.join(day_folder, "captions.txt")
            upload_times_file_path = os.path.join(day_folder, "upload_times.txt")
            assert os.path.isfile(captions_file_path), f"Error: captions.txt not found in {day_folder}. Skipping this day."
            assert os.path.isfile(upload_times_file_path), f"Error: upload_times.txt not found in {day_folder}. Skipping this day."
            # Check that at least one .png file exists
            png_files = [f for f in os.listdir(day_folder) if f.lower().endswith('.png')]
            assert png_files, f"Error: No .png files found in {day_folder}. Skipping this day."

            # Read captions and upload times
            try:
                with open(captions_file_path, 'r', encoding='utf-8') as f:
                    caption = f.read().strip()
            except Exception as e:
                print(f"Error reading captions.txt in {day_folder}: {e}")
                continue

            try:
                with open(upload_times_file_path, 'r', encoding='utf-8') as f:
                    upload_time_str = f.read().strip()
            except Exception as e:
                print(f"Error reading upload_times.txt in {day_folder}: {e}")
                continue

            # Look for images in the day folder.
            image_files = [os.path.join(day_folder, f) 
                            for f in sorted(os.listdir(day_folder))
                            if f.lower().endswith('.png')]

            assert image_files, f"Error: No image files found in {day_folder}. Skipping this day."

            # Process and upload the post
            # Parse the scheduled upload time
            try:
                scheduled_time = datetime.strptime(upload_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except Exception as e:
                print(f"Error parsing upload time '{upload_time_str}' in {day_folder}: {e}. Skipping this day.")
                continue

            now = datetime.now(timezone.utc)
            if scheduled_time > now:
                wait_seconds = (scheduled_time - now).total_seconds()
                print(f"Waiting for {wait_seconds:.0f} seconds until scheduled time {scheduled_time}...")
                sleep(wait_seconds)
            else:
                print(f"Scheduled time {scheduled_time} has already passed. Uploading immediately.")

            # Upload to Meta using GraphAPI.
            print(f"Uploading post from {day_folder} to Meta...")
            try:
                response_instagram = uploader_meta.upload_instagram_publication(image_files, caption)
                response_facebook = uploader_meta.upload_facebook_publication(image_files, caption)
                if response_instagram and response_facebook:
                    print(f"Post uploaded successfully to Instagram: {response_instagram}")
                    print(f"Post uploaded successfully to Facebook: {response_facebook}")
                else:
                    print(f"Failed to upload post.")
            except Exception as e:
                print(f"Error uploading post: {e}")

    print("Upload process completed.")
