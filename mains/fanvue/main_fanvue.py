import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from mains.planning_manager import PlanningManager
from mains.publications_generator import PublicationsGenerator
from mains.posting_scheduler import PostingScheduler

EXECUTE_PLANNING = True   # Set to True for planning
GENERATE_POSTS = False    # Set to True for generating posts
UPLOAD_POSTS = False      # Set to True for uploading posts

# Paths for Fanvue
FANVUE_PROFILES_BASE_PATH = os.path.join('.', 'resources', 'fanvue_profiles')
PLANNING_TEMPLATE_FOLDER = FANVUE_PROFILES_BASE_PATH

if __name__ == '__main__':
    if EXECUTE_PLANNING:
        planner = PlanningManager(
            planning_template_folder=PLANNING_TEMPLATE_FOLDER,
            platform_name="fanvue",
            llm_module_path="llm.fanvue_llm",
            llm_class_name="FanvueLLM",
            llm_method_name="generate_fanvue_planning",
            use_initial_conditions=False  # Skip initial conditions for Fanvue
        )
        planner.plan()

    if GENERATE_POSTS:
        generator = PublicationsGenerator(
            publication_template_folder=FANVUE_PROFILES_BASE_PATH,
            platform_name="fanvue"
        )
        generator.generate()

    if UPLOAD_POSTS:
        scheduler = PostingScheduler(
            publication_base_folder=FANVUE_PROFILES_BASE_PATH,
            platform_name="fanvue",
            api_module_path="bot_services.fanvue_poster_bot.fanvue_publisher_se",
            api_class_name="FanvuePublisher"
        )
        scheduler.upload()