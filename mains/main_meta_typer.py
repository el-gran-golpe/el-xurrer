import sys
from pathlib import Path
from typing import Optional, List

sys.path.append(str(Path(__file__).resolve().parent.parent))

import typer
from loguru import logger

from main_components.common.constants import Platform
from main_components.planning_manager import PlanningManager
from main_components.common.profile import ProfileManager
from main_components.posting_scheduler import PostingScheduler
from main_components.publications_generator import PublicationsGenerator
from automation.meta_api.graph_api import GraphAPI
from generation_tools.image_generator.comfy_local import ComfyLocal

app = typer.Typer()
resource_path = Path(__file__).resolve().parent.parent / "resources"
profile_manager = ProfileManager(resource_path)
ProfileID = int


@app.callback()
def pre_command_callback():
    try:
        profile_manager.load_profiles()
        logger.success("Profiles loaded and validated successfully.")
    except Exception as e:
        logger.critical(f"Failed to load profiles: {e}")
        raise typer.Exit(1)


def get_profiles(profiles_index: List[ProfileID], profile_names: Optional[str]):
    profiles = []
    if profiles_index:
        for idx in profiles_index:
            try:
                profiles.append(profile_manager.get_profile_by_index(idx))
            except Exception as e:
                logger.error(f"Invalid profile index {idx}: {e}")
                raise typer.Exit(1)
    elif profile_names:
        for name in profile_names.split(","):
            try:
                profiles.append(profile_manager.get_profile_by_name(name.strip()))
            except Exception as e:
                logger.error(f"Invalid profile name '{name.strip()}': {e}")
                raise typer.Exit(1)
    else:
        logger.warning("No profile index or name provided.")
        raise typer.BadParameter("Provide at least one profile index or name.")
    return profiles


@app.command()
def list_profiles():
    idx = 0
    found = False
    while True:
        try:
            profile = profile_manager.get_profile_by_index(idx)
            logger.info(f"{idx}: {profile.name}")
            found = True
            idx += 1
        except IndexError:
            if not found:
                logger.warning("No profiles found.")
            break


@app.command()
def plan(
    profiles_index: List[ProfileID] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    overwrite_outputs: bool = typer.Option(False, "-o", "--overwrite-outputs"),
    use_initial_conditions: bool = typer.Option(
        True,
        "--use-initial-conditions/--no-initial-conditions",
        help="Use initial_conditions.md file? Defaults to True.",
    ),
):
    # TODO: I accidentally removed the --overwrite-outputs for fanvue. Please add it back.
    profiles = get_profiles(profiles_index, profile_names)
    filtered_profiles = []
    if not overwrite_outputs:
        for profile in profiles:
            outputs = profile.platform_info[Platform.META].outputs_path
            if any(Path(outputs).iterdir()):
                logger.warning(
                    f"Profile {profile.name} has existing outputs in {outputs}. Skipping."
                )
            else:
                filtered_profiles.append(profile)
    else:
        filtered_profiles = profiles

    if not filtered_profiles:
        logger.warning("No profiles to plan for.")
        return

    planner = PlanningManager(
        template_profiles=filtered_profiles,
        platform_name=Platform.META,
        use_initial_conditions=use_initial_conditions,
    )
    planner.plan()
    logger.success("Planning completed.")


@app.command()
def generate(
    profiles_index: List[ProfileID] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    profiles = get_profiles(profiles_index, profile_names)
    # TODO: update workflow path as needed
    comfy_workflow_path = (
        resource_path / "laura_vigne" / "laura_vigne_comfyworkflow.json"
    )
    comfy_client = ComfyLocal(workflow_path=comfy_workflow_path)

    try:
        logger.info("Checking ComfyUI server connection...")
        comfy_client.client.get_json(f"http://{comfy_client.server}/system_stats")
        logger.success("ComfyUI server connection verified successfully.")
    except Exception as e:
        logger.critical(
            f"Failed to connect to ComfyUI server at {comfy_client.server}: {e}"
        )
        logger.error("Please ensure ComfyUI is running before generating publications.")
        raise typer.Exit(1)

    generator = PublicationsGenerator(
        template_profiles=profiles,
        platform_name=Platform.META,
        image_generator_tool=comfy_client,
    )
    generator.generate()
    logger.success("Publications generated.")


@app.command()
def schedule(
    profiles_index: List[ProfileID] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    profiles = get_profiles(profiles_index, profile_names)
    scheduler = PostingScheduler(
        template_profiles=profiles,
        platform_name=Platform.META,
        publisher=GraphAPI,
    )
    scheduler.upload()
    logger.success("Posts scheduled.")


@app.command(
    help="Execute the full Meta pipeline: planning + generating publications + scheduling posts."
)
def execute_pipeline(
    profiles_index: List[ProfileID] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    overwrite_outputs: bool = typer.Option(False, "-o", "--overwrite-outputs"),
):
    logger.info("Step 1: Planning content...")
    plan(profiles_index, profile_names, overwrite_outputs)
    logger.info("Step 2: Generating publications...")
    generate(profiles_index, profile_names)
    logger.info("Step 3: Scheduling posts...")
    schedule(profiles_index, profile_names)
    logger.success("All steps completed successfully!")


if __name__ == "__main__":
    profile_manager.load_profiles()
    app()
