from loguru import logger

from ai_content_pipeline.llm.api_keys import api_keys
from ai_content_pipeline.llm.base_llm import BaseLLM
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.domain.types import Profile
from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.profiles.repository import ProfileRepository


class PlanningManager:
    """Universal planning manager for generating content across different platforms."""

    def __init__(
        self,
        template_profiles: list[Profile],
        platform_name: Platform,
        use_initial_conditions: bool,
        repository: ProfileRepository,
        refresh_model_cache: bool = False,
    ):
        self.template_profiles = template_profiles
        self.platform_name = platform_name
        self.use_initial_conditions = use_initial_conditions
        self.refresh_model_cache = refresh_model_cache
        self.repository: ProfileRepository = repository

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
                previous_storyline=self._build_storyline(profile, platform_profile),
                platform_name=self.platform_name,
                model_router=model_router,
            )
            plan = WeekPlan.from_planning_dict(llm.generate_dict_from_prompts())
            self.repository.save_week_plan(profile, self.platform_name, plan)
            logger.success("Planning saved for {}", profile.name)

    def _build_storyline(self, profile: Profile, platform_profile) -> str:
        """
        What the prompt gets as `previous_storyline`: who she is, shared by
        both platforms, plus the platform's own notes. Narrative state (where
        the story is now) is not here on purpose — that is the chapter's job,
        and the chapter does not exist yet.
        """
        sections = [("Who she is", self.repository.get_persona(profile))]
        if self.use_initial_conditions:
            sections.append(("Platform notes", platform_profile.initial_conditions))
        return "\n\n".join(f"## {title}\n{body}" for title, body in sections if body)
