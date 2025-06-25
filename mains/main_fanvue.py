import os
import sys
import pathlib
from typing import Optional

import typer
from loguru import logger

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main_components.constants import Platform
from main_components.planning_manager import PlanningManager
from main_components.profile import ProfileManager
from main_components.posting_scheduler import PostingScheduler
from main_components.publications_generator import PublicationsGenerator

# Configure Loguru
logger.remove()
logger.add(sys.stderr, format="{time} {level} {message}", level="INFO")

app = typer.Typer()
profile_manager = ProfileManager(
    pathlib.Path(__file__).resolve().parent.parent / "resources"
)

ProfileIdentifier = int


@app.command()
def list_profiles():
    """List available profiles."""
    profiles = profile_manager.load_profiles()
    if len(profiles) == 0:
        logger.info("No profiles found.")
        return

    for i, profile in enumerate(profiles):
        logger.info(f"{i}: {profile.name}")


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


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
        for profile in profiles:
            fanvue_outputs = profile.platform_info[Platform.FANVUE].outputs_path
            if len(os.listdir(fanvue_outputs)) > 0:
                logger.info(
                    f"Profile {profile.name} has existing outputs in {fanvue_outputs}. Skipping."
                )
            else:
                filtered_profiles.append(profile)
    else:
        filtered_profiles = profiles

    planner = PlanningManager(
        template_profiles=filtered_profiles,
        platform_name=Platform.FANVUE,
        llm_module_path="llm.fanvue_llm",
        llm_class_name="FanvueLLM",
        llm_method_name="generate_fanvue_planning",
        use_initial_conditions=True,  # Explicitly use initial conditions
    )
    planner.plan()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


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
        platform_name=Platform.FANVUE,
    )
    generator.generate()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


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
        api_module_path="bot_services.meta_api.graph_api",
        api_class_name="GraphAPI",
    )
    scheduler.upload()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------


@app.command(
    help="Execute the full Fanvue pipeline (independent of Meta): planning + generating publications + scheduling posts."
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

    # To debug, call the function directly with your desired parameters
    # plan(profile_names="laura_vigne", profiles_index=[], overwrite_outputs=False)
    generate_publications(profile_names="laura_vigne", profiles_index=[])

    # To run the full command-line app, comment out the direct call above
    # and uncomment the line below.
    # app()
