import asyncio

import typer
from typing import Optional

from ai_content_pipeline.cli.commands.utils import (
    PROFILE_INDEXES_HELP,
    PROFILE_NAMES_HELP,
    resolve_profiles,
)
from ai_content_pipeline.integrations.meta.graph_api import MetaPublisher
import ai_content_pipeline.cli.commands.pipeline as pipeline
from ai_content_pipeline.domain.types import Platform

app = typer.Typer(
    help="Instagram publishing commands with Facebook Page auth and shared media staging"
)


@app.command()
def plan(
    profile_indexes: list[int] = typer.Option(
        [], "-p", "--profile-indexes", help=PROFILE_INDEXES_HELP
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help=PROFILE_NAMES_HELP
    ),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
    refresh_model_cache: bool = typer.Option(
        False, "--refresh-model-cache", help="Refresh the cached GitHub Models catalog."
    ),
):
    """Create Instagram planning JSON for the Facebook Page token publishing flow."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.plan(
        Platform.META,
        profiles,
        use_initial_conditions,
        refresh_model_cache=refresh_model_cache,
    )


@app.command()
def generate(
    profile_indexes: list[int] = typer.Option(
        [], "-p", "--profile-indexes", help=PROFILE_INDEXES_HELP
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help=PROFILE_NAMES_HELP
    ),
):
    """Generate Instagram assets for the Facebook Page token publishing flow."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.generate(Platform.META, profiles)


@app.command()
def schedule(
    profile_indexes: list[int] = typer.Option(
        [], "-p", "--profile-indexes", help=PROFILE_INDEXES_HELP
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help=PROFILE_NAMES_HELP
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help=(
            "Skip days whose upload time has already passed; continue from "
            "today's post if still ahead, otherwise tomorrow's."
        ),
    ),
):
    """Stage media on Facebook CDN and publish Instagram posts via Page tokens."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    asyncio.run(
        pipeline.schedule(Platform.META, profiles, MetaPublisher, resume=resume)
    )
