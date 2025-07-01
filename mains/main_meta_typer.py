import os
import sys
from pathlib import Path
from typing import Optional
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import typer

from main_components.constants import Platform
from main_components.planning_manager import PlanningManager
from main_components.profile import ProfileManager
from main_components.posting_scheduler import PostingScheduler
from main_components.publications_generator import PublicationsGenerator

# Updated paths for new structure
META_PROFILES_BASE_PATH = os.path.join(".", "resources", Platform.META.value)

logger = logging.getLogger(__name__)

app = typer.Typer()
profile_manager = ProfileManager(Path.cwd().joinpath(Path("resources")))

ProfileIdentifier = int


@app.command()
def list_profiles():
    """List available profiles."""
    profiles = profile_manager.load_profiles()
    if len(profiles) == 0:
        print("No profiles found.")
        return

    for i, profile in enumerate(profiles):
        print(f"{i}: {profile.name}")


@app.command()
def plan(
    profiles_index: list[ProfileIdentifier] = typer.Option(
        [], "-p", "--profile-indexes", help="Index of the profile to use"
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help="Comma-separated list of profile names"
    ),
    overwrite_outputs: bool = typer.Option(
        False, "-o", "--overwrite-outputs", help="Overwrite existing outputs"
    ),
):
    if len(profiles_index) == 0 and profile_names is None:
        raise ValueError(
            "Please provide at least one profile index or a list of profile names."
        )

    if len(profiles_index) > 0:
        profiles = [
            profile_manager.get_profile_by_index(index) for index in profiles_index
        ]

    else:
        assert profile_names is not None, (
            "Profile names cannot be None if index is not provided."
        )
        profile_names_splitted = profile_names.split(",")
        profiles = [
            profile_manager.get_profile_by_name(name.strip())
            for name in profile_names_splitted
        ]

    filtered_profiles = []
    if not overwrite_outputs:
        # Filter profiles from list if they have files in meta platform output folder
        for profile in profiles:
            meta_outputs = profile.platform_info[Platform.META].outputs_path
            if len(os.listdir(meta_outputs)) > 0:
                print(
                    f"Profile {profile.name} has existing outputs in {meta_outputs}. Skipping."
                )
            else:
                filtered_profiles.append(profile)
    else:
        filtered_profiles = profiles

    planner = PlanningManager(
        # planning_template_folder=META_PROFILES_BASE_PATH,
        template_profiles=filtered_profiles,
        platform_name=Platform.META,
        llm_module_path="llm.meta_llm",
        llm_class_name="MetaLLM",
        llm_method_name="generate_meta_planning",
        use_initial_conditions=True,  # Explicitly use initial conditions
    )
    planner.plan()


@app.command()
def generate_publications(
    profiles_index: list[ProfileIdentifier] = typer.Option(
        [], "-p", "--profile-indexes", help="Index of the profile to use"
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help="Comma-separated list of profile names"
    ),
):
    if len(profiles_index) > 0:
        profiles = [
            profile_manager.get_profile_by_index(index) for index in profiles_index
        ]

    else:
        assert profile_names is not None, (
            "Profile names cannot be None if index is not provided."
        )
        profile_names_splitted = profile_names.split(",")
        profiles = [
            profile_manager.get_profile_by_name(name.strip())
            for name in profile_names_splitted
        ]

    generator = PublicationsGenerator(
        template_profiles=profiles,
        platform_name=Platform.META,
        image_generator_tool="generation_tools.image_generator.comfy_local.ComfyLocal",
    )
    generator.generate()


@app.command()
def schedule_posts(
    profiles_index: list[ProfileIdentifier] = typer.Option(
        [], "-p", "--profile-indexes", help="Index of the profile to use"
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help="Comma-separated list of profile names"
    ),
):
    if len(profiles_index) > 0:
        profiles = [
            profile_manager.get_profile_by_index(index) for index in profiles_index
        ]

    else:
        assert profile_names is not None, (
            "Profile names cannot be None if index is not provided."
        )

        profile_names_splitted = profile_names.split(",")
        profiles = [
            profile_manager.get_profile_by_name(name.strip())
            for name in profile_names_splitted
        ]

    scheduler = PostingScheduler(
        template_profiles=profiles,
        platform_name=Platform.META,
        api_module_path="automation.meta_api.graph_api",
        api_class_name="GraphAPI",
    )
    scheduler.upload()


@app.command(
    help="Execute the complete Meta content pipeline: planning, generating publications, and scheduling posts in sequence."
)
def execute_pipeline(
    profiles_index: list[ProfileIdentifier] = typer.Option(
        [], "-p", "--profile-indexes", help="Index of the profile to use"
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help="Comma-separated list of profile names"
    ),
    overwrite_outputs: bool = typer.Option(
        False,
        "-o",
        "--overwrite-outputs",
        help="Overwrite existing outputs for planning",
    ),
):
    """Run the complete content pipeline: plan, generate publications, and schedule posts in sequence."""
    # First run planning
    logger.info("Step 1: Planning content...")
    plan(profiles_index, profile_names, overwrite_outputs)

    # Then generate publications
    logger.info("Step 2: Generating publications...")
    generate_publications(profiles_index, profile_names)

    # Finally schedule posts
    logger.info("Step 3: Scheduling posts...")
    schedule_posts(profiles_index, profile_names)

    logger.info("All steps completed successfully!")


if __name__ == "__main__":
    # read profiles
    profile_manager.load_profiles()
    app()
