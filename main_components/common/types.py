import re
from pathlib import Path
from pydantic import BaseModel, field_validator, ConfigDict
from enum import Enum


# ---------------------------
# Pydantic models (strict)
# ---------------------------


# --- Platform ---


class Platform(str, Enum):
    """Enumeration of supported platforms."""

    META = "meta"
    FANVUE = "fanvue"


class PlatformInfo(BaseModel):
    name: Platform
    inputs_path: Path
    outputs_path: Path
    lang: str  # language for this platform/profile input (e.g., "en", "es", "en-US")

    @field_validator("inputs_path", "outputs_path")
    @classmethod
    def must_be_directory(cls, v: Path) -> Path:
        if not v.exists():
            raise FileNotFoundError(f"Expected path to exist: {v}")
        if not v.is_dir():
            raise ValueError(f"Expected a directory at: {v}")
        return v

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str) -> str:
        # Accept "en", "es", or BCP47-ish like "en-US", "pt-BR"
        if not isinstance(v, str) or not v.strip():
            raise ValueError("lang must be a non-empty string")
        if not re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", v):
            raise ValueError(
                "lang must be a 2-letter code optionally followed by a region, "
                "e.g., 'en', 'es', 'en-US'"
            )
        return v


class PromptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    cache_key: str
    system_prompt: str
    output_as_json: bool
    is_sensitive_content: bool

    @field_validator("prompt", "cache_key", "system_prompt")
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("system_prompt")
    @classmethod
    def must_contain_day_placeholder(cls, v: str) -> str:
        if "{day}" not in v:
            raise ValueError("system_prompt must include '{day}'")
        return v


# --- Profile ---


class Profile(BaseModel):
    """Describes a persona, with per-platform I/O paths."""

    name: str
    platform_info: dict[Platform, PlatformInfo]

    def __str__(self) -> str:
        return self.name


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lang: str
    prompts: list[PromptItem]

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("lang must be a non-empty string")
        if not re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", v):
            raise ValueError(
                "lang must be a 2-letter code optionally followed by a region, "
                "e.g., 'en', 'es', 'en-US'"
            )
        return v

    @field_validator("prompts")
    @classmethod
    def prompts_non_empty_and_unique_cache_keys(
        cls, prompts: list[PromptItem]
    ) -> list[PromptItem]:
        if not prompts:
            raise ValueError("'prompts' must be a non-empty list")
        seen: set[str] = set()
        for i, p in enumerate(prompts):
            if p.cache_key in seen:
                raise ValueError(
                    f"duplicate cache_key '{p.cache_key}' at prompt index {i}"
                )
            seen.add(p.cache_key)
        return prompts
