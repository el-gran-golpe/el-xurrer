from pathlib import Path

from slugify import slugify
from tqdm import tqdm
from loguru import logger
from typing import List, Any
from dataclasses import dataclass

from ai_content_pipeline.integrations.comfyui.local import ComfyLocal
from ai_content_pipeline.domain.types import Platform
from ai_content_pipeline.domain.types import Profile
from ai_content_pipeline.domain.plans import DayPlan, WeekPlan
from ai_content_pipeline.paths import RESOURCES_DIR
from ai_content_pipeline.profiles.repository import (
    FilesystemProfileRepository,
    ProfileRepository,
)

# -- Data Models --------------------------------------------------------------


@dataclass(frozen=True)
class ImageSpec:
    description: str
    index: int


@dataclass(frozen=True)
class PublicationContent:
    title: str
    slug: str
    caption: str
    hashtags: list[str]
    upload_time: str
    images: list[ImageSpec]


# -- Directory Management -----------------------------------------------------


class DirectoryManager:
    """Handles creation of publication directory structure and files."""

    def __init__(self, base_path: Path):
        self.base_path = base_path

    def create_structure(self, plan: WeekPlan) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        week_folder = self.base_path / plan.week
        week_folder.mkdir(exist_ok=True)

        for day in plan.days:
            day_folder = week_folder / f"day_{day.day}"
            day_folder.mkdir(exist_ok=True)

            # Combine caption and hashtags into single text
            captions = []
            for post in day.posts:
                caption_text = post.caption.strip()
                if post.hashtags:
                    caption_text = f"{caption_text}\n{''.join(post.hashtags)}"
                captions.append(caption_text)
            (day_folder / "captions.txt").write_text(
                "\n\n".join(captions), encoding="utf-8"
            )

            upload_times = "\n".join(post.upload_time for post in day.posts)
            (day_folder / "upload_times.txt").write_text(upload_times, encoding="utf-8")


# -- Image Generation Service ------------------------------------------------


class ImageGeneratorService:
    def __init__(self, generator: ComfyLocal):
        self._generator = generator

    def generate_images(
        self,
        publications: list[PublicationContent],
        output_dir: Path,
    ) -> None:
        for pub in publications:
            for spec in pub.images:
                image_path = output_dir / f"{pub.slug}_{spec.index}.jpeg"
                if image_path.exists():
                    logger.info("Skipping existing image: {}", image_path)
                    continue
                logger.info("Generating image '{}'", image_path.name)
                success: bool = self._generator.generate_image(
                    prompt=spec.description,
                    output_path=image_path,
                )
                if not success or not image_path.exists():
                    raise RuntimeError(f"Image generation failed for '{image_path}'")

                rel_path = str(image_path).split("el-xurrer", 1)[-1]
                logger.success("Image saved at: el-xurrer{}", rel_path)


# -- Main Publications Generator ----------------------------------------------


def _parse_day(day: DayPlan) -> list[PublicationContent]:
    publications: List[PublicationContent] = []
    for post in day.posts:
        slug = slugify(post.title) if post.title else f"publication_{day.day}"
        images = [
            ImageSpec(image.image_description, idx)
            for idx, image in enumerate(post.images)
        ]
        publications.append(
            PublicationContent(
                title=post.title,
                slug=slug,
                caption=post.caption,
                hashtags=post.hashtags,
                upload_time=post.upload_time,
                images=images,
            )
        )
    return publications


class PublicationsGenerator:
    """Generates publications (directories, captions, images) from planning data."""

    def __init__(
        self,
        template_profiles: List[Profile],
        platform_name: Platform,
        image_generator_tool: Any,  # TODO: Should be a ComfyLocal instance
        repository: ProfileRepository | None = None,
    ):
        self.platform_name = platform_name
        self.template_profiles = template_profiles
        self.image_service = ImageGeneratorService(image_generator_tool)
        self.repository: ProfileRepository = repository or FilesystemProfileRepository(
            RESOURCES_DIR
        )

    def generate_publications_from_plan(
        self, plan: WeekPlan, output_folder: Path
    ) -> None:
        DirectoryManager(output_folder).create_structure(plan)

        week_folder = output_folder / plan.week
        for day in tqdm(plan.days, desc=f"Days in {plan.week}"):
            publications = _parse_day(day)
            if self.image_service and publications:
                self.image_service.generate_images(
                    publications, week_folder / f"day_{day.day}"
                )

    def generate(self) -> None:
        for profile in self.template_profiles:
            publications_folder = (
                Path(profile.platform_info[self.platform_name].outputs_path)
                / "publications"
            )
            self.generate_publications_from_plan(
                self.repository.get_week_plan(profile, self.platform_name),
                publications_folder,
            )
