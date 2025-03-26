import os
import sys

from main_components.planning_manager import PlanningManager
from main_components.posting_scheduler import PostingScheduler
from main_components.publications_generator import PublicationsGenerator

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


EXECUTE_PLANNING = False
GENERATE_PUBLICATIONS = True
UPLOAD_PUBLICATIONS = False

# Updated paths for new structure
META_PROFILES_BASE_PATH = os.path.join(".", "resources", "meta_profiles")

if __name__ == "__main__":
    if EXECUTE_PLANNING:
        planner = PlanningManager(
            planning_template_folder=META_PROFILES_BASE_PATH,
            platform_name="meta",
            llm_module_path="llm.meta_llm",
            llm_class_name="MetaLLM",
            llm_method_name="generate_meta_planning",
            use_initial_conditions=True,  # Explicitly use initial conditions
        )
        planner.plan()

    if GENERATE_PUBLICATIONS:
        generator = PublicationsGenerator(
            publication_template_folder=META_PROFILES_BASE_PATH, platform_name="meta"
        )
        generator.generate()

    if UPLOAD_PUBLICATIONS:
        scheduler = PostingScheduler(
            publication_base_folder=META_PROFILES_BASE_PATH,
            platform_name="meta",
            api_module_path="bot_services.meta_api.graph_api",
            api_class_name="GraphAPI",
        )
        scheduler.upload()
