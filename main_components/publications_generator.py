from pathlib import Path
import json

from slugify import slugify
from tqdm import tqdm
from loguru import logger
from typing import List, Any
from dataclasses import dataclass

from generation_tools.image_generator.comfy_local import ComfyLocal
from main_components.common.constants import Platform
from main_components.common.profile import Profile

# -- Data Models --------------------------------------------------------------


# TODO: Here maybe Moi knows how to use Pydantic models instead of dataclasses (ask him)
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

    def create_structure(self, planning: dict[str, list[dict[str, Any]]]) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        for week_key, days in planning.items():
            week_folder = self.base_path / week_key
            week_folder.mkdir(exist_ok=True)

            for day_data in days:
                day_folder = week_folder / f"day_{day_data['day']}"
                day_folder.mkdir(exist_ok=True)

                # Combine caption and hashtags into single text
                captions = []
                for post in day_data.get("posts", []):
                    caption_text = post.get("caption", "").strip()
                    hashtags = post.get("hashtags", [])
                    if hashtags:
                        caption_text = f"{caption_text}\n{' '.join(hashtags)}"
                    captions.append(caption_text)
                (day_folder / "captions.txt").write_text(
                    "\n\n".join(captions), encoding="utf-8"
                )

                upload_times = "\n".join(
                    post.get("upload_time", "") for post in day_data.get("posts", [])
                )
                (day_folder / "upload_times.txt").write_text(
                    upload_times, encoding="utf-8"
                )


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
                image_path = output_dir / f"{pub.slug}_{spec.index}.png"
                if image_path.exists():
                    logger.debug(f"Skipping existing image: {image_path}")
                    continue
                logger.info(f"Generating image '{image_path.name}'")
                success: bool = self._generator.generate_image(
                    prompt=spec.description,
                    output_path=image_path,
                    width=1080,
                    height=1080,
                )
                if not success or not image_path.exists():
                    raise RuntimeError(f"Image generation failed for '{image_path}'")

                rel_path = str(image_path).split("el-xurrer", 1)[-1]
                logger.success(f"Image saved at: el-xurrer{rel_path}")


# -- Main Publications Generator ----------------------------------------------


def _load_planning(planning_path: Path) -> dict[str, list[dict[str, Any]]]:
    with planning_path.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_day(day_data: dict[str, Any]) -> list[PublicationContent]:
    publications: List[PublicationContent] = []
    for post in day_data.get("posts", []):
        title = post.get("title", "")
        slug = slugify(title) if title else f"publication_{day_data.get('day')}"
        images = [
            ImageSpec(image.get("image_description", ""), idx)
            for idx, image in enumerate(post.get("images", []))
        ]
        publications.append(
            PublicationContent(
                title=title,
                slug=slug,
                caption=post.get("caption", ""),
                hashtags=post.get("hashtags", []),
                upload_time=post.get("upload_time", ""),
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
    ):
        self.platform_name = platform_name
        self.template_profiles = template_profiles
        self.image_service = ImageGeneratorService(image_generator_tool)

    def generate_publications_from_planning(
        self, profile_name: str, planning_file: Path, output_folder: Path
    ) -> None:
        planning = _load_planning(planning_file)

        publications_base_dir = output_folder
        DirectoryManager(publications_base_dir).create_structure(planning)

        for week, days in tqdm(planning.items(), desc="Weeks"):
            week_folder = publications_base_dir / week
            for day_data in tqdm(days, desc=f"Days in {week}"):
                day_folder = week_folder / f"day_{day_data['day']}"
                publications = _parse_day(day_data)
                if self.image_service and publications:
                    self.image_service.generate_images(publications, day_folder)

    def generate(self) -> None:
        for profile in self.template_profiles:
            initials = "".join(part[0] for part in profile.name.split("_"))
            planning_path = (
                Path(profile.platform_info[self.platform_name].outputs_path)
                / f"{initials}_planning.json"
            )
            publications_folder = (
                Path(profile.platform_info[self.platform_name].outputs_path)
                / "publications"
            )
            self.generate_publications_from_planning(
                profile.name,
                planning_path,
                publications_folder,
            )
