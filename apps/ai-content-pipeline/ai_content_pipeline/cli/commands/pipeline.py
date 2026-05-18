from loguru import logger

from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.profiles.profile import Profile
from ai_content_pipeline.planning.planning_manager import PlanningManager
from ai_content_pipeline.generation.publications_generator import PublicationsGenerator
from ai_content_pipeline.publishing.posting_scheduler import PostingScheduler
from ai_content_pipeline.integrations.comfyui.local import ComfyLocal

from ai_content_pipeline.cli.commands.utils import RESOURCES_DIR
from ai_content_pipeline.config import settings


def plan(
    platform: Platform,
    profiles: list[Profile],
    use_initial_conditions: bool,
    refresh_model_cache: bool = False,
):
    for p in profiles:
        PlanningManager(
            template_profiles=[p],
            platform_name=platform,
            use_initial_conditions=use_initial_conditions,
            refresh_model_cache=refresh_model_cache,
        ).plan()
        logger.success("{} planning done for {}.", platform.name, p.name)


def generate(platform: Platform, profiles: list[Profile]):
    if not profiles:
        logger.warning("No profiles to generate for {}.", platform.name)
        return

    wf = RESOURCES_DIR / profiles[0].name / f"{profiles[0].name}_comfyworkflow.json"
    client = ComfyLocal(
        workflow_path=wf,
        server_host=settings.comfy_host,
        server_port=settings.comfy_port,
    )
    try:
        client.check_connection()
    except Exception as e:
        logger.error("ComfyUI server not reachable: {}", e)
        raise

    for p in profiles:
        PublicationsGenerator(
            template_profiles=[p],
            platform_name=platform,
            image_generator_tool=client,
        ).generate()
        logger.success("{} assets generated for {}.", platform.name, p.name)


async def schedule(platform: Platform, profiles: list[Profile], publisher_cls):
    await PostingScheduler(
        template_profiles=profiles,
        platform_name=platform,
        publisher=publisher_cls,
    ).upload()
    # FIXME: When called from "all" we're creating async tasks so all the schedule can run asynchronously
    #  but when called from Schedule command we're passing a list of profiles so every profile is run sequentially.
    #  We need to decide if we want to allow a list of profiles in the PostingScheduler or not.
    #  Currently we're handling the list of profiles in different levels
