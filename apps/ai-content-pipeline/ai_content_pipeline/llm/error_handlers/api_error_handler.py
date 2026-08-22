from typing import Mapping


def parse_retry_after(headers: Mapping[str, str], default_seconds: int) -> int:
    """Best-effort parse of a Retry-After header; falls back to a default if missing/unparseable."""
    raw = headers.get("retry-after") if headers else None
    if raw is None:
        return default_seconds
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default_seconds
