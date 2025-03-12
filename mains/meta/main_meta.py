import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mains.planning_manager import PlanningManager
from mains.publications_generator import generate_instagram_posts
from mains.uploader import upload_posts

EXECUTE_PLANNING = False   # Set to True for planning
GENERATE_POSTS = False    # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True for uploading posts

# Updated paths for new structure
META_PROFILES_BASE_PATH = os.path.join('.', 'resources', 'meta_profiles')
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'instagram', 'prompts', 'posts')

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        planner = PlanningManager(
            planning_template_folder=META_PROFILES_BASE_PATH,
            platform_name="meta",
            llm_module_path="llm.meta.meta_llm",
            llm_class_name="InstagramLLM",
            llm_method_name="generate_instagram_planning"
        )
        planner.generate()

    if GENERATE_POSTS:
        pass
        #generate_instagram_posts(INSTAGRAM_PROFILES_BASE_PATH)

    if UPLOAD_POSTS:
        pass
        #upload_posts(INSTAGRAM_PROFILES_BASE_PATH)