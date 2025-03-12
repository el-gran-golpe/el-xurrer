import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mains.planning_manager import PlanningManager
from mains.publications_generator import PublicationsGenerator
# Import other Fanvue-specific modules here

EXECUTE_PLANNING = True   # Set to True for planning
GENERATE_POSTS = False    # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True for uploading posts

# Paths for Fanvue
FANVUE_PROFILES_BASE_PATH = os.path.join('.', 'resources', 'fanvue_profiles')
PLANNING_TEMPLATE_FOLDER = FANVUE_PROFILES_BASE_PATH

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        # Create Fanvue planning manager with appropriate configuration
        planner = PlanningManager(
            planning_template_folder=PLANNING_TEMPLATE_FOLDER,
            platform_name="fanvue",
            llm_module_path="llm.fanvue.fanvue_llm",
            llm_class_name="FanvueLLM",
            llm_method_name="generate_fanvue_planning"
        )
        planner.plan()

    if GENERATE_POSTS:
        generator = PublicationsGenerator(
            post_template_folder=os.path.join('.', 'llm', 'fanvue', 'prompts', 'posts'),
            platform_name="fanvue",
            llm_module_path="llm.fanvue_llm",
            llm_class_name="FanvueLLM",
            llm_method_name="generate_fanvue_posts"
        )
        generator.generate()

    if UPLOAD_POSTS:
        # Implement post uploading for Fanvue
        pass