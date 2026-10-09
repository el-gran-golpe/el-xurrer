from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from pydantic import BaseModel, field_validator

# One post's caption gets truncated to roughly this many characters in the
# weekly recap (`summarize_week`), so a verbose caption cannot blow up the
# next week's prompt size.
_SUMMARY_CAPTION_MAX_CHARS = 280

DAYS_PER_WEEK = 7
# Time of day used when the model's upload_time does not parse at all.
_FALLBACK_UPLOAD_TIME = time(18, 0, tzinfo=timezone.utc)


# Defaults mirror the `.get(..., default)` reads the consumers did on the raw
# planning dict, so an LLM reply that omitted a field still loads as before.


class ImagePlan(BaseModel):
    image_description: str = ""


class PostPlan(BaseModel):
    title: str = ""
    caption: str = ""
    # One space-separated string, as the planning prompts ask for and every
    # stored planning holds. Some models still reply with a list.
    hashtags: str = ""
    upload_time: str = ""
    images: list[ImagePlan] = []

    @field_validator("hashtags", mode="before")
    @classmethod
    def _join_hashtag_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return " ".join(str(tag).strip() for tag in value if str(tag).strip())
        return value


class DayPlan(BaseModel):
    day: int
    posts: list[PostPlan] = []


class WeekPlan(BaseModel):
    """What one platform publishes in one week, for one profile."""

    week: str  # the planning's top-level key, e.g. "week_1"
    days: list[DayPlan]

    @classmethod
    def from_planning_dict(cls, planning: dict[str, Any]) -> "WeekPlan":
        """Parses the `{week: [days]}` shape the LLM returns and disk stores."""
        if len(planning) != 1:
            raise ValueError(
                f"Expected exactly one week in the planning, got {list(planning)}"
            )
        [(week, days)] = planning.items()
        return cls.model_validate({"week": week, "days": days})

    def to_planning_dict(self) -> dict[str, Any]:
        return {self.week: [day.model_dump() for day in self.days]}

    def pin_to_week(self, week_start: date) -> list[str]:
        """
        Enforces one publication day per calendar day: day N's posts go out on
        `week_start + (N - 1)`, keeping the time of day the model chose. Models
        reliably return days 1-7 but often bunch their dates (seven posts on
        two days), and the date is the one part the code can fix without
        another LLM call.

        Raises ValueError when the plan is not exactly days 1-7, each with at
        least one post: that is content the code cannot invent, so the `plan`
        job fails and is re-planned on the next run. Returns one message per
        upload_time it changed, for the caller to log.
        """
        day_numbers = sorted(day.day for day in self.days)
        if day_numbers != list(range(1, DAYS_PER_WEEK + 1)):
            raise ValueError(
                f"Expected days 1-{DAYS_PER_WEEK} once each, got {day_numbers}"
            )
        empty = [day.day for day in self.days if not day.posts]
        if empty:
            raise ValueError(f"Days without any post: {empty}")

        corrections: list[str] = []
        for day in self.days:
            day_date = week_start + timedelta(days=day.day - 1)
            for post in day.posts:
                pinned = datetime.combine(day_date, _time_of_day(post.upload_time))
                pinned_text = pinned.isoformat().replace("+00:00", "Z")
                if pinned_text != post.upload_time:
                    corrections.append(
                        f"day {day.day}: {post.upload_time or '<empty>'} -> {pinned_text}"
                    )
                    post.upload_time = pinned_text
        return corrections


def _time_of_day(upload_time: str) -> time:
    """The time (with its offset) of an upload_time, or the fallback."""
    try:
        parsed = datetime.fromisoformat(upload_time.replace("Z", "+00:00"))
    except ValueError:
        return _FALLBACK_UPLOAD_TIME
    # A naive time would be read in the machine's timezone; pin it to UTC.
    return (
        parsed.timetz() if parsed.tzinfo else parsed.time().replace(tzinfo=timezone.utc)
    )


def _post_date_label(post: PostPlan) -> str | None:
    """The post's upload date, when `upload_time` parses, else None."""
    if not post.upload_time:
        return None
    try:
        return (
            datetime.fromisoformat(post.upload_time.replace("Z", "+00:00"))
            .date()
            .isoformat()
        )
    except ValueError:
        return None


def summarize_week(plan: WeekPlan) -> str:
    """
    Deterministic, LLM-free recap of a past week: one line per day, with its
    date (from `upload_time` when parseable), title, and a caption truncated
    to ~280 chars. No LLM call, so chaining continuity across weeks costs no
    extra quota and the resume hash (`jobs/tasks.py:run_plan`) stays stable
    as long as the previous week's plan itself does not change.

    A day with more than one post only summarizes its first post — this is a
    compact recap, not a full transcript.
    """
    lines: list[str] = []
    for day in plan.days:
        if not day.posts:
            continue
        post = day.posts[0]
        label = _post_date_label(post) or f"day {day.day}"
        caption = post.caption.strip()
        if len(caption) > _SUMMARY_CAPTION_MAX_CHARS:
            caption = caption[: _SUMMARY_CAPTION_MAX_CHARS - 3].rstrip() + "..."
        title = post.title.strip()
        text = f"{title} — {caption}" if title else caption
        lines.append(f"- {label}: {text}")
    return "\n".join(lines)
