import threading
from loguru import logger

from main_components.common.constants import Platform
from main_components.common.profile import Profile
from main_components.planning_manager import PlanningManager
from main_components.publications_generator import PublicationsGenerator
from main_components.posting_scheduler import PostingScheduler
from generation_tools.image_generator.comfy_local import ComfyLocal

from mains.commands.utils import RESOURCES_DIR


def plan(platform: Platform, profiles: list[Profile], use_initial_conditions: bool):
    for p in profiles:
        PlanningManager(
            template_profiles=[p],
            platform_name=platform,
            use_initial_conditions=use_initial_conditions,
        ).plan()
        logger.success("{} planning done for '{}'.", platform.name, p.name)


def generate(platform: Platform, profiles: list[Profile]):
    if not profiles:
        logger.warning("No profiles to generate for {}.", platform.name)
        return

    wf = RESOURCES_DIR / profiles[0].name / f"{profiles[0].name}_comfyworkflow.json"
    client = ComfyLocal(workflow_path=wf)
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
        logger.success("{} assets generated for '{}'.", platform.name, p.name)


def schedule(platform: Platform, profiles: list[Profile], publisher_cls):
    for p in profiles:
        t = threading.Thread(
            target=lambda profile=p: PostingScheduler(
                template_profiles=[profile],
                platform_name=platform,
                publisher=publisher_cls,
            ).upload(),
            daemon=True,
        )
        t.start()
        logger.success("{} upload scheduler launched for '{}'.", platform.name, p.name)
