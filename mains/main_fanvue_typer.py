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
from generation_tools.image_generator.comfy_local import ComfyLocal

from automation.fanvue_client.fanvue_publisher import FanvuePublisher


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

    # TODO: When executing the full pipeline, we should make this dynamic
    # Create ComfyLocal instance
    comfy_client = ComfyLocal(
        workflow_path=pathlib.Path(__file__).resolve().parent.parent
        / "resources"
        / "laura_vigne"
        / "laura_vigne_comfyworkflow.json",
    )

    # Verify ComfyUI server connection before proceeding
    try:
        logger.info("Checking ComfyUI server connection...")
        comfy_client.client.get_json(f"http://{comfy_client.server}/system_stats")
        logger.info("ComfyUI server connection verified successfully")
    except Exception as e:
        logger.error(
            f"Failed to connect to ComfyUI server at {comfy_client.server}: {e}"
        )
        logger.error("Please ensure ComfyUI is running before generating publications")
        raise typer.Exit(1)

    generator = PublicationsGenerator(
        template_profiles=profiles,
        platform_name=Platform.FANVUE,
        image_generator_tool=comfy_client,
    )

    # Future: Switch to Google Drive fetcher
    # generator = PublicationsGenerator(
    #     template_profiles=profiles,
    #     platform_name=Platform.FANVUE,
    #     image_generator_tool=GoogleDriveImageFetcher,  # Just change this line
    # )

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
        platform_name=Platform.FANVUE,
        publisher=FanvuePublisher,
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
    profile_manager.load_profiles()

    # TODO: I don't like using profile indexes, I prefer profile names. but meh, let's leave it for now.

    # To debug, call the function directly with your desired parameters
    # plan(profile_names="laura_vigne", profiles_index=[], overwrite_outputs=False)
    # generate_publications(profile_names="laura_vigne", profiles_index=[])
    schedule_posts(profile_names="laura_vigne", profiles_index=[])

    # To run the full command-line app, comment out the direct call above
    # and uncomment the line below.
    # app()
