import time
from datetime import datetime, timezone
from multiprocessing import Process
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from main_components.common.constants import Platform
from main_components.common.profile import Profile, ProfileManager
from main_components.planning_manager import PlanningManager
from main_components.posting_scheduler import PostingScheduler, _iter_day_folders
from main_components.publications_generator import PublicationsGenerator
from generation_tools.image_generator.comfy_local import ComfyLocal
from automation.fanvue_client.fanvue_publisher import FanvuePublisher

# CLI application for the Fanvue pipeline
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
        logger.success("Profiles loaded and validated successfully.")
    except Exception as error:
        logger.critical(f"Failed to load profiles: {error}")
        raise typer.Exit(1)


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
        cleaned = [n.strip() for n in names.split(",")]
        return [profile_manager.get_profile_by_name(n) for n in cleaned]

    logger.error("No profile indexes or names provided.")
    raise typer.BadParameter("Provide at least one profile index or name.")


@app.callback()
def load_profiles_callback() -> None:
    """
    Ensures profiles are loaded before running any command.
    """
    pre_command_callback()


@app.command()
def list_profiles() -> None:
    """List available profiles with their indexes and names."""
    index = 0
    while True:
        try:
            profile = profile_manager.get_profile_by_index(index)
            typer.echo(f"{index}: {profile.name}")
            index += 1
        except Exception:
            break


def do_plan(profiles: list[Profile], use_initial_conditions: bool) -> None:
    """
    Run the planning phase for given profiles.
    """
    PlanningManager(
        template_profiles=profiles,
        platform_name=Platform.FANVUE,
        use_initial_conditions=use_initial_conditions,
    ).plan()
    logger.success("Planning completed.")


def do_generate(profiles: list[Profile]) -> None:
    workflow_files = {
        profile.name: RESOURCES_DIR
        / profile.name
        / f"{profile.name}_comfyworkflow.json"
        for profile in profiles
    }
    for profile in profiles:
        client = ComfyLocal(workflow_path=workflow_files[profile.name])
        try:
            client.client.get_json(f"http://{client.server}/system_stats")
        except Exception as error:
            logger.critical(
                f"Failed to connect to ComfyUI for '{profile.name}': {error}"
            )
            raise typer.Exit(1)

    PublicationsGenerator(
        template_profiles=profiles,
        platform_name=Platform.FANVUE,
        image_generator_tool=ComfyLocal,
        workflow_files=workflow_files,  # Pass mapping for multi-threaded generation
    ).generate()
    logger.success("Generation completed.")


def do_schedule(profiles: list[Profile]) -> None:
    """
    Run the scheduling/upload phase for given profiles.
    """
    PostingScheduler(
        template_profiles=profiles,
        platform_name=Platform.FANVUE,
        publisher=FanvuePublisher,
    ).upload()
    logger.success("Scheduling completed.")


@app.command()
def plan(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
) -> None:
    """CLI: Run the planning phase."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    do_plan(profiles, use_initial_conditions)


@app.command()
def generate(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
) -> None:
    """CLI: Run the generation phase."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    do_generate(profiles)


@app.command()
def schedule(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
) -> None:
    """CLI: Run the scheduling phase."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    do_schedule(profiles)


def background_worker(profile: Profile) -> None:
    """
    Continuous loop: do_plan → do_generate → do_schedule → sleep → update lore.
    """
    use_initial_conditions = True  # Let's always use this in the pipeline
    while True:
        logger.info(f"[{profile.name}] Cycle start.")
        do_plan([profile], use_initial_conditions)
        do_generate([profile])
        do_schedule([profile])
        logger.success(f"[{profile.name}] Cycle complete.")

        pub_dir = (
            Path(profile.platform_info[Platform.FANVUE].outputs_path) / "publications"
        )
        upload_times: list[datetime] = []
        for day_folder in _iter_day_folders(pub_dir):
            ts = (day_folder / "upload_times.txt").read_text().strip()
            upload_times.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))

        if not upload_times:
            logger.error(f"[{profile.name}] No upload_times; stopping.")
            return

        next_run = max(upload_times)
        now = datetime.now(next_run.tzinfo)
        sleep_seconds = (next_run - now).total_seconds()
        if sleep_seconds > 0:
            logger.info(
                f"[{profile.name}] Waiting {int(sleep_seconds)}s until {next_run}"
            )
            time.sleep(sleep_seconds)

        # TODO: check this
        # Append summary lore
        summary_lines = [f"## Summary at {datetime.now(timezone.utc).isoformat()}"]
        for day_folder in sorted(pub_dir.iterdir()):
            date = (day_folder / "upload_times.txt").read_text().strip()
            caption = (day_folder / "captions.txt").read_text().strip()
            summary_lines.append(f"- **{date}**: {caption}")

        lore_file = RESOURCES_DIR / profile.name / "initial_conditions.md"
        lore_file.parent.mkdir(parents=True, exist_ok=True)
        with open(lore_file, "a", encoding="utf-8") as lf:
            lf.write("\n" + "\n".join(summary_lines) + "\n")

        use_initial_conditions = True


@app.command(help="Run the full Fanvue pipeline continuously for selected profiles.")
def start_pipeline(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
) -> None:
    """
    Spawn one process per profile, each running an infinite pipeline loop.
    """
    logger.warning(
        "\n"
        + "=" * 60
        + "\n⚠️  IMPORTANT: Make sure ComfyUI is running in the background! ⚠️\n"
        + "=" * 60
    )
    profiles = resolve_profiles(profile_indexes, profile_names)
    workers: list[Process] = []

    for profile in profiles:
        worker = Process(
            target=background_worker,
            args=(profile,),
            daemon=False,
        )
        worker.start()
        workers.append(worker)

    for worker in workers:
        worker.join()


if __name__ == "__main__":
    app()
