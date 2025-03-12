import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mains.planning_manager import PlanningManager
from mains.uploader import upload_posts
from mains.publications_generator import PublicationsGenerator

EXECUTE_PLANNING = True   # Set to True for planning
GENERATE_POSTS = False    # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True for uploading posts

# Updated paths for new structure
META_PROFILES_BASE_PATH = os.path.join('.', 'resources', 'meta_profiles')
POST_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'meta', 'prompts', 'posts')  # Updated path

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        planner = PlanningManager(
            planning_template_folder=META_PROFILES_BASE_PATH,
            platform_name="meta",
            llm_module_path="llm.meta_llm",  # Simplified path
            llm_class_name="MetaLLM",  
            llm_method_name="generate_meta_planning"  
        )
        planner.plan()

    if GENERATE_POSTS:
        generator = PublicationsGenerator(
            post_template_folder=POST_TEMPLATE_FOLDER,
            platform_name="meta",
            llm_module_path="llm.meta_llm",  # Simplified path
            llm_class_name="MetaLLM",
            llm_method_name="generate_meta_posts"
        )
        generator.generate()

    if UPLOAD_POSTS:
        pass
        #upload_posts(META_PROFILES_BASE_PATH)