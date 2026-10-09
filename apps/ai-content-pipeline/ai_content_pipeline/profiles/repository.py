import re
import json
import shutil
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

# A planning week's key is either today's real format (an ISO date, the
# Monday it starts on, e.g. "2026-10-12") or the legacy literal the prompts
# used before this ("week_1" etc.) — both can still be on disk at once while
# a profile has plans from before and after the switch.
_DATED_WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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

    def get_week_plan(
        self, profile: Profile, platform: Platform, week: str | None = None
    ) -> WeekPlan: ...

    def save_week_plan(
        self, profile: Profile, platform: Platform, plan: WeekPlan
    ) -> None: ...

    def get_previous_week_plan(
        self, profile: Profile, platform: Platform, before: str
    ) -> WeekPlan | None: ...

    def get_persona(self, profile: Profile) -> str: ...


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

    def _history_dir(self, profile: Profile, platform: Platform) -> Path:
        return profile.platform_info[platform].outputs_path / "history"

    def _history_path(self, profile: Profile, platform: Platform, week: str) -> Path:
        return self._history_dir(profile, platform) / f"{week}_planning.json"

    def _read_week_plan(self, path: Path) -> WeekPlan:
        return WeekPlan.from_planning_dict(json.loads(path.read_text(encoding="utf-8")))

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

    def get_week_plan(
        self, profile: Profile, platform: Platform, week: str | None = None
    ) -> WeekPlan:
        """
        `week=None` (today's behaviour, used by the `all run_all`/`jobs run`
        current-week readers) returns whatever is current. With a week, the
        current plan is returned if it matches; otherwise the archived
        `history/{week}_planning.json`; otherwise `FileNotFoundError`, so a
        caller resuming a `plan` job for an already-archived week still finds
        it.
        """
        planning_path = self._planning_path(profile, platform)
        if week is None:
            return self._read_week_plan(planning_path)

        if planning_path.is_file():
            current = self._read_week_plan(planning_path)
            if current.week == week:
                return current

        history_path = self._history_path(profile, platform, week)
        if history_path.is_file():
            return self._read_week_plan(history_path)

        raise FileNotFoundError(
            f"No plan for week {week} ({profile.name}/{platform.value})"
        )

    def save_week_plan(
        self, profile: Profile, platform: Platform, plan: WeekPlan
    ) -> None:
        """
        `{initials}_planning.json` holds only the current week, same as
        before this plan — see `get_previous_week_plan` for why. If a
        different week was current, archive it to `outputs/history/` first —
        unless `plan.week` is *older* than the current week (see
        `_is_older_week`): writing an older week as "current" would demote
        the newer week that is already there, so instead `plan` is written
        straight into `outputs/history/` and current is left untouched. This
        matters for the `--weeks N` plan chain: if week k is (re-)planned
        after week k+1 already became current (e.g. a retry on a later run),
        week k must not displace it.
        """
        planning_path = self._planning_path(profile, platform)
        if planning_path.is_file():
            current = self._read_week_plan(planning_path)
            if current.week != plan.week:
                if self._is_older_week(plan.week, current.week):
                    logger.warning(
                        "Not overwriting current plan for {} {} (week {}) "
                        "with older week {}; saving it to history instead",
                        profile.name,
                        platform.value,
                        current.week,
                        plan.week,
                    )
                    self._write_to_history(profile, platform, plan)
                    return
                self._archive_current(profile, platform, current, planning_path)

        with open(planning_path, "w", encoding="utf-8") as f:
            json.dump(plan.to_planning_dict(), f, indent=4, ensure_ascii=False)

    @staticmethod
    def _is_older_week(candidate: str, current: str) -> bool:
        """
        True when `candidate` is strictly older than `current`. Dated (ISO)
        weeks compare lexicographically, which is also chronological. A
        legacy (non-dated) `candidate` is always older than a dated
        `current` — the legacy key predates the switch to real week dates.
        A legacy `current` is never treated as newer than anything (the
        normal archive-then-write path handles it, same as before dated
        weeks existed).
        """
        if not _DATED_WEEK_RE.match(current):
            return False
        if not _DATED_WEEK_RE.match(candidate):
            return True
        return candidate < current

    def _write_to_history(
        self, profile: Profile, platform: Platform, plan: WeekPlan
    ) -> None:
        history_dir = self._history_dir(profile, platform)
        history_dir.mkdir(parents=True, exist_ok=True)
        destination = self._history_path(profile, platform, plan.week)
        if destination.exists():
            logger.warning(
                "Overwriting existing history plan at {} for {} {}",
                destination,
                profile.name,
                platform.value,
            )
        with open(destination, "w", encoding="utf-8") as f:
            json.dump(plan.to_planning_dict(), f, indent=4, ensure_ascii=False)

    def _archive_current(
        self, profile: Profile, platform: Platform, current: WeekPlan, path: Path
    ) -> None:
        history_dir = self._history_dir(profile, platform)
        history_dir.mkdir(parents=True, exist_ok=True)
        destination = self._history_path(profile, platform, current.week)
        if destination.exists():
            logger.warning(
                "Overwriting existing history plan at {} for {} {}",
                destination,
                profile.name,
                platform.value,
            )
            destination.unlink()
        shutil.move(str(path), str(destination))

    def get_previous_week_plan(
        self, profile: Profile, platform: Platform, before: str
    ) -> WeekPlan | None:
        """
        Among the current plan and every archived history plan for this
        platform, the latest ISO-dated week strictly before `before`. With no
        dated plan (a profile still on the legacy `"week_1"` key, or no
        history yet), falls back to the latest non-dated legacy plan by file
        mtime. `None` when there are no plans at all.

        Platform-own only: Meta reads Meta's previous week, Fanvue reads
        Fanvue's. Cross-platform continuity is the future "chapter" command's
        job, not this one's.
        """
        candidates: list[tuple[Path, WeekPlan]] = []

        planning_path = self._planning_path(profile, platform)
        if planning_path.is_file():
            candidates.append((planning_path, self._read_week_plan(planning_path)))

        history_dir = self._history_dir(profile, platform)
        if history_dir.is_dir():
            for path in history_dir.glob("*_planning.json"):
                try:
                    candidates.append((path, self._read_week_plan(path)))
                except (json.JSONDecodeError, ValidationError, ValueError) as e:
                    logger.warning("Skipping unreadable history plan {}: {}", path, e)

        if not candidates:
            return None

        dated = [
            (path, plan)
            for path, plan in candidates
            if _DATED_WEEK_RE.match(plan.week) and plan.week < before
        ]
        if dated:
            return max(dated, key=lambda item: item[1].week)[1]

        legacy = [
            (path, plan)
            for path, plan in candidates
            if not _DATED_WEEK_RE.match(plan.week)
        ]
        if legacy:
            return max(legacy, key=lambda item: item[0].stat().st_mtime)[1]

        return None

    # --- Shared by both platforms: who she is ---
    #
    # Hangs off the profile root, not off `PlatformInfo`, so Meta and Fanvue
    # read the same file. A profile not yet migrated has no persona.md and
    # reads as empty rather than failing to load.

    def _persona_path(self, profile: Profile) -> Path:
        return self.resource_path / profile.name / "persona.md"

    def get_persona(self, profile: Profile) -> str:
        path = self._persona_path(profile)
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
