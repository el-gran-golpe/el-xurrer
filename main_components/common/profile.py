import re
import json
from pathlib import Path
from loguru import logger

from pydantic import BaseModel, field_validator
from main_components.common.constants import Platform


class PlatformInfo(BaseModel):
    name: Platform
    inputs_path: Path
    outputs_path: Path

    @field_validator("inputs_path", "outputs_path")
    @classmethod
    def must_be_directory(cls, v: Path) -> Path:
        if not v.exists():
            raise FileNotFoundError("Expected path to exist: {}", v)
        if not v.is_dir():
            raise ValueError("Expected a directory at: {}", v)
        return v


class Profile(BaseModel):
    """Describes a persona, with per-platform I/O paths."""

    name: str
    platform_info: dict[Platform, PlatformInfo]

    def __str__(self) -> str:
        return self.name


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

        Checks that every profile directory contains a subfolder for every platform
        defined in Platform. Raises an error if any required platform subfolder is missing.
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

            # 1. Validate profile name
            try:
                self._validate_profile_name(profile_name)
                logger.debug("Validated profile name: {}", profile_name)
            except Exception as e:
                logger.critical("Invalid profile name '{}': {}", profile_name, e)
                raise

            # 2. Check all required platform subfolders exist
            missing_platforms = []
            for platform in Platform:
                platform_subdir = profile_dir / platform.value
                if not platform_subdir.is_dir():
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

            # 3. Validate workflow file
            try:
                self._validate_workflow_file(profile_dir, profile_name)
                logger.debug("Validated workflow file for profile: {}", profile_name)
            except Exception as e:
                logger.critical(
                    "Workflow file validation failed for '{}': {}", profile_name, e
                )
                raise

            # 4. Continue with the rest
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
            raise KeyError("No profile loaded with name '{}'", name)

    def get_profile_by_index(self, index: int) -> Profile:
        try:
            return self._profiles[index]
        except IndexError:
            raise IndexError("Profile index {} is out of range.", index)

    def _validate_profile_name(self, name: str) -> None:
        if not self.PROFILE_NAME_REGEX.match(name):
            raise ValueError(
                "Profile name '{}' must be snake_case (e.g. 'laura_vigne').", name
            )

    def _validate_workflow_file(self, profile_dir: Path, profile_name: str) -> None:
        workflow_file = profile_dir / f"{profile_name}{self.WORKFLOW_SUFFIX}"
        if not workflow_file.exists():
            raise FileNotFoundError("Missing workflow JSON: {}", workflow_file)
        if not workflow_file.is_file():
            raise ValueError("Workflow path is not a file: {}", workflow_file)

    def _gather_platforms(
        self, profile_dir: Path, profile_name: str
    ) -> dict[Platform, PlatformInfo]:
        """
        For each platform subfolder in `profile_dir`, validate and collect I/O paths.

        # Decision:
        # If any profile is incomplete, this will fail—even if you later only use
        # a different platform. We validate all up front for consistency.
        """
        platforms: dict[Platform, PlatformInfo] = {}

        for platform_dir in sorted(profile_dir.iterdir()):
            if not platform_dir.is_dir():
                continue

            try:
                platform = Platform(platform_dir.name)
            except ValueError as e:
                raise ValueError(
                    "Unrecognized platform folder '{}'", platform_dir.name
                ) from e

            inputs = platform_dir / "inputs"
            outputs = platform_dir / "outputs"

            # --- Validate inputs directory and required files ---
            if not inputs.exists() or not inputs.is_dir():
                logger.critical("Inputs directory missing: {}", inputs)
                raise FileNotFoundError("Inputs directory missing: {}", inputs)

            initial_conditions_file = inputs / "initial_conditions.md"
            if not initial_conditions_file.is_file():
                logger.critical("Missing initial_conditions.md in: {}", inputs)
                raise FileNotFoundError("Missing initial_conditions.md in: {}", inputs)
            else:
                content = initial_conditions_file.read_text(encoding="utf-8").strip()
                if not content:
                    logger.warning("initial_conditions.md is empty in {}", inputs)
                else:
                    logger.debug(
                        "initial_conditions.md found in {} and contains text.", inputs
                    )

            # --- Add prompt structure validation here ---
            profile_json = inputs / f"{profile_name}.json"
            with profile_json.open("r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception as e:
                    logger.error("Invalid JSON in {}: {}", profile_json, e)
                    raise ValueError(f"Invalid JSON in {profile_json}: {e}")
                prompts = data.get("prompts")
                if not isinstance(prompts, list) or not prompts:
                    logger.critical(
                        "'prompts' must be a non-empty list in {}", profile_json
                    )
                    raise ValueError(
                        f"'prompts' must be a non-empty list in {profile_json}"
                    )
                # --- Validate "prompt", "cache_key" and "system_prompt" keys and values ---
                for i, prompt_def in enumerate(prompts):
                    required_keys = ("prompt", "cache_key", "system_prompt")
                    if not all(k in prompt_def for k in required_keys):
                        logger.critical(
                            "Prompt #{} in {} is missing required keys {}.",
                            i,
                            profile_json,
                            required_keys,
                        )
                        raise ValueError(
                            f"Prompt #{i} in {profile_json} is missing required keys {required_keys}."
                        )
                    # Validate that each required value is a non-empty string
                    for k in required_keys:
                        v = prompt_def[k]
                        if not isinstance(v, str) or not v.strip():
                            logger.critical(
                                "Prompt #{} in {} has invalid or empty value for key '{}'.",
                                i,
                                profile_json,
                                k,
                            )
                            raise ValueError(
                                f"Prompt #{i} in {profile_json} has invalid or empty value for key '{k}'."
                            )

            # --- Validate {day} in system_prompt ---
            for i, prompt in enumerate(prompts):
                system_prompt = prompt.get("system_prompt")
                if system_prompt and "{day}" not in system_prompt:
                    logger.critical(
                        "\n\n"
                        "Validation Error: The 'system_prompt' for prompt #{} in '{}' is missing the '{{day}}' placeholder.\n"
                        "Each 'system_prompt' must include '{{day}}' so the system can personalize prompts for the correct week.\n"
                        "To fix this:\n"
                        "  1. Open the file: {}\n"
                        "  2. Locate prompt #{} and ensure 'system_prompt' contains '{{day}}'.\n"
                        "     Example: 'Welcome! Today is {{day}}.'\n"
                        "  3. Save the file and rerun your command.\n"
                        "\n"
                        "Project structure reminder:\n"
                        "  - resources/<profile>/<platform>/inputs/<profile>.json (prompt templates)\n"
                        "  - Each 'system_prompt' in this file must have '{{day}}'.\n"
                        "\n"
                        "Invalid system_prompt: {}",
                        i,
                        profile_json,
                        profile_json,
                        i,
                        system_prompt,
                    )
                    raise ValueError(
                        f"Prompt #{i} in {profile_json} is missing '{{day}}' in system_prompt"
                    )
            logger.debug(
                "Validated 'prompts' in {} ({} prompts found)",
                profile_json,
                len(prompts),
            )

            # Ensure outputs directory exists (create if not)
            outputs.mkdir(parents=True, exist_ok=True)

            platforms[platform] = PlatformInfo(
                name=platform, inputs_path=inputs, outputs_path=outputs
            )

        return platforms
