import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mains.instagram.planning import generate_instagram_planning
from mains.instagram.posts import generate_instagram_posts
from mains.instagram.uploader import upload_posts

EXECUTE_PLANNING = False   # Set to True for planning
GENERATE_POSTS = False    # Set to True for generating posts
UPLOAD_POSTS = True      # Set to True for uploading posts

PLANNING_TEMPLATE_FOLDER = os.path.join('.', 'resources', 'inputs', 'instagram_profiles') 
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'instagram', 'prompts', 'posts')

OUTPUT_FOLDER_BASE_PATH = os.path.join('.', 'resources', 'outputs')
OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join('.', 'resources', 'outputs', 'instagram_profiles')
OUTPUT_FOLDER_BASE_PATH_POSTS = os.path.join('.', 'resources', 'outputs', 'instagram_profiles', 'laura_vigne', 'posts')

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        generate_instagram_planning(PLANNING_TEMPLATE_FOLDER, OUTPUT_FOLDER_BASE_PATH_PLANNING)

    if GENERATE_POSTS:
        generate_instagram_posts(OUTPUT_FOLDER_BASE_PATH_PLANNING)

    if UPLOAD_POSTS:
        upload_posts(OUTPUT_FOLDER_BASE_PATH_PLANNING)
