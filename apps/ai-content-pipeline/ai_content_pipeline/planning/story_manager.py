"""
Generates the arc and chapter levels of the story (see
`docs/weekly-planning-continuity-plan.md` section 5 and `domain/story.py`).

Mirrors `PlanningManager`'s shape deliberately: one `ModelRouter` per
generation call, the same `generate_with_retries` policy (model exclusion,
last-attempt-on-fallback), and the same "nothing is saved until every part
succeeds" guarantee. The two things that differ from `plan`:

- Both the arc and the chapter are generated with `is_sensitive_content=True`
  — neither is read directly by Meta, so neither needs a censored-model-safe
  prompt. (The chapter prompt still *asks* for Meta-safe `situation`/`meta`
  text, enforced by instruction only, same as any other content-safety rule
  that lives in the prompt rather than in code.)
- `ensure_arc`/`ensure_chapter` never regenerate a file that already exists:
  arcs and chapters are meant to be hand-edited, so "it's on disk" always
  wins over "the inputs changed", unlike `plan`'s hash-based resume.

Chapter generation is split into several LLM calls, not one: a real run
asked a model for a whole 4-week (28-day) chapter in a single reply and got
7 days back. `plan_chapter` now does an outline call (title/summary/one
short summary per week — `ChapterOutline`) followed by one call per week
(exactly that week's 7 `ChapterDay`s — `ChapterWeekDays`), each with its own
`generate_with_retries` budget and all sharing one `ModelRouter` so model
exclusions still carry over between them. The days already generated for
this chapter's earlier weeks are fed into each later week's call for
continuity, alongside the outline. The full `Chapter` is only assembled and
validated (and only then saved by `ensure_chapter`) once the outline and
every week succeeded — a failure partway through leaves nothing on disk,
same as a single-call failure used to.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from loguru import logger

from ai_content_pipeline.domain.story import (
    DAYS_PER_WEEK,
    Arc,
    Chapter,
    ChapterDay,
    ChapterOutline,
    ChapterWeekDays,
    RegeneratedAngles,
    chapter_boundaries_for_week,
    determine_new_arc_start,
)
from ai_content_pipeline.domain.types import Platform, Profile
from ai_content_pipeline.llm.api_keys import api_keys
from ai_content_pipeline.llm.base_llm import BaseLLM
from ai_content_pipeline.llm.retry import (
    GenerationFailedError,
    RetryOutcome,
    generate_with_retries,
)
from ai_content_pipeline.llm.routing.model_router import ModelRouter
from ai_content_pipeline.domain.types import PromptItem
from ai_content_pipeline.profiles.repository import ProfileRepository

MAX_ARC_ATTEMPTS = 5
MAX_CHAPTER_ATTEMPTS = 5

# BaseLLM's constructor asks for a Platform, but arc/chapter generation is
# platform-blind (the arc entirely, the chapter by design covers every
# platform in one call) — it only matters for `PromptItem.is_sensitive_content`
# capability filtering, which we already set directly below. Any value works;
# META is just a harmless placeholder.
_UNUSED_PLATFORM_FOR_ROUTING = Platform.META


class StoryGenerationFailedError(ValueError):
    """Same shape as `PlanningFailedError`: every attempt was invalid."""

    def __init__(self, message: str, invalid_attempts: list[str]):
        super().__init__(message)
        self.invalid_attempts = invalid_attempts


@dataclass(frozen=True)
class ArcOutcome:
    profile: str
    start_week: str
    attempt: int
    max_attempts: int
    model: str | None
    used_fallback: bool
    invalid_attempts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChapterOutcome:
    profile: str
    start_week: str
    attempt: int
    max_attempts: int
    model: str | None
    used_fallback: bool
    invalid_attempts: list[str] = field(default_factory=list)


def _build_router(refresh_model_cache: bool) -> ModelRouter:
    router = ModelRouter(
        free_provider_keys={"openrouter": api_keys.extract_openrouter_keys()},
        deepseek_api_key=api_keys.extract_deepseek_key(),
    )
    router.initialize_model_classifiers(
        models_to_scan=None, force_refresh=refresh_model_cache
    )
    return router


def _build_arc_context(
    repository: ProfileRepository, profile: Profile, before: str
) -> str:
    """Persona + every platform's own notes + the previous arc's summary
    (plus its chapters' summaries, if any) — the arc is free, so it is the
    only generation step allowed to read every platform's notes at once."""
    sections = [("Who she is", repository.get_persona(profile))]
    for platform in Platform:
        notes = repository.get_platform_profile(profile, platform).initial_conditions
        sections.append((f"{platform.value.capitalize()} notes", notes))

    previous_arc = repository.get_previous_arc(profile, before=before)
    if previous_arc is not None:
        sections.append(
            (f"Previous arc ({previous_arc.start_week})", previous_arc.summary)
        )
        chapter_summaries = [
            f"- {c.start_week}: {c.summary}"
            for c in repository.get_chapters_of_arc(profile, previous_arc.start_week)
        ]
        if chapter_summaries:
            sections.append(("Previous arc's chapters", "\n".join(chapter_summaries)))

    return "\n\n".join(f"## {title}\n{body}" for title, body in sections if body)


def _build_chapter_context(
    repository: ProfileRepository, profile: Profile, arc: Arc, before: str
) -> str:
    """Arc + persona + every platform's notes + the previous chapters of the
    same arc (summary + last week's situations, for continuity)."""
    sections = [
        ("Who she is", repository.get_persona(profile)),
        (
            f"Arc ({arc.start_week} - {arc.end_week}): {arc.title}",
            f"Premise: {arc.premise}\nGoal: {arc.goal}\nConflict: {arc.conflict}\n"
            f"Starting point: {arc.starting_point}\nEnding point: {arc.ending_point}",
        ),
    ]
    for platform in Platform:
        notes = repository.get_platform_profile(profile, platform).initial_conditions
        sections.append((f"{platform.value.capitalize()} notes", notes))

    previous_chapters = [
        c
        for c in repository.get_chapters_of_arc(profile, arc.start_week)
        if c.start_week < before
    ]
    if previous_chapters:
        lines = []
        for chapter in previous_chapters:
            lines.append(f"- {chapter.start_week}: {chapter.summary}")
            last_week = chapter.days[-7:]
            for day in last_week:
                lines.append(f"  - {day.date}: {day.situation}")
        sections.append(("Previous chapters of this arc", "\n".join(lines)))

    return "\n\n".join(f"## {title}\n{body}" for title, body in sections if body)


def _build_chapter_week_storyline(
    base_context: str,
    outline: ChapterOutline,
    week_index: int,
    generated_days: list[ChapterDay],
) -> str:
    """
    `base_context` (`_build_chapter_context`'s arc + persona + every
    platform's notes + the previous chapters of this arc) plus this
    chapter's own outline, and — once week 0's call has produced days —
    the days already written for this chapter's earlier weeks, so a later
    week's call continues them rather than repeating or contradicting them.
    """
    sections = [
        (
            f"This chapter's outline: {outline.title}",
            f"Summary: {outline.summary}\nThis week's outline: "
            f"{outline.week_summaries[week_index]}",
        )
    ]
    if generated_days:
        lines = [
            f"- {day.date}: {day.situation} — meta: {day.angles['meta']} — "
            f"fanvue: {day.angles['fanvue']}"
            for day in generated_days
        ]
        sections.append(
            ("Earlier days already written in this chapter", "\n".join(lines))
        )
    extra = "\n\n".join(f"## {title}\n{body}" for title, body in sections if body)
    return f"{base_context}\n\n{extra}" if extra else base_context


_ARC_SYSTEM_PROMPT = """\
You are a professional showrunner, writing the season-long story arc for a
social media influencer persona. This arc starts {day}. It is never shown to
any platform or audience directly — it is the private outline later chapters
and posts are drawn from, so it may include mature or adult themes freely.
Reply with a single JSON object with exactly these string fields: "title",
"premise", "goal", "conflict", "starting_point", "ending_point", "summary".
No markdown, no extra fields, no commentary outside the JSON object."""

_ARC_USER_PROMPT = """\
Here is everything known about this persona and her previous arc, if any:

{previous_storyline}

Write the next season-long arc: what she wants, what stands in her way,
where she starts, and where she ends up by the arc's last week. Keep it
consistent with her persona and, if a previous arc exists, continue from it
rather than repeating it."""


def _arc_prompts() -> list[PromptItem]:
    return [
        PromptItem(
            prompt=_ARC_USER_PROMPT,
            cache_key="arc",
            system_prompt=_ARC_SYSTEM_PROMPT,
            output_as_json=True,
            is_sensitive_content=True,
        )
    ]


# ---------------- chapter: outline, then one call per week ----------------
#
# A real run asked one model for a whole 4-week (28-day) chapter in a single
# reply and got 7 days back ("Expected 28 days ... got 7"). Splitting into a
# small outline call plus one call per week keeps every single reply to a
# size a model can reliably produce in full.


def _chapter_outline_system_prompt(weeks: int) -> str:
    return (
        "You are a professional showrunner planning the outline for one "
        f"chapter of a story arc, covering {weeks} week(s) starting "
        "{day}, for a social media influencer persona. This outline is "
        "never shown to any platform directly — it is the private plan "
        "the day-by-day beats for each week are later drawn from, so it "
        "may include mature or adult themes freely. Reply with a single "
        'JSON object with exactly these fields: "title" (string), '
        '"summary" (string), and "week_summaries": a list of exactly '
        f"{weeks} short string(s), one per week of the chapter in order, "
        "each a 1-2 sentence outline of what happens that week. No "
        "markdown, no extra fields, no commentary outside the JSON "
        "object."
    )


_CHAPTER_OUTLINE_USER_PROMPT = """\
Here is the arc this chapter belongs to, this persona's notes for every
platform, and the previous chapters of this same arc, if any:

{previous_storyline}

Write this chapter's outline: a title, an overall summary, and one short
summary per week describing what happens that week, continuing the arc
and, if previous chapters exist, continuing their story rather than
repeating it."""


# What an angle is, shared by the chapter week prompt and the angle refresh
# prompt. Angles used to come back as finished first-person captions, which
# `plan` then copied verbatim even when they contradicted the situation.
_ANGLE_GUIDANCE = (
    "An angle is a direction for the writer of that platform's posts, not "
    "a post: one or two sentences in the third person saying how that "
    "platform's audience lives the day's situation (focus, tone, what is "
    "shown). It must happen inside the situation, never contradict it or "
    "add events of its own. No first person, no hashtags, no ready-to-post "
    "caption text."
)


def _chapter_week_system_prompt(week_index: int, weeks_total: int) -> str:
    return (
        "You are a professional showrunner, writing week "
        f"{week_index + 1} of {weeks_total} of one chapter of a story "
        "arc, as daily beats for a social media influencer persona. This "
        'week starts {day}. Every day needs a neutral "situation" (what '
        "happens, described so it is safe to read on any platform, "
        'including Instagram) and one "angle" per platform describing '
        "how that platform's audience experiences that same day. "
        f"{_ANGLE_GUIDANCE} The "
        '"meta" angle must stay safe for work (Instagram reads it '
        'directly); the "fanvue" angle may be adult/explicit. Reply with '
        'a single JSON object with exactly one field, "days": a list '
        "with exactly 7 entries, one per day of this week in order, each "
        'with "date" (ISO YYYY-MM-DD), "situation" (string), and '
        '"angles" (an object with exactly the keys "meta" and "fanvue", '
        "each a string). No markdown, no extra fields, no commentary "
        "outside the JSON object."
    )


_CHAPTER_WEEK_USER_PROMPT = """\
Here is everything relevant to this one week of the chapter: the arc,
this persona's notes for every platform, this chapter's outline, the
previous chapters of this same arc (if any), and the days already
written for the earlier weeks of this same chapter (if any):

{previous_storyline}

Write exactly this week's 7 days in order, continuing the chapter's
outline and, if earlier weeks of this chapter already have days,
continuing their story rather than repeating it."""


_ANGLES_REFRESH_SYSTEM_PROMPT = (
    "You are a professional showrunner. Some days of a story chapter for a "
    "social media influencer persona had their situation rewritten by "
    "hand, so their platform angles no longer match. The chapter's week "
    "starts {day}. Rewrite the angles of exactly the days you are asked "
    "for, from their new situation. "
    f"{_ANGLE_GUIDANCE} "
    'The "meta" angle must stay safe for work (Instagram reads it '
    'directly); the "fanvue" angle may be adult/explicit. Reply with a '
    'single JSON object with exactly one field, "days": a list with one '
    'entry per requested day, each with "date" (ISO YYYY-MM-DD) and '
    '"angles" (an object with exactly the keys "meta" and "fanvue", each '
    "a string). No markdown, no extra fields, no commentary outside the "
    "JSON object."
)

_ANGLES_REFRESH_USER_PROMPT = """\
Here is the persona, every platform's notes, the arc, this chapter's days
(situation and current angles), and the days whose angles must be
rewritten:

{previous_storyline}

Rewrite the angles of exactly the requested days so they follow each
day's new situation, keeping the voice and continuity of the days around
them."""


def _angles_refresh_prompts() -> list[PromptItem]:
    return [
        PromptItem(
            prompt=_ANGLES_REFRESH_USER_PROMPT,
            cache_key="chapter_angles_refresh",
            system_prompt=_ANGLES_REFRESH_SYSTEM_PROMPT,
            output_as_json=True,
            is_sensitive_content=True,
        )
    ]


def _chapter_outline_prompts(weeks: int) -> list[PromptItem]:
    return [
        PromptItem(
            prompt=_CHAPTER_OUTLINE_USER_PROMPT,
            cache_key="chapter_outline",
            system_prompt=_chapter_outline_system_prompt(weeks),
            output_as_json=True,
            is_sensitive_content=True,
        )
    ]


def _chapter_week_prompts(week_index: int, weeks_total: int) -> list[PromptItem]:
    return [
        PromptItem(
            prompt=_CHAPTER_WEEK_USER_PROMPT,
            # Unique per week so a caller/test can tell which week a given
            # `BaseLLM`/cache entry belongs to.
            cache_key=f"chapter_week_{week_index}",
            system_prompt=_chapter_week_system_prompt(week_index, weeks_total),
            output_as_json=True,
            is_sensitive_content=True,
        )
    ]


class StoryManager:
    """Generates and persists the arc/chapter levels for one profile."""

    def __init__(
        self,
        profile: Profile,
        repository: ProfileRepository,
        refresh_model_cache: bool = False,
    ):
        self.profile = profile
        self.repository = repository
        self.refresh_model_cache = refresh_model_cache

    # ---------------- generation ----------------

    def plan_arc(self, start_week: str, weeks: int) -> tuple[Arc, ArcOutcome]:
        router = _build_router(self.refresh_model_cache)
        storyline = _build_arc_context(self.repository, self.profile, start_week)
        llm = BaseLLM(
            prompts=_arc_prompts(),
            previous_storyline=storyline,
            platform_name=_UNUSED_PLATFORM_FOR_ROUTING,
            model_router=router,
            week_start=date.fromisoformat(start_week),
        )

        def parse(reply: dict) -> Arc:
            return Arc.model_validate(
                {**reply, "start_week": start_week, "weeks": weeks}
            )

        try:
            retried = generate_with_retries(
                llm,
                parse,
                max_attempts=MAX_ARC_ATTEMPTS,
                context=f"arc for {self.profile.name} starting {start_week}",
            )
        except GenerationFailedError as e:
            raise StoryGenerationFailedError(str(e), e.invalid_attempts) from e

        outcome = ArcOutcome(
            profile=self.profile.name,
            start_week=start_week,
            attempt=retried.attempt,
            max_attempts=retried.max_attempts,
            model=retried.model,
            used_fallback=retried.used_fallback,
            invalid_attempts=retried.invalid_attempts,
        )
        return retried.value, outcome

    def plan_chapter(
        self, arc: Arc, start_week: str, weeks: int
    ) -> tuple[Chapter, ChapterOutcome]:
        """
        Generates the chapter's outline, then exactly `weeks` week calls in
        order (each exactly that week's 7 `ChapterDay`s), all sharing one
        `ModelRouter` so model exclusions from an earlier call still apply
        to a later one. Every call has its own `generate_with_retries`
        budget; a `GenerationFailedError` from any of them — the outline or
        any week — aborts the whole chapter before anything is assembled or
        returned, so `ensure_chapter` never saves a partial chapter.

        `ChapterOutcome` aggregates the per-call `RetryOutcome`s: `attempt`
        is the worst (highest) attempt number needed by any call, `model`
        and `invalid_attempts` reflect the latest/every call respectively,
        and `used_fallback` is true if any call needed the paid fallback.
        """
        router = _build_router(self.refresh_model_cache)
        context = _build_chapter_context(self.repository, self.profile, arc, start_week)

        try:
            outline_retried = self._plan_chapter_outline(
                router, context, start_week, weeks
            )
            outline = outline_retried.value

            all_days: list[ChapterDay] = []
            invalid_attempts = list(outline_retried.invalid_attempts)
            max_attempt = outline_retried.attempt
            used_fallback = outline_retried.used_fallback
            model = outline_retried.model

            start = date.fromisoformat(start_week)
            for week_index in range(weeks):
                week_start = (start + timedelta(weeks=week_index)).isoformat()
                week_retried = self._plan_chapter_week(
                    router, context, outline, all_days, week_index, weeks, week_start
                )
                all_days.extend(week_retried.value)
                invalid_attempts.extend(week_retried.invalid_attempts)
                max_attempt = max(max_attempt, week_retried.attempt)
                used_fallback = used_fallback or week_retried.used_fallback
                model = week_retried.model
                logger.info(
                    "Chapter for {} {}: week {}/{} generated",
                    self.profile.name,
                    start_week,
                    week_index + 1,
                    weeks,
                )
        except GenerationFailedError as e:
            raise StoryGenerationFailedError(str(e), e.invalid_attempts) from e

        chapter = Chapter.model_validate(
            {
                "arc_start_week": arc.start_week,
                "start_week": start_week,
                "weeks": weeks,
                "title": outline.title,
                "summary": outline.summary,
                "days": [day.stamped() for day in all_days],
            }
        )

        outcome = ChapterOutcome(
            profile=self.profile.name,
            start_week=start_week,
            attempt=max_attempt,
            max_attempts=MAX_CHAPTER_ATTEMPTS,
            model=model,
            used_fallback=used_fallback,
            invalid_attempts=invalid_attempts,
        )
        return chapter, outcome

    def _plan_chapter_outline(
        self, router: ModelRouter, context: str, start_week: str, weeks: int
    ) -> RetryOutcome[ChapterOutline]:
        llm = BaseLLM(
            prompts=_chapter_outline_prompts(weeks),
            previous_storyline=context,
            platform_name=_UNUSED_PLATFORM_FOR_ROUTING,
            model_router=router,
            week_start=date.fromisoformat(start_week),
        )

        def parse(reply: dict) -> ChapterOutline:
            outline = ChapterOutline.model_validate(reply)
            if len(outline.week_summaries) != weeks:
                raise ValueError(
                    f"Expected {weeks} week summaries, got "
                    f"{len(outline.week_summaries)}"
                )
            return outline

        return generate_with_retries(
            llm,
            parse,
            max_attempts=MAX_CHAPTER_ATTEMPTS,
            context=f"chapter outline for {self.profile.name} starting {start_week}",
        )

    def _plan_chapter_week(
        self,
        router: ModelRouter,
        context: str,
        outline: ChapterOutline,
        generated_days: list[ChapterDay],
        week_index: int,
        weeks_total: int,
        week_start: str,
    ) -> RetryOutcome[list[ChapterDay]]:
        storyline = _build_chapter_week_storyline(
            context, outline, week_index, generated_days
        )
        llm = BaseLLM(
            prompts=_chapter_week_prompts(week_index, weeks_total),
            previous_storyline=storyline,
            platform_name=_UNUSED_PLATFORM_FOR_ROUTING,
            model_router=router,
            week_start=date.fromisoformat(week_start),
        )

        def parse(reply: dict) -> list[ChapterDay]:
            week_days = ChapterWeekDays.model_validate(reply)
            start = date.fromisoformat(week_start)
            expected_dates = [
                (start + timedelta(days=i)).isoformat() for i in range(DAYS_PER_WEEK)
            ]
            actual_dates = [day.date for day in week_days.days]
            if actual_dates != expected_dates:
                raise ValueError(
                    f"Week {week_start} days must be exactly contiguous from "
                    f"{week_start}: expected {expected_dates}, got {actual_dates}"
                )
            return week_days.days

        return generate_with_retries(
            llm,
            parse,
            max_attempts=MAX_CHAPTER_ATTEMPTS,
            context=(
                f"chapter week {week_index + 1}/{weeks_total} for "
                f"{self.profile.name} starting {week_start}"
            ),
        )

    # ---------------- ensure (generate only if missing) ----------------

    def ensure_arc(
        self, week: str, force: bool = False
    ) -> tuple[Arc, bool, ArcOutcome | None]:
        """
        Returns `(arc, was_generated, outcome)`. `outcome` is `None` when the
        arc already existed and was simply reused — arcs are user-editable,
        so an existing file always wins unless `force=True`.

        A forced regeneration of an arc that already covers `week` keeps
        that arc's own `start_week` (the same slot), rather than treating
        the arc being replaced as "the previous arc" and skipping past it —
        `determine_new_arc_start`/`get_previous_arc` only apply when there
        is genuinely no arc covering `week` yet.
        """
        existing = self.repository.get_arc_covering(self.profile, week)
        if existing is not None and not force:
            return existing, False, None

        config = self.repository.get_story_config(self.profile)
        if existing is not None:
            start_week = existing.start_week
        else:
            previous = self.repository.get_previous_arc(self.profile, before=week)
            start_week = determine_new_arc_start(previous, week)
        arc, outcome = self.plan_arc(start_week, config.arc_weeks)
        self.repository.save_arc(self.profile, arc)
        logger.success(
            "Arc for {} generated: {} (+{}w)", self.profile.name, start_week, arc.weeks
        )
        return arc, True, outcome

    def ensure_chapter(
        self, arc: Arc, week: str, force: bool = False
    ) -> tuple[Chapter, bool, ChapterOutcome | None]:
        """Same reuse-first contract as `ensure_arc`, one level down."""
        if not force:
            existing = self.repository.get_chapter_covering(self.profile, week)
            if existing is not None:
                return self.sync_hand_edits(arc, existing), False, None

        config = self.repository.get_story_config(self.profile)
        chapter_start, chapter_weeks = chapter_boundaries_for_week(
            arc, config.chapter_weeks, week
        )
        chapter, outcome = self.plan_chapter(arc, chapter_start, chapter_weeks)
        self.repository.save_chapter(self.profile, chapter)
        logger.success(
            "Chapter for {} generated: {} (+{}w)",
            self.profile.name,
            chapter_start,
            chapter.weeks,
        )
        return chapter, True, outcome

    # ---------------- hand edits ----------------

    def sync_hand_edits(self, arc: Arc, chapter: Chapter) -> Chapter:
        """
        Reconciles a reused chapter with any hand edits, saving it only if
        something changed:

        - a day whose situation was edited but whose angles were not gets
          its angles regenerated from the new situation (one LLM call for
          every such day of the chapter), so `plan` never gets an angle
          describing a situation that no longer exists;
        - a day whose angles were edited (with or without its situation),
          or that has no stamp yet, is accepted as it is and re-stamped.

        Days in a week that has already started (its Monday <= today) are
        left alone, same as a frozen `plan`: rewriting them could only
        contradict what may already be published.
        """
        today = date.today()

        def started(day_iso: str) -> bool:
            day = date.fromisoformat(day_iso)
            return day - timedelta(days=day.weekday()) <= today

        stale = [d for d in chapter.days if d.angles_are_stale and not started(d.date)]
        for day in chapter.days:
            if day.angles_are_stale and started(day.date):
                logger.warning(
                    "Chapter {} for {}: situation of {} was edited after its week "
                    "started; not regenerating its angles",
                    chapter.start_week,
                    self.profile.name,
                    day.date,
                )

        new_angles = self._regenerate_angles(arc, chapter, stale) if stale else {}

        days = []
        for day in chapter.days:
            if day.date in new_angles:
                day = day.model_copy(update={"angles": new_angles[day.date]})
            elif day.angles_are_stale:
                days.append(day)  # started week: keep its old stamp
                continue
            days.append(day if day.stamp == day.current_stamp() else day.stamped())

        if days == chapter.days:
            return chapter
        synced = chapter.model_copy(update={"days": days})
        self.repository.save_chapter(self.profile, synced)
        if new_angles:
            logger.success(
                "Chapter {} for {}: regenerated angles for edited day(s) {}",
                chapter.start_week,
                self.profile.name,
                ", ".join(sorted(new_angles)),
            )
        return synced

    def _regenerate_angles(
        self, arc: Arc, chapter: Chapter, stale: list[ChapterDay]
    ) -> dict[str, dict[str, str]]:
        router = _build_router(self.refresh_model_cache)
        context = _build_chapter_context(
            self.repository, self.profile, arc, chapter.start_week
        )
        stale_dates = [day.date for day in stale]
        chapter_lines = [
            f"- {day.date}: {day.situation} — meta: {day.angles['meta']} — "
            f"fanvue: {day.angles['fanvue']}"
            for day in chapter.days
            if day.date not in stale_dates
        ]
        requested_lines = [f"- {day.date}: {day.situation}" for day in stale]
        storyline = (
            f"{context}\n\n## This chapter: {chapter.title}\n{chapter.summary}\n"
            + "\n".join(chapter_lines)
            + "\n\n## Days to rewrite the angles of (new situation)\n"
            + "\n".join(requested_lines)
        )
        llm = BaseLLM(
            prompts=_angles_refresh_prompts(),
            previous_storyline=storyline,
            platform_name=_UNUSED_PLATFORM_FOR_ROUTING,
            model_router=router,
            week_start=date.fromisoformat(chapter.start_week),
        )

        def parse(reply: dict) -> dict[str, dict[str, str]]:
            regenerated = RegeneratedAngles.model_validate(reply)
            got = [day.date for day in regenerated.days]
            if sorted(got) != sorted(stale_dates):
                raise ValueError(f"Expected angles for {stale_dates}, got {got}")
            return {day.date: day.angles for day in regenerated.days}

        try:
            retried = generate_with_retries(
                llm,
                parse,
                max_attempts=MAX_CHAPTER_ATTEMPTS,
                context=(
                    f"angles for edited days {stale_dates} of {self.profile.name}'s "
                    f"chapter {chapter.start_week}"
                ),
            )
        except GenerationFailedError as e:
            raise StoryGenerationFailedError(str(e), e.invalid_attempts) from e
        return retried.value
