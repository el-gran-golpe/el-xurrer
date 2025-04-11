from pathlib import Path

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
        """Load profiles from the base path."""
        if not self.resource_path.is_dir():
            raise FileNotFoundError(
                f"Resource path does not exist: {self.resource_path}"
            )

        for profile_dir in self.resource_path.iterdir():
            if not profile_dir.is_dir():
                continue

            profile_name = profile_dir.name
            # TODO: Check profile name is in snake case

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
                    # TODO: here the main_meta_typer.py fails because the folder fanvue
                    # does not have a an initial_conditions.md file. Does this make sense? Same with .json
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
