import threading
from typing import Optional

import typer
from pathlib import Path
from loguru import logger

from main_components.common.constants import Platform
from main_components.common.profile import ProfileManager, Profile
from main_components.planning_manager import PlanningManager
from main_components.publications_generator import PublicationsGenerator
from main_components.posting_scheduler import PostingScheduler
from generation_tools.image_generator.comfy_local import ComfyLocal
from automation.fanvue_client.fanvue_publisher import FanvuePublisher

app = typer.Typer()

# Paths and profile manager
ROOT_DIR = Path(__file__).resolve().parent.parent
RESOURCES_DIR = ROOT_DIR / "resources"
profile_manager = ProfileManager(RESOURCES_DIR)


def pre_command_callback() -> None:
    """
    Load and validate profiles before any CLI command.

    Exits the program if loading fails.
    """
    try:
        profile_manager.load_profiles()
    except Exception as e:
        logger.error(f"Failed to load profiles: {e}")
        raise typer.Exit(1)


@app.callback()
def load_profiles_callback() -> None:
    """
    Ensures profiles are loaded before running any command.
    """
    pre_command_callback()


@app.command()
def list_profiles() -> None:
    """List available profiles with their indexes and names."""
    idx = 0
    while True:
        try:
            p = profile_manager.get_profile_by_index(idx)
            typer.echo(f"{idx}: {p.name}")
            idx += 1
        except Exception:
            break


@app.command()
def plan(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
) -> None:
    """Run the planning phase."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    PlanningManager(
        template_profiles=profiles,
        platform_name=Platform.FANVUE,
        use_initial_conditions=use_initial_conditions,
    ).plan()
    logger.success("Planning completed.")


@app.command()
def generate(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
) -> None:
    """Run the generation phase, ensuring ComfyUI is available."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    for profile in profiles:
        logger.info(f"▶️  Checking ComfyUI for {profile.name}…")
        client = ComfyLocal(
            workflow_path=RESOURCES_DIR
            / profile.name
            / f"{profile.name}_comfyworkflow.json"
        )
        try:
            client.check_connection()
        except Exception as e:
            logger.error(f"ComfyUI server not reachable: {e}")
            raise typer.Exit(code=1)

        logger.info(f"▶️  Generating assets for {profile.name}…")
        PublicationsGenerator(
            template_profiles=[profile],
            platform_name=Platform.FANVUE,
            image_generator_tool=client,
        ).generate()
        logger.success(f"[{profile.name}] Asset generation done.")


@app.command()
def schedule(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
) -> None:
    """Run the scheduling/upload phase (blocks until done)."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    PostingScheduler(
        template_profiles=profiles,
        platform_name=Platform.FANVUE,
        publisher=FanvuePublisher,
    ).upload()
    logger.success("Scheduling completed.")


@app.command(name="run_all")
def run_all(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    use_initial_conditions: bool = typer.Option(True, "--use-initial-conditions"),
) -> None:
    """
    1) Plan → 2) Generate (serial GPU with ComfyUI check) → 3) Schedule/upload in background threads.
    """
    profiles = resolve_profiles(profile_indexes, profile_names)

    for profile in profiles:
        logger.info(f"▶️ Processing profile '{profile.name}'")

        # Step 1: Plan
        PlanningManager(
            template_profiles=[profile],
            platform_name=Platform.FANVUE,
            use_initial_conditions=use_initial_conditions,
        ).plan()
        logger.success(f"[{profile.name}] Planning done.")

        # Step 2: Check & Generate
        logger.info(f"▶️  Checking ComfyUI for {profile.name}…")
        client = ComfyLocal(
            workflow_path=RESOURCES_DIR
            / profile.name
            / f"{profile.name}_comfyworkflow.json"
        )
        try:
            client.check_connection()
        except Exception as e:
            logger.error(f"ComfyUI server not reachable: {e}")
            raise typer.Exit(code=1)

        logger.info(f"▶️  Generating assets for {profile.name}…")
        PublicationsGenerator(
            template_profiles=[profile],
            platform_name=Platform.FANVUE,
            image_generator_tool=client,
        ).generate()
        logger.success(f"[{profile.name}] Asset generation done.")

        # Step 3: Schedule/upload in background
        def _upload_task(p: Profile):
            PostingScheduler(
                template_profiles=[p],
                platform_name=Platform.FANVUE,
                publisher=FanvuePublisher,
            ).upload()

        t = threading.Thread(target=_upload_task, args=(profile,), daemon=True)
        t.start()
        logger.success(f"[{profile.name}] Upload & scheduler launched in background.")

    logger.success("✅ All profiles processed — background uploads in progress.")


if __name__ == "__main__":
    app()


# Helper to resolve profiles by index or name
def resolve_profiles(indexes: list[int], names: Optional[str]) -> list[Profile]:
    """
    Resolve profiles by index list or comma-separated names.

    Edge case: if both indexes and names are provided, indexes take precedence.

    Raises:
        typer.BadParameter: if neither argument is provided.
    """
    if indexes:
        return [profile_manager.get_profile_by_index(i) for i in indexes]
    if names:
        return [
            profile_manager.get_profile_by_name(n.strip()) for n in names.split(",")
        ]
    raise typer.BadParameter("Must provide either profile_indexes or profile_names.")
