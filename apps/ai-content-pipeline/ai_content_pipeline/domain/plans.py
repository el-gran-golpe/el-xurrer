from typing import Any

from pydantic import BaseModel


# Defaults mirror the `.get(..., default)` reads the consumers did on the raw
# planning dict, so an LLM reply that omitted a field still loads as before.


class ImagePlan(BaseModel):
    image_description: str = ""


class PostPlan(BaseModel):
    title: str = ""
    caption: str = ""
    hashtags: list[str] = []
    upload_time: str = ""
    images: list[ImagePlan] = []


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
