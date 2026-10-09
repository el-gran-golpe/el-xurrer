from dataclasses import dataclass, field
from datetime import date

from loguru import logger

from ai_content_pipeline.llm.api_keys import api_keys
from ai_content_pipeline.llm.base_llm import BaseLLM
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.llm.utils.utils import planning_week_start
from ai_content_pipeline.domain.types import Platform, PlatformProfile, Profile
from ai_content_pipeline.domain.plans import WeekPlan, summarize_week
from ai_content_pipeline.profiles.repository import ProfileRepository

# Up to this many attempts of generate -> parse -> override week key -> pin
# per profile+platform, before giving up and re-raising. Covers an LLM reply
# that is not JSON (`decode_json_from_message`), one `WeekPlan.from_planning_dict`
# rejects (pydantic's ValidationError is a ValueError), or one `pin_to_week`
# rejects for not being exactly days 1-7 each with a post. Each attempt
# re-runs the full prompt chain, since `BaseLLM`'s cache dict is per call.
# After an invalid attempt, the model that produced the last prompt's reply
# is excluded from `model_router` for the rest of this `plan()` call
# (`ModelRouter.exclude_model`), so a retry cannot land on the same model
# again — it naturally falls through to the next candidate, and eventually
# to the DeepSeek fallback. The exclusion lives only on this router instance
# (one per `plan()` call) and is never persisted to the model cache.
# The last attempt always goes to the paid fallback (DeepSeek,
# `ModelRouter.use_fallback_only`): it is the most reliable with the JSON
# structure, and a week left unplanned means a week with no content.
MAX_PLAN_ATTEMPTS = 5


@dataclass(frozen=True)
class PlanOutcome:
    """
    What `PlanningManager.plan()` actually did for one profile+platform, so
    `jobs/tasks.py:run_plan` can record it as a `job_events` row without
    `PlanningManager` ever touching `JobStore` itself (it runs inside
    `asyncio.to_thread`, and `JobStore`/sqlite3 is not thread-safe).
    """

    profile: str
    week: str
    attempt: int
    max_attempts: int
    model: str | None
    used_fallback: bool
    pinned_corrections: int
    invalid_attempts: list[str] = field(default_factory=list)


class PlanningFailedError(ValueError):
    """
    Raised instead of the last attempt's bare error when every attempt in
    `_generate_valid_plan` was invalid. Subclasses `ValueError` so existing
    callers that catch `ValueError` (retry logic in `jobs/tasks.py`, tests
    asserting on `pytest.raises(ValueError, match=...)`) keep working
    unchanged; `invalid_attempts` additionally carries every attempt's error
    message so `run_plan` can record a `plan_failed` event with full detail.
    """

    def __init__(self, message: str, invalid_attempts: list[str]):
        super().__init__(message)
        self.invalid_attempts = invalid_attempts


def build_previous_storyline(
    repository: ProfileRepository,
    profile: Profile,
    platform: Platform,
    platform_profile: PlatformProfile,
    use_initial_conditions: bool,
    target_week: str,
) -> str:
    """
    What the prompt gets as `previous_storyline`: who she is (shared by both
    platforms), this platform's own static notes, and a deterministic recap
    of this platform's own previous week, if one exists. Platform-own only —
    Meta reads Meta's previous week, Fanvue reads Fanvue's; cross-platform
    continuity is the future "chapter" command's job.

    Exposed as a function rather than a `PlanningManager` method so
    `jobs/tasks.py:run_plan` can build exactly this same text to compute the
    resume hash without constructing a `PlanningManager` (and therefore
    without touching the model router).
    """
    sections = [("Who she is", repository.get_persona(profile))]
    if use_initial_conditions:
        sections.append(("Platform notes", platform_profile.initial_conditions))

    previous_plan = repository.get_previous_week_plan(
        profile, platform, before=target_week
    )
    if previous_plan is not None:
        sections.append(
            (f"Last week ({previous_plan.week})", summarize_week(previous_plan))
        )

    return "\n\n".join(f"## {title}\n{body}" for title, body in sections if body)


class PlanningManager:
    """Universal planning manager for generating content across different platforms."""

    def __init__(
        self,
        template_profiles: list[Profile],
        platform_name: Platform,
        use_initial_conditions: bool,
        repository: ProfileRepository,
        refresh_model_cache: bool = False,
        target_week: date | None = None,
    ):
        self.template_profiles = template_profiles
        self.platform_name = platform_name
        self.use_initial_conditions = use_initial_conditions
        self.refresh_model_cache = refresh_model_cache
        self.repository: ProfileRepository = repository
        # Deterministic: today if today is Monday, else the next Monday.
        # Never "the Monday after the latest planned week" — that would plan
        # a new week on every re-run and break resume. Callers that need the
        # same week across several jobs in one run (`jobs run`) compute it
        # once themselves and pass it in instead of relying on this default.
        self.target_week = target_week or planning_week_start(date.today())

    def plan(self) -> list[PlanOutcome]:
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

        week_key = self.target_week.isoformat()
        outcomes: list[PlanOutcome] = []
        for profile in self.template_profiles:
            platform_profile = self.repository.get_platform_profile(
                profile, self.platform_name
            )
            previous_storyline = build_previous_storyline(
                self.repository,
                profile,
                self.platform_name,
                platform_profile,
                self.use_initial_conditions,
                week_key,
            )
            logger.info(
                "Target week for {} {}: {}",
                profile.name,
                self.platform_name.value,
                week_key,
            )
            logger.info(
                "Previous storyline for {} {}:\n{}",
                profile.name,
                self.platform_name.value,
                previous_storyline,
            )
            llm = BaseLLM(
                prompts=platform_profile.prompts,
                previous_storyline=previous_storyline,
                platform_name=self.platform_name,
                model_router=model_router,
                week_start=self.target_week,
            )
            plan, outcome = self._generate_valid_plan(llm, profile, week_key)
            self.repository.save_week_plan(profile, self.platform_name, plan)
            logger.success("Planning saved for {}", profile.name)
            outcomes.append(outcome)
        return outcomes

    def _generate_valid_plan(
        self, llm: BaseLLM, profile: Profile, week_key: str
    ) -> tuple[WeekPlan, PlanOutcome]:
        """
        Retries generate -> parse -> override week key -> pin up to
        `MAX_PLAN_ATTEMPTS` times. Catches only `ValueError` (which also
        covers `json.JSONDecodeError` and pydantic's `ValidationError`) so an
        unrelated bug still propagates immediately. Nothing is saved until an
        attempt succeeds; the caller only sees the final, valid plan (plus a
        `PlanOutcome` describing how it got there) or a `PlanningFailedError`
        carrying every attempt's error.
        """
        last_error: ValueError | None = None
        invalid_attempts: list[str] = []
        used_fallback = False
        for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
            if attempt == MAX_PLAN_ATTEMPTS and attempt > 1:
                llm.model_router.use_fallback_only()
                used_fallback = True
                logger.warning(
                    "Last plan attempt for {} {} week {}: using the paid fallback only",
                    profile.name,
                    self.platform_name.value,
                    week_key,
                )
            try:
                plan = WeekPlan.from_planning_dict(llm.generate_dict_from_prompts())
                # The prompt JSONs under resources*/ still say "week_1"; the
                # target week we asked for is authoritative, not whatever key
                # the model replied with.
                plan.week = week_key
                corrections = plan.pin_to_week(self.target_week)
                for correction in corrections:
                    logger.warning(
                        "Pinned {} {} upload_time to its day: {}",
                        profile.name,
                        self.platform_name.value,
                        correction,
                    )
                last_model = llm.model_router.last_model
                model_label = f"{last_model[0]}/{last_model[1]}" if last_model else None
                outcome = PlanOutcome(
                    profile=profile.name,
                    week=week_key,
                    attempt=attempt,
                    max_attempts=MAX_PLAN_ATTEMPTS,
                    model=model_label,
                    used_fallback=used_fallback,
                    pinned_corrections=len(corrections),
                    invalid_attempts=list(invalid_attempts),
                )
                return plan, outcome
            except ValueError as e:
                last_error = e
                invalid_attempts.append(str(e))
                last_model = llm.model_router.last_model
                if last_model is not None:
                    provider_id, identifier = last_model
                    llm.model_router.exclude_model(provider_id, identifier)
                    logger.warning(
                        "Excluding model {} ({}) for the remaining attempts "
                        "after an invalid plan",
                        identifier,
                        provider_id,
                    )
                logger.warning(
                    "Plan attempt {}/{} for {} {} week {} was invalid: {}; retrying",
                    attempt,
                    MAX_PLAN_ATTEMPTS,
                    profile.name,
                    self.platform_name.value,
                    week_key,
                    e,
                )
        assert last_error is not None  # the loop always sets it before falling through
        raise PlanningFailedError(str(last_error), invalid_attempts)
