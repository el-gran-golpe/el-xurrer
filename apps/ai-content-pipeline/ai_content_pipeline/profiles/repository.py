import re
import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from loguru import logger
from pydantic import ValidationError

from ai_content_pipeline.domain.plans import WeekPlan
from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.domain.types import (
    PlatformInfo,
    PlatformProfile,
    Profile,
    ProfileInput,
)
from ai_content_pipeline.config import settings


def _read_profile_input(inputs_path: Path, profile_name: str) -> ProfileInput:
    """
    Parses and validates one platform's `{profile}.json`. Shared by profile
    loading (which validates every profile up front) and by the repository
    (which needs the prompts at planning time), so the file layout and its
    error messages are described once.
    """
    profile_json = inputs_path / f"{profile_name}.json"
    if not profile_json.exists():
        logger.critical("Missing profile JSON: {}", profile_json)
        raise FileNotFoundError(f"Missing profile JSON: {profile_json}")
    if not profile_json.is_file():
        logger.critical("Profile JSON path is not a file: {}", profile_json)
        raise ValueError(f"Profile JSON path is not a file: {profile_json}")

    try:
        data = json.loads(profile_json.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Invalid JSON in {}: {}", profile_json, e)
        raise ValueError(f"Invalid JSON in {profile_json}: {e}")

    try:
        return ProfileInput.model_validate(data)
    except ValidationError as ve:
        # surface a clean error with file context
        raise ValueError(f"Prompt schema error in {profile_json}:\n{ve}") from ve


class ProfileRepository(Protocol):
    """
    Everything that lives in `resources/`: which profiles exist, and each
    one's planning inputs and outputs. Consumers only see domain models,
    never paths or file formats, so a future backend (e.g. a DB) implements
    the same methods — same pattern as `JobStore`/`Queue`/`GenerationBackend`
    in `jobs/`.
    """

    def load_profiles(self) -> None: ...

    def get_profile_by_name(self, name: str) -> Profile: ...

    def get_profile_by_index(self, index: int) -> Profile: ...

    def get_all_profiles(self) -> list[Profile]: ...

    def get_platform_profile(
        self, profile: Profile, platform: Platform
    ) -> PlatformProfile: ...

    def get_week_plan(self, profile: Profile, platform: Platform) -> WeekPlan: ...

    def save_week_plan(
        self, profile: Profile, platform: Platform, plan: WeekPlan
    ) -> None: ...

    def add_storyline_summary(
        self, profile: Profile, platform: Platform, summary: str
    ) -> None: ...


class FilesystemProfileRepository:
    """
    V1: today's files, paths and formats under `resources/`. Discovering and
    validating profiles is the same job as reading their planning files —
    both are this tree on disk — so it lives here rather than in a separate
    manager.
    """

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
                # TODO: Add Fanvue credential checks here
                meta_credentials = settings.get_meta_credentials(profile_name)
                profile = Profile(
                    name=profile_name,
                    platform_info=platforms,
                    meta_credentials=meta_credentials,
                )
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

    def get_all_profiles(self) -> list[Profile]:
        return list(self._profiles)

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
            profile_input = _read_profile_input(inputs, profile_name)
            logger.debug(
                "Validated 'prompts' in {} ({} prompts found) with lang '{}'",
                inputs / f"{profile_name}.json",
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

    def _inputs(self, profile: Profile, platform: Platform) -> Path:
        return profile.platform_info[platform].inputs_path

    def _initial_conditions_path(self, profile: Profile, platform: Platform) -> Path:
        return self._inputs(profile, platform) / "initial_conditions.md"

    def _planning_path(self, profile: Profile, platform: Platform) -> Path:
        initials = "".join(part[0] for part in profile.name.split("_"))
        outputs = profile.platform_info[platform].outputs_path
        return outputs / f"{initials}_planning.json"

    def get_platform_profile(
        self, profile: Profile, platform: Platform
    ) -> PlatformProfile:
        profile_input = _read_profile_input(
            self._inputs(profile, platform), profile.name
        )
        initial_conditions = (
            self._initial_conditions_path(profile, platform)
            .read_text(encoding="utf-8")
            .strip()
        )
        return PlatformProfile(
            platform=platform,
            lang=profile_input.lang,
            prompts=profile_input.prompts,
            initial_conditions=initial_conditions,
        )

    def get_week_plan(self, profile: Profile, platform: Platform) -> WeekPlan:
        text = self._planning_path(profile, platform).read_text(encoding="utf-8")
        return WeekPlan.from_planning_dict(json.loads(text))

    def save_week_plan(
        self, profile: Profile, platform: Platform, plan: WeekPlan
    ) -> None:
        with open(self._planning_path(profile, platform), "w", encoding="utf-8") as f:
            json.dump(plan.to_planning_dict(), f, indent=4, ensure_ascii=False)

    def add_storyline_summary(
        self, profile: Profile, platform: Platform, summary: str
    ) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"\n\n---\n**[{timestamp}] - Recent Content Summary:**\n{summary}\n"
        path = self._initial_conditions_path(profile, platform)
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
