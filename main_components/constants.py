from enum import Enum


class Platform(str, Enum):
    """Enumeration of supported platforms."""

    META = "meta"
    FANVUE = "fanvue"
