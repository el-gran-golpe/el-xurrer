import sys
import typer
from loguru import logger

from mains.commands.utils import profile_manager
from mains.commands.meta import app as meta_app
from mains.commands.fanvue import app as fanvue_app
from mains.commands.all import app as all_app

# Baseline DEBUG for everything (only run_all command overwrites this internally)
logger.remove()
logger.add(sys.stderr, level="DEBUG")

app = typer.Typer(help="Top‑level CLI: meta, fanvue, or all")


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """
    1) Sync resources from Google Drive
    2) Load & validate profiles
    """
    # If running `python -m mains.main all run_all`, switch to INFO before sync/load
    if len(sys.argv) >= 3 and sys.argv[1] == "all" and sys.argv[2] == "run_all":
        logger.remove()
        logger.add(sys.stderr, level="INFO")

    try:
        # gdrive_sync.pull(profile_manager.resource_path)
        pass
    except Exception as e:
        logger.error("Failed to sync resources from Google Drive: {}", e)
        raise typer.Exit(1)

    try:
        profile_manager.load_profiles()
    except Exception as e:
        logger.error("Failed to load profiles: {}", e)
        raise typer.Exit(1)

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


app.add_typer(meta_app, name="meta", help="META pipeline commands")
app.add_typer(fanvue_app, name="fanvue", help="FANVUE pipeline commands")
app.add_typer(all_app, name="all", help="End‑to‑end pipelines (run_all/debug)")

if __name__ == "__main__":
    app()
