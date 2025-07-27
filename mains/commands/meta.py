import typer
from typing import Optional, List

from mains.commands.utils import resolve_profiles
import mains.commands.pipeline as pipeline
from main_components.common.constants import Platform
from automation.meta_api.graph_api import GraphAPI

app = typer.Typer(help="META‑only pipeline commands")


@app.command()
def plan(
    profile_indexes: List[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
):
    """Create META planning JSON."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.plan(Platform.META, profiles, use_initial_conditions)


@app.command()
def generate(
    profile_indexes: List[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    """Generate META images & assets."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.generate(Platform.META, profiles)


@app.command()
def schedule(
    profile_indexes: List[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    """Upload & schedule META posts."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.schedule(Platform.META, profiles, GraphAPI)
