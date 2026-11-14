from datetime import date
from typing import Optional

import typer
from loguru import logger

from ai_content_pipeline.cli.commands.utils import (
    PROFILE_INDEXES_HELP,
    PROFILE_NAMES_HELP,
    profile_repository,
    resolve_profiles,
)
from ai_content_pipeline.llm.utils.utils import planning_week_start
from ai_content_pipeline.planning.story_manager import StoryManager

app = typer.Typer(help="Generate the season-level story arc, one command on its own")


@app.command()
def plan(
    profile_indexes: list[int] = typer.Option(
        [], "-p", "--profile-indexes", help=PROFILE_INDEXES_HELP
    ),
    profile_names: Optional[str] = typer.Option(
        None, "-n", "--profile-names", help=PROFILE_NAMES_HELP
    ),
    week: Optional[str] = typer.Option(
        None,
        "--week",
        help="ISO Monday the arc must cover. Defaults to this run's target "
        "week (today if Monday, else next Monday).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Regenerate even if an arc already covers this week.",
    ),
    refresh_model_cache: bool = typer.Option(
        False, "--refresh-model-cache", help="Refresh the cached model catalog."
    ),
):
    """Generate the arc covering a week for selected profiles, if missing."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    target_week = week or planning_week_start(date.today()).isoformat()

    for profile in profiles:
        manager = StoryManager(
            profile, profile_repository, refresh_model_cache=refresh_model_cache
        )
        arc, generated, outcome = manager.ensure_arc(target_week, force=force)
        if generated:
            logger.success(
                "Arc for {} generated: {} (+{}w), attempt {}/{}",
                profile.name,
                arc.start_week,
                arc.weeks,
                outcome.attempt if outcome else 1,
                outcome.max_attempts if outcome else 1,
            )
        else:
            logger.info(
                "Arc for {} already covers {} (starts {}, +{}w); nothing to do",
                profile.name,
                target_week,
                arc.start_week,
                arc.weeks,
            )
