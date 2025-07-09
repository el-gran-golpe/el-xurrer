import re
from pathlib import Path
from typing import Dict, List
from loguru import logger

from pydantic import BaseModel, field_validator
from main_components.constants import Platform


class PlatformInfo(BaseModel):
    name: Platform
    inputs_path: Path
    outputs_path: Path

    @field_validator("inputs_path", "outputs_path")
    @classmethod
    def must_be_directory(cls, v: Path) -> Path:
        if not v.exists():
            raise FileNotFoundError(f"Expected path to exist: {v}")
        if not v.is_dir():
            raise ValueError(f"Expected a directory at: {v}")
        return v


class Profile(BaseModel):
    """Describes a persona, with per-platform I/O paths."""

    name: str
    platform_info: Dict[Platform, PlatformInfo]

    def __str__(self) -> str:
        return self.name


# TODO: we might be able to use Pydantic models instead of doing manual validations
class ProfileManager:
    """Manager for loading and retrieving Profile objects."""

    PROFILE_NAME_REGEX = re.compile(r"^[a-z][a-z0-9]*_[a-z][a-z0-9]*$")
    WORKFLOW_SUFFIX = "_comfyworkflow.json"

    def __init__(self, resource_path: Path):
        self.resource_path = resource_path
        self._profiles_by_name: Dict[str, Profile] = {}
        self._profiles: List[Profile] = []

    def load_profiles(self) -> None:
        """
        Scan `resource_path` for valid profile directories and load them.

        This runs once at startup and verifies every profile folder, even those not in use,
        so that all personas are validated up front.

        A valid profile folder must:
          - Be named in snake_case (e.g., "laura_vigne").
          - Contain a ComfyUI workflow file named `<folder>_comfyworkflow.json`.
          - For each platform subfolder:
            - Have an `inputs/initial_conditions.md` file.
            - Have an `inputs/<profile_name>.json` file.
            - Have (or be able to create) an `outputs/` directory.

        Raises:
            FileNotFoundError: if resource_path is missing or expected files/dirs are absent.
            ValueError: if naming conventions or types are incorrect.
        """
        if not self.resource_path.is_dir():
            raise FileNotFoundError(
                f"Resource directory not found: {self.resource_path}"
            )

        for profile_dir in sorted(self.resource_path.iterdir()):
            if not profile_dir.is_dir():
                continue

            profile_name = profile_dir.name
            self._validate_profile_name(profile_name)
            self._validate_workflow_file(profile_dir, profile_name)

            platforms = self._gather_platforms(profile_dir, profile_name)

            profile = Profile(name=profile_name, platform_info=platforms)
            self._profiles_by_name[profile_name] = profile
            self._profiles.append(profile)

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
    ) -> Dict[Platform, PlatformInfo]:
        """
        For each platform subfolder in `profile_dir`, validate and collect I/O paths.

        # Decision:
        # If any profile is incomplete, this will fail—even if you later only use
        # a different platform. We validate all up front for consistency.
        """
        platforms: Dict[Platform, PlatformInfo] = {}

        for platform_dir in sorted(profile_dir.iterdir()):
            if not platform_dir.is_dir():
                continue

            try:
                platform = Platform(platform_dir.name)
            except ValueError as e:
                raise ValueError(
                    f"Unrecognized platform folder '{platform_dir.name}'"
                ) from e

            inputs = platform_dir / "inputs"
            outputs = platform_dir / "outputs"

            # Validate inputs directory and required files
            if not inputs.exists() or not inputs.is_dir():
                raise FileNotFoundError(f"Inputs directory missing: {inputs}")

            initial_conditions_file = inputs / "initial_conditions.md"
            if not initial_conditions_file.is_file():
                raise FileNotFoundError(f"Missing initial_conditions.md in: {inputs}")
            else:
                content = initial_conditions_file.read_text(encoding="utf-8").strip()
                if not content:
                    logger.warning(f"initial_conditions.md is empty in {inputs}")
                else:
                    logger.info(
                        f"initial_conditions.md found in {inputs} and contains text."
                    )

            profile_json = inputs / f"{profile_name}.json"
            if not profile_json.is_file():
                raise FileNotFoundError(f"Missing profile JSON in: {inputs}")

            # Ensure outputs directory exists (create if not)
            outputs.mkdir(parents=True, exist_ok=True)

            platforms[platform] = PlatformInfo(
                name=platform, inputs_path=inputs, outputs_path=outputs
            )

        return platforms
