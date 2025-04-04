import os
import sys
from typing import Optional

import typer

from main_components.base_main import BaseMain
from main_components.planning_manager import PlanningManager

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_components.posting_scheduler import PostingScheduler
from main_components.publications_generator import PublicationsGenerator

# Updated paths for new structure
META_PROFILES_BASE_PATH = os.path.join(".", "resources", "meta_profiles")
# - ProfileName
#     - inputs
#     - outputs

app = typer.Typer()


@app.command()
def profiles():
    """List available profiles."""
    base = BaseMain()
    base.find_available_items()


ProfileIdentifier = int


@app.command()
def plan(
    profiles_index: list[ProfileIdentifier] = typer.Option(
        [], "-p", "--profiles", help="Index of the profile to use"
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help="Comma-separated list of profile names"
    ),
):
    if len(profiles_index) == 0 and profile_names is None:
        raise ValueError(
            "Please provide at least one profile index or a list of profile names."
        )

    if len(profiles_index) > 0:
        pass

    else:
        pass

    planner = PlanningManager(
        planning_template_folder=META_PROFILES_BASE_PATH,
        template_profiles=profiles,  # FIXME: Laura vigne and others goes here
        platform_name="meta",
        llm_module_path="llm.meta_llm",
        llm_class_name="MetaLLM",
        llm_method_name="generate_meta_planning",
        use_initial_conditions=True,  # Explicitly use initial conditions
    )
    planner.plan()


@app.command()
def generate_publications():
    generator = PublicationsGenerator(
        publication_template_folder=META_PROFILES_BASE_PATH, platform_name="meta"
    )
    generator.generate()


@app.command()
def upload():
    scheduler = PostingScheduler(
        publication_base_folder=META_PROFILES_BASE_PATH,
        platform_name="meta",
        api_module_path="bot_services.meta_api.graph_api",
        api_class_name="GraphAPI",
    )
    scheduler.upload()


if __name__ == "__main__":
    app()
