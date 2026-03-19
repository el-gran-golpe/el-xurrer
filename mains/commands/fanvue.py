import time
import typer
from typing import Optional

from mains.commands.utils import resolve_profiles
import mains.commands.pipeline as pipeline
from main_components.common.types import Platform
from automation.fanvue_client.fanvue_api_publisher import FanvueAPIPublisher
from main_components.fanvue_auth import (
    start_fastapi_server,
    authenticate_profile,
)

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
    """Upload & schedule FANVUE posts via the API publisher."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.schedule(Platform.FANVUE, profiles, FanvueAPIPublisher)


@app.command()
def auth(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    """Authenticate Fanvue profiles via OAuth (opens browser)."""
    profiles = resolve_profiles(profile_indexes, profile_names)

    # 1. Start FastAPI server in background
    server_process, port = start_fastapi_server()
    time.sleep(3)  # Wait for server to be ready

    try:
        # 2. Authenticate each profile sequentially
        for profile in profiles:
            try:
                authenticate_profile(profile.name, port)
            except TimeoutError as e:
                typer.echo(f"❌ {e}", err=True)
                continue
            except Exception as e:
                typer.echo(
                    f"❌ Authentication failed for {profile.name}: {e}", err=True
                )
                continue

        typer.echo(f"\n✓ Authenticated {len(profiles)} profile(s)")

    finally:
        # 3. Stop FastAPI server
        server_process.terminate()
        server_process.wait(timeout=5)


@app.command()
def schedule_api(
    profile_indexes: list[int] = typer.Option([], "-p", "--profile-indexes"),
    profile_names: Optional[str] = typer.Option(None, "-n", "--profile-names"),
):
    """Upload & schedule FANVUE posts (OAuth API-based)."""
    profiles = resolve_profiles(profile_indexes, profile_names)
    pipeline.schedule(Platform.FANVUE, profiles, FanvueAPIPublisher)
