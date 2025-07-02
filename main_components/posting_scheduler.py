from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Iterator, List, Optional, Sequence, Type, Union
import shutil

from loguru import logger
from pydantic import BaseModel, ConfigDict, field_validator
from seleniumbase import SB

from main_components.base_main import BaseMain
from main_components.constants import Platform
from main_components.profile import Profile


class Publication(BaseModel):
    """
    Pydantic model representing a single publication.
    """

    day_folder: Path
    caption: str
    # Accept both datetime and raw string inputs for flexibility
    upload_time: Optional[Union[datetime, str]]
    images: List[Path]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("images", mode="before")
    def _sort_images(cls, v: Any) -> List[Path]:
        paths: Sequence[Path] = v if isinstance(v, Sequence) else []
        try:
            return sorted(paths)
        except Exception:
            return []

    @field_validator("upload_time", mode="before")
    def _parse_upload_time(cls, v: Any) -> Optional[datetime]:
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                logger.warning(f"Invalid datetime format: {v}")
                return None
        if isinstance(v, datetime):
            return v
        return None

    @property
    def is_valid(self) -> bool:
        return bool(self.caption and self.upload_time and self.images)


class PostingScheduler(BaseMain):
    def __init__(
        self,
        template_profiles: List[Profile],
        platform_name: Platform,
        publisher: Union[Any, Type[Any]],
    ):
        super().__init__(platform_name)
        self.platform_name: Platform = platform_name
        self.template_profiles: List[Profile] = template_profiles
        self.publisher: Union[Any, Type[Any]] = publisher  # TODO fix this type hint

    def upload(self) -> None:
        for profile in self.template_profiles:
            outputs = profile.platform_info[self.platform_name].outputs_path
            pub_root = Path(outputs) / "publications"
            # TODO: use pydantic here for validation
            if not pub_root.exists():
                logger.warning(f"No publications folder for {profile}")
                continue

            for day_folder in self._iter_day_folders(pub_root):
                caption_text = (
                    (day_folder / "captions.txt").read_text(encoding="utf-8").strip()
                    if (day_folder / "captions.txt").exists()
                    else ""
                )
                raw_time = (
                    (day_folder / "upload_times.txt")
                    .read_text(encoding="utf-8")
                    .strip()
                    if (day_folder / "upload_times.txt").exists()
                    else None
                )
                image_paths = list(day_folder.glob("*.[pj][pn]g"))

                pub = Publication(
                    day_folder=day_folder,
                    caption=caption_text,
                    upload_time=raw_time,
                    images=image_paths,
                )
                if not pub.is_valid:
                    logger.warning(f"Skipping incomplete data in {day_folder}")
                    continue

                if self.platform_name == Platform.FANVUE:
                    self._upload_via_selenium(pub, self.publisher, profile)
                elif self.platform_name == Platform.META:
                    self._upload_via_api(pub, self.publisher)
                else:
                    raise NotImplementedError(
                        f"Unsupported platform: {self.platform_name}"
                    )
            # TODO: uncomment when cleanup is needed (when finished the refactoring)
            # self._cleanup(pub_root)

    def _iter_day_folders(self, root: Path) -> Iterator[Path]:
        """
        Yield day folders sorted by week then day.
        """
        for week in sorted(p for p in root.iterdir() if p.is_dir()):
            for day in sorted(p for p in week.iterdir() if p.is_dir()):
                yield day

    def _upload_via_api(self, pub: Publication, client: Any) -> None:
        """
        Uses Meta's graph API to upload publications.
        """
        logger.info(f"Uploading {pub.day_folder.name} via API on {self.platform_name}")
        # TODO: check if the wait time is needed here
        self._wait_for_time(pub.upload_time)  # type: ignore[arg-type]
        try:
            insta_resp = client.upload_instagram_publication(
                pub.images, pub.caption, pub.upload_time
            )  # type: ignore[arg-type]
            logger.debug(f"Instagram response: {insta_resp}")
            fb_resp = client.upload_facebook_publication(
                pub.images, pub.caption, pub.upload_time
            )  # type: ignore[arg-type]
            logger.debug(f"Facebook response: {fb_resp}")
        except Exception as err:
            logger.error(f"API upload failed for {pub.day_folder}: {err}")
            # TODO: should we raise in here?
            raise

    def _upload_via_selenium(
        self, pub: Publication, publisher_cls: Type[Any], profile: Profile
    ) -> None:
        """
        Uses a custom SeleniumBase script to upload publications on Fanvue.
        """
        logger.info(
            f"Uploading {pub.day_folder.name} via Selenium on {self.platform_name}"
        )
        with SB(uc=True, test=True, locale_code="en") as driver:
            publisher = publisher_cls(driver)
            try:
                publisher.login(profile.name)
            except Exception as err:
                logger.error(f"Login failed for {profile}: {err}")
                raise

            for image in pub.images:
                try:
                    publisher.post_publication(str(image), pub.caption)
                    logger.debug(f"Uploaded {image.name}")
                    # TODO: remove this sleep in the future
                    sleep(5)
                except Exception as err:
                    logger.error(f"Failed to upload {image.name}: {err}")
                    raise

    def _wait_for_time(self, scheduled: Optional[Union[datetime, str]]) -> None:
        """
        Sleep until scheduled time if in the future.
        """
        if not scheduled:
            return
        scheduled_dt = (
            scheduled
            if isinstance(scheduled, datetime)
            else datetime.fromisoformat(scheduled)
        )  # type: ignore[arg-type]
        now = datetime.now(scheduled_dt.tzinfo)
        delay = (scheduled_dt - now).total_seconds()
        if delay > 0:
            logger.info(f"Sleeping for {delay:.0f}s until {scheduled_dt.isoformat()}")
            sleep(delay)

    def _cleanup(self, root: Path) -> None:
        """
        Remove publications directory after upload.
        """
        try:
            shutil.rmtree(root)
            logger.info(f"Cleaned up publications at {root}")
        except Exception as err:
            logger.error(f"Cleanup failed for {root}: {err}")
