import re
import json
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, field_validator, ValidationError
from pydantic import ConfigDict

from main_components.common.constants import Platform


# ---------------------------
# Pydantic models (strict)
# ---------------------------


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


class Profile(BaseModel):
    """Describes a persona, with per-platform I/O paths."""

    name: str
    platform_info: dict[Platform, PlatformInfo]

    def __str__(self) -> str:
        return self.name


# ---------------------------
# Manager
# ---------------------------


class ProfileManager:
    """Manager for loading and retrieving Profile objects."""

    PROFILE_NAME_REGEX = re.compile(r"^[a-z][a-z0-9]*_[a-z][a-z0-9]*$")
    WORKFLOW_SUFFIX = "_comfyworkflow.json"

    def __init__(self, resource_path: Path):
        self.resource_path = resource_path
        self._profiles_by_name: dict[str, Profile] = {}
        self._profiles: list[Profile] = []

    def load_profiles(self) -> None:
        """
        Scan `resource_path` for valid profile directories and load them.
        Strict validation: new JSON schema only (lang + prompts).
        """
        if not self.resource_path.is_dir():
            logger.critical("Resource directory not found: {}", self.resource_path)
            raise FileNotFoundError(
                f"Resource directory not found: {self.resource_path}"
            )

        profile_dirs = [d for d in sorted(self.resource_path.iterdir()) if d.is_dir()]
        logger.info("Found {} profile directories.", len(profile_dirs))

        for profile_dir in profile_dirs:
            profile_name = profile_dir.name

            # 1) Validate profile name
            try:
                self._validate_profile_name(profile_name)
                logger.debug("Validated profile name: {}", profile_name)
            except Exception as e:
                logger.critical("Invalid profile name '{}': {}", profile_name, e)
                raise

            # 2) Ensure each required platform subfolder exists
            missing_platforms = []
            for platform in Platform:
                if not (profile_dir / platform.value).is_dir():
                    missing_platforms.append(platform.value)
            if missing_platforms:
                logger.critical(
                    "Profile '{}' is missing required platform subfolders: {}",
                    profile_name,
                    missing_platforms,
                )
                raise FileNotFoundError(
                    f"Profile '{profile_name}' is missing required platform subfolders: {missing_platforms}"
                )
            logger.debug(
                "All required platform subfolders exist for profile '{}'.", profile_name
            )

            # 3) Validate workflow file
            try:
                self._validate_workflow_file(profile_dir, profile_name)
                logger.debug("Validated workflow file for profile: {}", profile_name)
            except Exception as e:
                logger.critical(
                    "Workflow file validation failed for '{}': {}", profile_name, e
                )
                raise

            # 4) Gather per-platform info (+ strict prompt & lang validation)
            try:
                platforms = self._gather_platforms(profile_dir, profile_name)
                profile = Profile(name=profile_name, platform_info=platforms)
                self._profiles_by_name[profile_name] = profile
                self._profiles.append(profile)
                logger.success("Profile {} loaded and validated.", profile_name)
            except Exception as e:
                logger.critical("Failed to load profile '{}': {}", profile_name, e)
                raise

    def get_profile_by_name(self, name: str) -> Profile:
        try:
            return self._profiles_by_name[name]
        except KeyError:
            raise KeyError(f"No profile loaded with name '{name}'")

    def get_profile_by_index(self, index: int) -> Profile:
        try:
            return self._profiles[index]
        except IndexError:
            raise IndexError(f"Profile index {index} is out of range.")

    def _validate_profile_name(self, name: str) -> None:
        if not self.PROFILE_NAME_REGEX.match(name):
            raise ValueError(
                f"Profile name '{name}' must be snake_case (e.g. 'laura_vigne')."
            )

    def _validate_workflow_file(self, profile_dir: Path, profile_name: str) -> None:
        workflow_file = profile_dir / f"{profile_name}{self.WORKFLOW_SUFFIX}"
        if not workflow_file.exists():
            raise FileNotFoundError(f"Missing workflow JSON: {workflow_file}")
        if not workflow_file.is_file():
            raise ValueError(f"Workflow path is not a file: {workflow_file}")

    def _gather_platforms(
        self, profile_dir: Path, profile_name: str
    ) -> dict[Platform, PlatformInfo]:
        """
        For each Platform subfolder in `profile_dir`, validate and collect I/O paths.
        """
        platforms: dict[Platform, PlatformInfo] = {}

        for platform in Platform:
            platform_dir = profile_dir / platform.value
            inputs = platform_dir / "inputs"
            outputs = platform_dir / "outputs"

            # --- Validate inputs directory and required files ---
            if not inputs.exists() or not inputs.is_dir():
                logger.critical("Inputs directory missing: {}", inputs)
                raise FileNotFoundError(f"Inputs directory missing: {inputs}")

            initial_conditions_file = inputs / "initial_conditions.md"
            if not initial_conditions_file.is_file():
                logger.critical("Missing initial_conditions.md in: {}", inputs)
                raise FileNotFoundError(f"Missing initial_conditions.md in: {inputs}")
            else:
                content = initial_conditions_file.read_text(encoding="utf-8").strip()
                if not content:
                    logger.warning("initial_conditions.md is empty in {}", inputs)
                else:
                    logger.debug(
                        "initial_conditions.md found in {} and contains text.", inputs
                    )

            # --- Validate prompt structure (strict: requires lang + prompts) ---
            profile_json = inputs / f"{profile_name}.json"
            if not profile_json.exists():
                logger.critical("Missing profile JSON: {}", profile_json)
                raise FileNotFoundError(f"Missing profile JSON: {profile_json}")
            if not profile_json.is_file():
                logger.critical("Profile JSON path is not a file: {}", profile_json)
                raise ValueError(f"Profile JSON path is not a file: {profile_json}")

            with profile_json.open("r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception as e:
                    logger.error("Invalid JSON in {}: {}", profile_json, e)
                    raise ValueError(f"Invalid JSON in {profile_json}: {e}")

            try:
                profile_input = ProfileInput.model_validate(data)
            except ValidationError as ve:
                # surface a clean error with file context
                raise ValueError(
                    f"Prompt schema error in {profile_json}:\n{ve}"
                ) from ve

            logger.debug(
                "Validated 'prompts' in {} ({} prompts found) with lang '{}'",
                profile_json,
                len(profile_input.prompts),
                profile_input.lang,
            )

            # Ensure outputs directory exists (create if not)
            outputs.mkdir(parents=True, exist_ok=True)

            platforms[platform] = PlatformInfo(
                name=platform,
                inputs_path=inputs,
                outputs_path=outputs,
                lang=profile_input.lang,
            )

        return platforms
