from pathlib import Path
import re
from pydantic import BaseModel
from main_components.constants import Platform


class PlatformInfo(BaseModel):
    """Platform information model."""

    name: str
    inputs_path: Path
    outputs_path: Path


class Profile(BaseModel):
    """Profile model for Meta profiles."""

    name: str
    platform_info: dict[Platform, PlatformInfo] = {}

    def __str__(self):
        return self.name


class ProfileManager:
    """Manager for handling profiles."""

    def __init__(self, resource_path: Path):
        self.resource_path = resource_path
        self.__profiles_by_name: dict[str, Profile] = {}
        self.__profiles_by_index: list[Profile] = []

    def load_profiles(self):
        """This method will go to the folder called resources and check that the profiles
        actually exist. For a profile (persona) to be valid, it must contain an initial
        conditions file and a .json file named after the folder, that contains the
        instructions for the LLM. The folder must be named in snake_case.

        Also, this is run once at the beginning and checks each and every profile folder even
        if we are not using it, so that we can ensure that all personas are valid.
        """
        if not self.resource_path.is_dir():
            raise FileNotFoundError(
                f"Resource path does not exist: {self.resource_path}"
            )

        for profile_dir in self.resource_path.iterdir():
            if not profile_dir.is_dir():
                continue

            profile_name = profile_dir.name
            # Check profile name is in snake case
            profile_pattern = re.compile(r"^[a-z][a-z0-9]*_[a-z][a-z0-9]*$")
            if not profile_pattern.match(profile_name):
                raise ValueError(
                    f"Profile name '{profile_name}' is not in the format 'word_word' (e.g., 'laura_vigne')"
                )

            # Check for ComfyUI workflow file
            workflow_filename = f"{profile_name}_comfyworkflow.json"
            workflow_path = profile_dir / workflow_filename
            if not workflow_path.exists():
                raise FileNotFoundError(
                    f"ComfyUI workflow file does not exist: {workflow_path}"
                )
            if not workflow_path.is_file():
                raise ValueError(
                    f"ComfyUI workflow path is not a file: {workflow_path}"
                )

            platforms_info = {}
            for platform_dir in profile_dir.iterdir():
                if not platform_dir.is_dir():
                    continue

                platform_name = Platform(platform_dir.name)
                inputs_path = platform_dir / "inputs"
                outputs_path = platform_dir / "outputs"

                if not inputs_path.exists():
                    raise FileNotFoundError(
                        f"Inputs path does not exist: {inputs_path}"
                    )
                else:
                    # Decision: If any profile is incomplete, it will fail even if we are running code that is not
                    # directly related with that platform
                    initial_conditions_path = inputs_path / "initial_conditions.md"
                    if not initial_conditions_path.exists():
                        raise FileNotFoundError(
                            f"Initial conditions file does not exist: {initial_conditions_path}"
                        )
                    profile_json_path = inputs_path / f"{profile_name}.json"
                    if not profile_json_path.exists():
                        raise FileNotFoundError(
                            f"Profile JSON file does not exist: {profile_json_path}"
                        )

                if not outputs_path.exists():
                    outputs_path.mkdir(parents=True, exist_ok=True)

                platform_info = PlatformInfo(
                    name=platform_name,
                    inputs_path=inputs_path,
                    outputs_path=outputs_path,
                )
                platforms_info[platform_name] = platform_info

            self.__profiles_by_name[profile_name] = Profile(
                name=profile_name,
                platform_info=platforms_info,
            )
            self.__profiles_by_index.append(
                Profile(
                    name=profile_name,
                    platform_info=platforms_info,
                )
            )

    def get_profile_by_name(self, name: str) -> Profile:
        """Get a profile by its name."""
        return self.__profiles_by_name[name]

    def get_profile_by_index(self, index: int) -> Profile:
        """Get a profile by its index."""
        if index < 0 or index >= len(self.__profiles_by_index):
            raise IndexError("Profile index out of range.")
        return self.__profiles_by_index[index]
