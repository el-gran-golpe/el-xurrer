import typer
from typing import Optional

from mains.commands.utils import resolve_profiles
import mains.commands.pipeline as pipeline
from main_components.common.constants import Platform
from automation.fanvue_client.fanvue_publisher import FanvuePublisher

app = typer.Typer(help="FANVUE‑only pipeline commands")


@app.command()
def plan(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
    use_initial_conditions: bool = typer.Option(
        True, "--use-initial-conditions/--no-initial-conditions"
    ),
):
    """Create FANVUE planning JSON."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.plan(Platform.FANVUE, profiles, use_initial_conditions)


@app.command()
def generate(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    """Generate FANVUE images & assets."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.generate(Platform.FANVUE, profiles)


@app.command()
def schedule(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    """Upload & schedule FANVUE posts."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.schedule(Platform.FANVUE, profiles, FanvuePublisher)
