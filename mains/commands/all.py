import typer
from sys import stderr
from typing import Optional

from loguru import logger
from main_components.common.profile import Profile
from main_components.common.constants import Platform

from mains.commands.utils import resolve_profiles, gdrive_sync, RESOURCES_DIR
import mains.commands.pipeline as pipeline
from automation.meta_api.graph_api import GraphAPI
from automation.fanvue_client.fanvue_publisher import FanvuePublisher

app = typer.Typer(help="Run META → FANVUE end‑to‑end for profiles")


def _execute_all(
    profiles: list[Profile],
    overwrite: bool,
    use_initial_conditions: bool,
):
    for p in profiles:
        # META
        logger.info("▶️  META pipeline for '{}'", p.name)
        out_meta = p.platform_info[Platform.META].outputs_path
        if not overwrite and any(out_meta.iterdir()):
            logger.warning("Skipping META plan for '{}' (outputs exist)", p.name)
        else:
            pipeline.plan(Platform.META, [p], use_initial_conditions)
        pipeline.generate(Platform.META, [p])
        pipeline.schedule(Platform.META, [p], GraphAPI)

        # FANVUE
        logger.info("▶️  FANVUE pipeline for '{}'", p.name)
        out_fan = p.platform_info[Platform.FANVUE].outputs_path
        if not overwrite and any(out_fan.iterdir()):
            logger.warning("Skipping FANVUE plan for '{}' (outputs exist)", p.name)
        else:
            pipeline.plan(Platform.FANVUE, [p], use_initial_conditions)
        pipeline.generate(Platform.FANVUE, [p])
        pipeline.schedule(Platform.FANVUE, [p], FanvuePublisher)

    logger.success("✅ All profiles processed — background uploads in progress.")


@app.command("run_all")
def run_all(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    overwrite: bool = typer.Option(False, "-o", "--overwrite-outputs"),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
):
    """
    Run the full pipeline (META → FANVUE) at INFO level.
    """
    # Silence DEBUG, switch to INFO
    logger.remove()
    logger.add(stderr, level="INFO")

    profiles = resolve_profiles(profile_indexes, profile_names)
    if not profiles:
        logger.warning("No profiles to process.")
        return

    _execute_all(profiles, overwrite, use_initial_conditions)
    logger.info("Pushing local resources → Google Drive…")
    gdrive_sync.push(RESOURCES_DIR)


@app.command("debug")
def debug(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    overwrite: bool = typer.Option(False, "-o", "--overwrite-outputs"),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
):
    """
    Run the full pipeline with DEBUG‑level logging (baseline).
    """
    # baseline is already DEBUG—no change needed
    profiles = resolve_profiles(profile_indexes, profile_names)
    if not profiles:
        logger.warning("No profiles to process.")
        return

    _execute_all(profiles, overwrite, use_initial_conditions)
    logger.debug("Pushing local resources → Google Drive…")
    gdrive_sync.push(RESOURCES_DIR)
