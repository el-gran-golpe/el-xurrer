import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Type, Union, cast

from automation.fanvue_client.fanvue_api_publisher import FanvueAPIPublisher
from automation.meta_api.graph_api import MetaPublisher

from loguru import logger
from pydantic import BaseModel, ConfigDict, field_validator, ValidationError

from main_components.common.types import Platform, Profile


class Publication(BaseModel):
    """
    Pydantic model representing a single publication.
    """

    day_folder: Path
    caption_text: str
    upload_time: datetime
    image_paths: List[Path]

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("caption_text", mode="before")
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
    Yield day folders sorted by week then day, validating folder names.
    """
    week_pattern = re.compile(r"^week_\d+$")
    day_pattern = re.compile(r"^day_\d+$")

    for week_folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if not week_pattern.match(week_folder.name):
            raise ValueError(f"Invalid week folder name: {week_folder.name}")
        for day_folder in sorted(p for p in week_folder.iterdir() if p.is_dir()):
            if not day_pattern.match(day_folder.name):
                raise ValueError(
                    f"Invalid day folder name: {day_folder.name} in {week_folder.name}"
                )
            yield day_folder


class PostingScheduler:
    def __init__(
        self,
        template_profiles: List[Profile],
        platform_name: Platform,
        publisher: Union[Type[MetaPublisher], Type[FanvueAPIPublisher]],
    ):
        self.platform_name = platform_name
        self.platform_name = platform_name
        self.template_profiles = template_profiles
        self.publisher = publisher

    async def upload(self) -> None:
        for profile in self.template_profiles:
            outputs = profile.platform_info[self.platform_name].outputs_path

            pub_root = Path(outputs) / "publications"
            # TODO: should be this included in the Profile class?
            if not pub_root.exists():
                raise FileNotFoundError(f"No publications folder for {profile}")

            publications = []
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

                    image_paths: List[Path] = (
                        list(day_folder.glob("*.png"))
                        + list(day_folder.glob("*.jpg"))
                        + list(day_folder.glob("*.jpeg"))
                    )

                    # Let Pydantic handle all validation
                    publications.append(
                        Publication(
                            day_folder=day_folder,  # This Path variable is used for logging stuff in the terminal
                            caption_text=caption_text,
                            upload_time=upload_time,
                            image_paths=image_paths,
                        )
                    )
                except (FileNotFoundError, ValueError, ValidationError) as err:
                    logger.error(
                        f"Failed to create publication for {day_folder}: {err}"
                    )
                    continue

            if self.platform_name == Platform.FANVUE:
                try:
                    await self._upload_via_fanvue_api(
                        publications,
                        cast(Type[FanvueAPIPublisher], self.publisher),
                        profile,
                    )
                except Exception as e:
                    logger.error("Failed to upload via Fanvue API: {}", e)
            elif self.platform_name == Platform.META:
                await self._upload_via_api(
                    publications,
                    cast(Type[MetaPublisher], self.publisher),
                    profile,
                )
            else:
                raise NotImplementedError(f"Unsupported platform: {self.platform_name}")

    async def _upload_via_api(
        self,
        publications: list[Publication],
        client_class: Type[MetaPublisher],
        profile: Profile,
    ) -> None:
        """
        Uses Meta's graph API to upload publications.
        """
        client = client_class(profile)

        for pub in publications:
            logger.info(
                f"Uploading {pub.day_folder.name} via API on {self.platform_name}"
            )
            # We have to wait anyway since Instagram does not have a built-in api for scheduling
            await self._wait_for_time(pub.upload_time)

            try:
                meta_resp = await client.upload_publication(
                    pub.image_paths,
                    pub.caption_text,
                    pub.upload_time,
                )
                logger.debug(f"Meta response: {meta_resp}")

            except Exception as err:
                logger.error(f"API upload failed for {pub.day_folder}: {err}")

    async def _wait_for_time(self, scheduled: datetime) -> None:
        """
        Sleep until scheduled time.
        """
        now = datetime.now(scheduled.tzinfo)
        delay = (scheduled - now).total_seconds()

        if delay > 0:
            logger.info(
                f"[{self.platform_name}] Sleeping for {delay:.0f}s until {scheduled.isoformat()}"
            )
            await asyncio.sleep(delay)
        else:
            logger.info(
                f"[{self.platform_name}] Scheduled time has already passed. Continuing without sleep..."
            )

    async def _upload_via_fanvue_api(
        self,
        publications: list[Publication],
        client_class: Type[FanvueAPIPublisher],
        profile: Profile,
    ) -> None:
        """Upload via Fanvue OAuth API with multiple images as single carousel post."""

        # Create API client
        client = client_class(profile)

        for pub in publications:
            # Convert datetime to ISO 8601 string with 'Z' suffix (Fanvue requirement)
            # Fanvue API requires format: YYYY-MM-DDTHH:MM:SSZ
            utc_time = pub.upload_time.astimezone(timezone.utc)
            publish_at = utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            logger.info(
                f"Scheduling {pub.day_folder.name} via Fanvue API for {publish_at}"
            )

            try:
                # Run async batch upload in sync context with scheduled time
                await client.post_publication_batch(
                    pub.image_paths, pub.caption_text, publish_at
                )
            except Exception as err:
                logger.error(f"API upload failed for {pub.day_folder}: {err}")
