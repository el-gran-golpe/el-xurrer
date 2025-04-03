from pathlib import Path

from pydantic import BaseModel


class Profile(BaseModel):
    """Profile model for Meta profiles."""

    name: str
    inputs: Path
    outputs: Path
