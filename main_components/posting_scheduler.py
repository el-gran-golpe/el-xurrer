from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Any, Iterator, List, Type, Union, cast
from automation.fanvue_client.fanvue_publisher import FanvuePublisher
from automation.meta_api.graph_api import GraphAPI
import shutil

from loguru import logger
from pydantic import BaseModel, ConfigDict, field_validator, ValidationError
from seleniumbase import SB

from main_components.base_main import BaseMain
from main_components.constants import Platform
from main_components.profile import Profile


class Publication(BaseModel):
    """
    Pydantic model representing a single publication.
    """

    day_folder: Path
    caption_text: str
    upload_time: datetime
    image_paths: List[Path]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("caption", mode="before")
    def _validate_caption(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError(f"caption must be a string, got {type(v)}")
        if not v.strip():
            raise ValueError("caption cannot be empty or whitespace only")
        return v.strip()

    @field_validator("upload_time", mode="after")
    def _parse_upload_time(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v
        raise ValueError(f"upload_time must be a datetime object, got {type(v)}")

    @field_validator("image_paths", mode="before")
    def validate_image_paths(cls, v: Any) -> List[Path]:
        if not isinstance(v, list) or not v:
            raise ValueError("image_paths must be a non-empty list")
        valid_exts = {".png", ".jpg", ".jpeg"}
        paths = []
        for p in v:
            path = Path(p)
            if not path.is_file():
                raise ValueError(f"{path} is not a file")
            if path.suffix.lower() not in valid_exts:
                raise ValueError(f"{path} does not have a valid image extension")
            paths.append(path)
        return paths


def _iter_day_folders(root: Path) -> Iterator[Path]:
    """
    Yield day folders sorted by week then day.
    """
    for week in sorted(p for p in root.iterdir() if p.is_dir()):
        for day in sorted(p for p in week.iterdir() if p.is_dir()):
            yield day


class PostingScheduler(BaseMain):
    def __init__(
        self,
        template_profiles: List[Profile],
        platform_name: Platform,
        # I pass the class itself and not an instance, since Fanvue needs a driver to be passed to it
        publisher: Union[Type[GraphAPI], Type[FanvuePublisher]],
    ):
        super().__init__(platform_name)
        self.platform_name = platform_name
        self.template_profiles = template_profiles
        self.publisher = publisher

    def upload(self) -> None:
        for profile in self.template_profiles:
            outputs = profile.platform_info[self.platform_name].outputs_path

            pub_root = Path(outputs) / "publications"
            if not pub_root.exists():
                raise FileNotFoundError(f"No publications folder for {profile}")

            # TODO: isn't it easier if you just iterate through week folders?
            for day_folder in _iter_day_folders(pub_root):
                try:
                    caption_text: str = (
                        (day_folder / "captions.txt")
                        .read_text(encoding="utf-8")
                        .strip()
                    )

                    upload_time: datetime = datetime.fromisoformat(
                        (day_folder / "upload_times.txt")
                        .read_text(encoding="utf-8")
                        .strip()
                        .replace("Z", "+00:00")
                    )

                    image_paths: List[Path] = list(day_folder.glob("*.[pj][pn]g"))

                    # Let Pydantic handle all validation
                    pub = Publication(
                        day_folder=day_folder,  # TODO: do I really need this day_folder?
                        caption_text=caption_text,
                        upload_time=upload_time,
                        image_paths=image_paths,
                    )

                    if self.platform_name == Platform.FANVUE:
                        self._upload_via_selenium(
                            pub, cast(Type[FanvuePublisher], self.publisher), profile
                        )
                    elif self.platform_name == Platform.META:
                        self._upload_via_api(pub, cast(Type[GraphAPI], self.publisher))
                    else:
                        raise NotImplementedError(
                            f"Unsupported platform: {self.platform_name}"
                        )

                    # TODO: uncomment when cleanup is needed (when finished the refactoring)
                    # self._cleanup(pub_root)

                except (FileNotFoundError, ValueError, ValidationError) as err:
                    logger.error(
                        f"Failed to create publication for {day_folder}: {err}"
                    )
                    continue

    def _upload_via_api(self, pub: Publication, client_class: Type[GraphAPI]) -> None:
        """
        Uses Meta's graph API to upload publications.
        """
        client = client_class()
        logger.info(f"Uploading {pub.day_folder.name} via API on {self.platform_name}")

        # self._wait_for_time(pub.upload_time)  # --> Meta's Graph API already has a built-in scheduling

        try:
            insta_resp = client.upload_instagram_publication(
                pub.image_paths, pub.caption_text, pub.upload_time
            )
            logger.debug(f"Instagram response: {insta_resp}")

            fb_resp = client.upload_facebook_publication(
                pub.image_paths, pub.caption_text, pub.upload_time
            )
            logger.debug(f"Facebook response: {fb_resp}")

        except Exception as err:
            logger.error(f"API upload failed for {pub.day_folder}: {err}")
            raise  # TODO: Should we raise in here?

    def _upload_via_selenium(
        self, pub: Publication, client_class: Type[FanvuePublisher], profile: Profile
    ) -> None:
        """
        Uses a custom SeleniumBase script to upload publications on Fanvue.
        """
        logger.info(
            f"Uploading {pub.day_folder.name} via Selenium on {self.platform_name}"
        )

        self._wait_for_time(pub.upload_time)

        with SB(uc=True, locale_code="en") as driver:
            client = client_class(driver)
            try:
                client.login(profile.name)
            except Exception as err:
                logger.error(f"Login failed for {profile}: {err}")
                raise

            for image_path in pub.image_paths:
                try:
                    client.post_publication(image_path, pub.caption_text)
                    logger.debug(f"Uploaded {image_path.name}")
                    sleep(5)  # TODO: remove this sleep in the future
                except Exception as err:
                    logger.error(f"Failed to upload {image_path.name}: {err}")
                    raise

    def _wait_for_time(self, scheduled: datetime) -> None:
        """
        Sleep until scheduled time.
        """
        now = datetime.now(scheduled.tzinfo)
        delay = (scheduled - now).total_seconds()

        if delay > 0:
            logger.info(
                f"[{self.platform_name}] Sleeping for {delay:.0f}s until {scheduled.isoformat()}"
            )
            sleep(delay)
        else:
            logger.info(
                f"[{self.platform_name}] Scheduled time has already passed. Continuing without sleep..."
            )

    def _cleanup(self, root: Path) -> None:
        """
        Remove publications directory after upload.
        """
        try:
            shutil.rmtree(root)
            logger.success(f"[{self.platform_name}] Cleaned up publications at {root}")
        except Exception as err:
            logger.error(f"[{self.platform_name}] Cleanup failed for {root}: {err}")
