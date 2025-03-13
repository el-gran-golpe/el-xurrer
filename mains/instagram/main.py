import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mains.planning_manager import generate_instagram_planning
from mains.publications_generator import generate_instagram_posts
from mains.posting_scheduler import upload_posts

EXECUTE_PLANNING = True   # Set to True for planning
GENERATE_POSTS = False    # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True for uploading posts

# Updated paths for new structure
INSTAGRAM_PROFILES_BASE_PATH = os.path.join('.', 'resources', 'instagram_profiles')
PLANNING_TEMPLATE_FOLDER = INSTAGRAM_PROFILES_BASE_PATH
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'instagram', 'prompts', 'posts')

# No longer needed with new structure
# OUTPUT_FOLDER_BASE_PATH = os.path.join('.', 'resources', 'outputs')
# OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join('.', 'resources', 'outputs', 'instagram_profiles')
# OUTPUT_FOLDER_BASE_PATH_POSTS = os.path.join('.', 'resources', 'outputs', 'instagram_profiles', 'laura_vigne', 'posts')

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        generate_instagram_planning(PLANNING_TEMPLATE_FOLDER)

    if GENERATE_POSTS:
        generate_instagram_posts(INSTAGRAM_PROFILES_BASE_PATH)

    if UPLOAD_POSTS:
        upload_posts(INSTAGRAM_PROFILES_BASE_PATH)
