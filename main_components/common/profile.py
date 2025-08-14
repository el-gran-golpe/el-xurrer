import re
import json
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from main_components.common.types import Platform
from main_components.common.types import Profile, PlatformInfo, ProfileInput


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
