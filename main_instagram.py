import os
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv
from uploading_apis.instagram.uploader_instagram import InstagramAPI

# Load environment variables from the specific .env file
dotenv_path = os.path.join(r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\uploading_apis\instagram", "api_key_instagram.env")
load_dotenv(dotenv_path)

# Retrieve the Instagram API access token from the environment
ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")

# Correct BASE_FOLDER path
BASE_FOLDER = r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\instagram_profiles\laura_vigne\output"

def process_folder_for_date(date_folder):
    date_path = os.path.join(BASE_FOLDER, date_folder)
    logger.debug(f"Looking for folder: {date_path}")

    caption_file = os.path.join(date_path, "caption.txt")
    location_file = os.path.join(date_path, "location.txt")
    images_folder = os.path.join(date_path, "images")

    if os.path.isdir(images_folder) and os.path.isfile(caption_file):
        with open(caption_file, 'r') as file:
            caption = file.read()

        location = None
        if os.path.isfile(location_file):
            with open(location_file, 'r') as file:
                location = file.read()

        image_files = [os.path.join(images_folder, img) for img in os.listdir(images_folder) if img.endswith(('jpg', 'jpeg', 'png'))]
        if image_files:
            api = InstagramAPI(ACCESS_TOKEN)
            api.upload_image(image_files, caption, location)
        else:
            logger.warning(f"No images found in folder: {images_folder}")
    else:
        logger.warning(f"Missing caption or images in folder: {date_folder}")

def run_script():
    # Use today's date
    target_date_str = datetime.now().strftime("%Y-%m-%d")
    target_folder = os.path.join(BASE_FOLDER, target_date_str)
    
    if os.path.isdir(target_folder):
        process_folder_for_date(target_date_str)
    else:
        logger.error(f"No folder found for date: {target_date_str}")

if __name__ == '__main__':
    run_script()
