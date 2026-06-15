import sys
import typer
from loguru import logger

from ai_content_pipeline.cli.commands.utils import profile_manager, get_gdrive_sync
from ai_content_pipeline.cli.commands.meta import app as meta_app
from ai_content_pipeline.cli.commands.fanvue import app as fanvue_app
from ai_content_pipeline.cli.commands.all import (
    app as all_app,
    configure_run_all_logging,
)

# Baseline DEBUG for everything (only run_all command overwrites this internally)
logger.remove()
logger.add(sys.stderr, level="DEBUG")

STARTUP_PREFLIGHT_BANNER = r"""
+------------------------------------------------------------+
|        __    CLI STARTUP PREFLIGHT                         |
|       / /    Google Drive sync -> profile/config checks    |
|   ___/ /     selected command runs after this block        |
+------------------------------------------------------------+
""".strip()

STARTUP_PREFLIGHT_COMPLETE = (
    "+------------------- PREFLIGHT COMPLETE --------------------+"
)

app = typer.Typer(help="Top‑level CLI: meta, fanvue, or all")


def _print_startup_preflight_banner() -> None:
    typer.echo(f"\n{STARTUP_PREFLIGHT_BANNER}", err=True)


def _print_startup_preflight_complete() -> None:
    typer.echo(STARTUP_PREFLIGHT_COMPLETE, err=True)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """
    1) Sync resources from Google Drive
    2) Load & validate profiles
    """
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        return

    # If running the full pipeline, switch to INFO before sync/load.
    if len(sys.argv) >= 3 and sys.argv[1] == "all" and sys.argv[2] == "run_all":
        configure_run_all_logging()

    _print_startup_preflight_banner()

    try:
        get_gdrive_sync().pull(profile_manager.resource_path)
    except Exception as e:
        logger.error("Failed to sync resources from Google Drive: {}", e)
        raise typer.Exit(1)

    try:
        profile_manager.load_profiles()
    except Exception as e:
        logger.error("Failed to load profiles: {}", e)
        raise typer.Exit(1)

    _print_startup_preflight_complete()


app.add_typer(
    meta_app,
    name="meta",
    help="Instagram publishing commands with Facebook Page auth and shared staging",
)
app.add_typer(fanvue_app, name="fanvue", help="FANVUE pipeline commands")
app.add_typer(
    all_app,
    name="all",
    help="End-to-end Instagram Page-token posting and Fanvue pipelines",
)

if __name__ == "__main__":
    app()
