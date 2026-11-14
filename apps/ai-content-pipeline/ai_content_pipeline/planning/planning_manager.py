from dataclasses import dataclass, field
from datetime import date

from loguru import logger

from ai_content_pipeline.llm.api_keys import api_keys
from ai_content_pipeline.llm.base_llm import BaseLLM
from ai_content_pipeline.llm.retry import GenerationFailedError, generate_with_retries
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.llm.utils.utils import planning_week_start
from ai_content_pipeline.domain.types import Platform, PlatformProfile, Profile
from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.planning.story_manager import StoryManager
from ai_content_pipeline.profiles.repository import ProfileRepository

# Up to this many attempts of generate -> parse -> override week key -> pin
# per profile+platform, before giving up and re-raising. Covers an LLM reply
# that is not JSON (`decode_json_from_message`), one `WeekPlan.from_planning_dict`
# rejects (pydantic's ValidationError is a ValueError), or one `pin_to_week`
# rejects for not being exactly days 1-7 each with a post. Each attempt
# re-runs the full prompt chain, since `BaseLLM`'s cache dict is per call.
# The retry policy itself (model exclusion, last-attempt-on-fallback) lives
# in `llm/retry.py:generate_with_retries`, shared with `StoryManager`'s arc
# and chapter generation.
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
    platforms), this platform's own static notes, and this platform's slice
    of the chapter covering `target_week` — the date, the neutral
    `situation`, and ONLY this platform's own `angle`, for each of the 7
    days. This is the isolation boundary: a Meta call never sees the arc
    text, the Fanvue angle, or Fanvue's notes, because nothing here ever
    reads them. Cross-platform continuity lives entirely in the chapter
    (`planning/story_manager.py`), which both platforms' plans read from
    independently.

    Raises `ValueError` (not caught here) when no chapter covers
    `target_week`: in the DAG, the "story" step guarantees one exists before
    any `plan` job for that week is enqueued, so this should never happen
    there; it is a clear signal when `plan`/`arc plan`/`chapter plan` are run
    out of order by hand.

    Exposed as a function rather than a `PlanningManager` method so
    `jobs/tasks.py:run_plan` can build exactly this same text to compute the
    resume hash without constructing a `PlanningManager` (and therefore
    without touching the model router).
    """
    sections = [("Who she is", repository.get_persona(profile))]
    if use_initial_conditions:
        sections.append(("Platform notes", platform_profile.initial_conditions))

    chapter = repository.get_chapter_covering(profile, target_week)
    if chapter is None:
        raise ValueError(
            f"No chapter covers week {target_week} for {profile.name} "
            f"{platform.value}; generate one first (`jobs run` or `chapter plan`)."
        )
    # The situation is what happens; the angle is only a direction for how
    # this platform lives it. Labelled so the model does not copy the angle
    # as the post or let it override the situation.
    week_lines = [
        f"- {day.date}: Situation: {day.situation} | "
        f"Angle (direction only): {day.angles[platform.value]}"
        for day in chapter.week_slice(target_week)
    ]
    sections.append(("This week", "\n".join(week_lines)))

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
            self._ensure_story(profile, week_key)
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

    def _ensure_story(self, profile: Profile, week_key: str) -> None:
        """
        `build_previous_storyline` requires a chapter covering `week_key`.
        In `jobs run`, the "story" DAG node already guarantees one exists
        before any `plan` job is enqueued for that week, so this is a cheap
        no-op there: `StoryManager.ensure_arc`/`ensure_chapter` check the
        repository first (`get_arc_covering`/`get_chapter_covering`) and
        only build a `ModelRouter`/call the LLM when something is actually
        missing. Standalone callers with no DAG in front of them (`meta
        plan`, `fanvue plan`, `all run_all`/`pipeline.py`) have no such
        guarantee, so `plan()` must ensure it itself here or those commands
        would simply break now that `plan` depends on a chapter.

        Never touches `JobStore`: `PlanningManager.plan()` runs inside
        `asyncio.to_thread` in the DAG (see `jobs/tasks.py:run_plan`), and
        `JobStore`'s sqlite3 connection is not thread-safe.
        """
        story_manager = StoryManager(
            profile, self.repository, refresh_model_cache=self.refresh_model_cache
        )
        arc, _, _ = story_manager.ensure_arc(week_key)
        story_manager.ensure_chapter(arc, week_key)

    def _generate_valid_plan(
        self, llm: BaseLLM, profile: Profile, week_key: str
    ) -> tuple[WeekPlan, PlanOutcome]:
        """
        Retries generate -> parse -> override week key -> pin up to
        `MAX_PLAN_ATTEMPTS` times, via the shared `generate_with_retries`
        helper (same policy `StoryManager` uses for arc/chapter generation).
        Nothing is saved until an attempt succeeds; the caller only sees the
        final, valid plan (plus a `PlanOutcome` describing how it got there)
        or a `PlanningFailedError` carrying every attempt's error.
        """
        pinned_corrections: list[str] = []

        def parse(reply: dict) -> WeekPlan:
            plan = WeekPlan.from_planning_dict(reply)
            # The prompt JSONs under resources*/ still say "week_1"; the
            # target week we asked for is authoritative, not whatever key
            # the model replied with.
            plan.week = week_key
            corrections = plan.pin_to_week(self.target_week)
            pinned_corrections[:] = corrections
            for correction in corrections:
                logger.warning(
                    "Pinned {} {} upload_time to its day: {}",
                    profile.name,
                    self.platform_name.value,
                    correction,
                )
            return plan

        try:
            retried = generate_with_retries(
                llm,
                parse,
                max_attempts=MAX_PLAN_ATTEMPTS,
                context=(
                    f"plan for {profile.name} {self.platform_name.value} "
                    f"week {week_key}"
                ),
            )
        except GenerationFailedError as e:
            raise PlanningFailedError(str(e), e.invalid_attempts) from e

        outcome = PlanOutcome(
            profile=profile.name,
            week=week_key,
            attempt=retried.attempt,
            max_attempts=retried.max_attempts,
            model=retried.model,
            used_fallback=retried.used_fallback,
            pinned_corrections=len(pinned_corrections),
            invalid_attempts=retried.invalid_attempts,
        )
        return retried.value, outcome
