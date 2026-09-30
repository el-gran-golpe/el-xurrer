from loguru import logger

from ai_content_pipeline.llm.api_keys import api_keys
from ai_content_pipeline.llm.base_llm import BaseLLM
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.domain.types import Profile
from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.paths import RESOURCES_DIR
from ai_content_pipeline.profiles.repository import (
    FilesystemProfileRepository,
    ProfileRepository,
)
from ai_content_pipeline.planning.storyline_tracker import StorylineTracker


class PlanningManager:
    """Universal planning manager for generating content across different platforms."""

    def __init__(
        self,
        template_profiles: list[Profile],
        platform_name: Platform,
        use_initial_conditions: bool,
        refresh_model_cache: bool = False,
        repository: ProfileRepository | None = None,
    ):
        self.template_profiles = template_profiles
        self.platform_name = platform_name
        self.use_initial_conditions = use_initial_conditions
        self.refresh_model_cache = refresh_model_cache
        self.repository: ProfileRepository = repository or FilesystemProfileRepository(
            RESOURCES_DIR
        )

    def plan(self) -> None:
        openrouter_api_keys: list[str] = api_keys.extract_openrouter_keys()
        deepseek_api_key: str = api_keys.extract_deepseek_key()

        model_router = ModelRouter(
            free_provider_keys={"openrouter": openrouter_api_keys},
            deepseek_api_key=deepseek_api_key,
        )
        # None means scan all available models
        model_router.initialize_model_classifiers(
            models_to_scan=None,
            force_refresh=self.refresh_model_cache,
        )  # TODO: put this into the env or settings

        for profile in self.template_profiles:
            platform_profile = self.repository.get_platform_profile(
                profile, self.platform_name
            )
            llm = BaseLLM(
                prompts=platform_profile.prompts,
                previous_storyline=(
                    platform_profile.initial_conditions
                    if self.use_initial_conditions
                    else ""
                ),
                platform_name=self.platform_name,
                model_router=model_router,
            )
            plan = WeekPlan.from_planning_dict(llm.generate_dict_from_prompts())
            self.repository.save_week_plan(profile, self.platform_name, plan)
            logger.success("Planning saved for {}", profile.name)

            # Update storyline after planning generation
            StorylineTracker(
                profile, self.platform_name, llm, self.repository
            ).update_storyline(plan)
