"""
Arc -> chapter domain models (see `docs/story-dag.md` for the flow): the
arc is a free, platform-blind season-level intention; the chapter tiles it into day-by-day, platform-aware
beats; `plan` (domain/plans.py) reads only one week's slice of one chapter.

Pure data + pure helpers here, no filesystem and no LLM — those live in
`profiles/repository.py` and `planning/story_manager.py` respectively.
"""

import hashlib
import json
from datetime import date, timedelta

from pydantic import BaseModel, field_validator, model_validator

from ai_content_pipeline.domain.types import Platform

DEFAULT_ARC_WEEKS = 12
DEFAULT_CHAPTER_WEEKS = 4
DAYS_PER_WEEK = 7


def _must_be_iso_monday(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"'{value}' is not an ISO date (YYYY-MM-DD)")
    if parsed.weekday() != 0:
        raise ValueError(f"'{value}' is not a Monday")
    return value


class StoryConfig(BaseModel):
    """
    Per-profile arc/chapter durations. A profile with no `story/config.json`
    reads these defaults (`FilesystemProfileRepository.get_story_config`).
    """

    arc_weeks: int = DEFAULT_ARC_WEEKS
    chapter_weeks: int = DEFAULT_CHAPTER_WEEKS

    @field_validator("arc_weeks", "chapter_weeks")
    @classmethod
    def must_be_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value

    @model_validator(mode="after")
    def chapter_fits_in_the_arc(self) -> "StoryConfig":
        if self.chapter_weeks > self.arc_weeks:
            raise ValueError(
                f"chapter_weeks ({self.chapter_weeks}) must be <= "
                f"arc_weeks ({self.arc_weeks})"
            )
        return self


class Arc(BaseModel):
    """
    One season's narrative intention. Free: no platform ever reads this
    directly (the chapter does, and only the chapter is split into platform
    angles), so it may contain the adult half of the story.
    """

    start_week: str  # ISO Monday
    weeks: int
    title: str
    premise: str
    goal: str
    conflict: str
    starting_point: str
    ending_point: str
    summary: str

    @field_validator("start_week")
    @classmethod
    def start_week_is_a_monday(cls, value: str) -> str:
        return _must_be_iso_monday(value)

    @field_validator("weeks")
    @classmethod
    def weeks_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("weeks must be >= 1")
        return value

    @property
    def end_week(self) -> str:
        """The ISO Monday of this arc's last week."""
        start = date.fromisoformat(self.start_week)
        return (start + timedelta(weeks=self.weeks - 1)).isoformat()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class DayStamp(BaseModel):
    """
    Fingerprint of a `ChapterDay`'s `situation` and `angles` as they were
    last written together (by the model, or accepted after a hand edit).
    Lets `StoryManager` tell "the user edited only the situation" — the
    angles were written for a situation that no longer exists, so they are
    regenerated — from "the user edited the angles" (kept as they are).
    """

    situation: str
    angles: str


class ChapterDay(BaseModel):
    """
    One shared day of story: a neutral `situation` (valid for every
    platform) plus one `angle` per platform (keyed by `Platform.value`) on
    how that platform lives it — e.g. Meta gets the public face, Fanvue the
    private one. The angles are derived from the situation, never the
    other way around. `stamp` is `None` for a day written before stamps
    existed.
    """

    date: str  # ISO date
    situation: str
    angles: dict[str, str]
    stamp: DayStamp | None = None

    @field_validator("date")
    @classmethod
    def date_is_iso(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"'{value}' is not an ISO date (YYYY-MM-DD)")
        return value

    @field_validator("angles")
    @classmethod
    def angles_cover_every_platform(cls, value: dict[str, str]) -> dict[str, str]:
        missing = [p.value for p in Platform if p.value not in value]
        if missing:
            raise ValueError(f"angles missing for platform(s): {missing}")
        return value

    def current_stamp(self) -> DayStamp:
        return DayStamp(
            situation=_short_hash(self.situation),
            angles=_short_hash(json.dumps(self.angles, sort_keys=True)),
        )

    def stamped(self) -> "ChapterDay":
        """A copy whose `stamp` matches its current situation and angles."""
        return self.model_copy(update={"stamp": self.current_stamp()})

    @property
    def angles_are_stale(self) -> bool:
        """True when only the situation changed since the last stamp: the
        angles still describe the old situation. A day whose angles were
        edited too (or that has no stamp) is not stale — the user's angles
        win."""
        if self.stamp is None:
            return False
        current = self.current_stamp()
        return (
            current.situation != self.stamp.situation
            and current.angles == self.stamp.angles
        )


class Chapter(BaseModel):
    """
    One tile of an arc: `weeks` consecutive weeks, day by day, platform-aware.
    The story the platforms actually read — `plan` only ever sees one week's
    `week_slice()` of this, never the arc.
    """

    arc_start_week: str
    start_week: str  # ISO Monday
    weeks: int
    title: str
    summary: str
    days: list[ChapterDay]

    @field_validator("arc_start_week", "start_week")
    @classmethod
    def week_fields_are_mondays(cls, value: str) -> str:
        return _must_be_iso_monday(value)

    @field_validator("weeks")
    @classmethod
    def weeks_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("weeks must be >= 1")
        return value

    @model_validator(mode="after")
    def days_are_exactly_contiguous(self) -> "Chapter":
        expected_count = self.weeks * DAYS_PER_WEEK
        if len(self.days) != expected_count:
            raise ValueError(
                f"Expected {expected_count} days ({self.weeks} week(s) x "
                f"{DAYS_PER_WEEK}), got {len(self.days)}"
            )
        start = date.fromisoformat(self.start_week)
        expected_dates = [
            (start + timedelta(days=i)).isoformat() for i in range(expected_count)
        ]
        actual_dates = [day.date for day in self.days]
        if actual_dates != expected_dates:
            raise ValueError(
                f"Chapter days must be exactly contiguous from {self.start_week}: "
                f"expected {expected_dates}, got {actual_dates}"
            )
        return self

    def week_slice(self, week: str) -> list[ChapterDay]:
        """The 7 `ChapterDay`s for `week` (an ISO Monday), in date order.

        Raises `ValueError` if this chapter does not fully cover `week` —
        `build_previous_storyline` relies on that to surface a clear error
        when a week has no chapter, rather than silently returning less than
        7 days."""
        start = date.fromisoformat(self.start_week)
        target = date.fromisoformat(week)
        offset_days = (target - start).days
        if offset_days < 0 or offset_days % DAYS_PER_WEEK != 0:
            raise ValueError(
                f"Week {week} does not align with chapter {self.start_week}"
            )
        if offset_days + DAYS_PER_WEEK > len(self.days):
            raise ValueError(
                f"Chapter {self.start_week} ({self.weeks} week(s)) does not "
                f"cover week {week}"
            )
        return self.days[offset_days : offset_days + DAYS_PER_WEEK]


class ChapterOutline(BaseModel):
    """
    A chapter's title, overall summary, and one short summary per week —
    produced by a small/cheap outline call *before* any day-by-day content,
    so a single LLM reply never has to carry a whole multi-week chapter's
    worth of days at once (a real run got a 7-day reply for a 28-day
    chapter). `StoryManager.plan_chapter` generates one of these first, then
    one more call per week to fill in that week's `ChapterDay`s, using this
    outline (and the days written so far for this chapter's earlier weeks)
    for continuity. Not persisted on its own — only the assembled `Chapter`
    is ever saved, and only once every week succeeded.
    """

    title: str
    summary: str
    week_summaries: list[str]

    @field_validator("week_summaries")
    @classmethod
    def must_not_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("week_summaries must not be empty")
        return value


class ChapterWeekDays(BaseModel):
    """
    One week's worth of `ChapterDay`s — the wire shape for a single week
    call in `StoryManager.plan_chapter`'s split chapter generation. Several
    of these (one per week) are concatenated into one `Chapter.days` list,
    which is then validated as a whole exactly as before. Not persisted on
    its own.
    """

    days: list[ChapterDay]

    @field_validator("days")
    @classmethod
    def must_be_exactly_one_week(cls, value: list[ChapterDay]) -> list[ChapterDay]:
        if len(value) != DAYS_PER_WEEK:
            raise ValueError(
                f"Expected {DAYS_PER_WEEK} days for one week, got {len(value)}"
            )
        return value


class DayAngles(BaseModel):
    """One day's regenerated angles — the wire shape for
    `StoryManager.refresh_stale_angles`. Not persisted on its own."""

    date: str
    angles: dict[str, str]

    @field_validator("angles")
    @classmethod
    def angles_cover_every_platform(cls, value: dict[str, str]) -> dict[str, str]:
        missing = [p.value for p in Platform if p.value not in value]
        if missing:
            raise ValueError(f"angles missing for platform(s): {missing}")
        return value


class RegeneratedAngles(BaseModel):
    days: list[DayAngles]


def determine_new_arc_start(previous_arc: Arc | None, requested_week: str) -> str:
    """
    Where a brand-new arc should start: the Monday right after the previous
    arc ends, or `requested_week` itself when there is no previous arc. Pure
    function of the two inputs, same spirit as `planning_week_start` — the
    story chain only ever asks for consecutive weeks, so in practice this
    lines up with `requested_week` whenever a previous arc exists.
    """
    if previous_arc is None:
        return requested_week
    return (date.fromisoformat(previous_arc.end_week) + timedelta(days=7)).isoformat()


def chapter_boundaries_for_week(
    arc: Arc, chapter_weeks: int, week: str
) -> tuple[str, int]:
    """
    The (start_week, weeks) a chapter covering `week` must have, tiling the
    arc in `chapter_weeks`-sized chunks starting at `arc.start_week`. The
    last chapter of an arc is shorter than `chapter_weeks` whenever
    `arc.weeks` is not a multiple of it.
    """
    arc_start = date.fromisoformat(arc.start_week)
    target = date.fromisoformat(week)
    offset_weeks = (target - arc_start).days // 7
    if (
        (target - arc_start).days % 7 != 0
        or offset_weeks < 0
        or offset_weeks >= arc.weeks
    ):
        raise ValueError(f"Week {week} is outside arc {arc.start_week} (+{arc.weeks}w)")

    chapter_index = offset_weeks // chapter_weeks
    chapter_start_offset = chapter_index * chapter_weeks
    chapter_start = (arc_start + timedelta(weeks=chapter_start_offset)).isoformat()
    length = min(chapter_weeks, arc.weeks - chapter_start_offset)
    return chapter_start, length
