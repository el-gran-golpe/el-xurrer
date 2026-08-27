import asyncio
from pathlib import Path
from typing import Protocol

from loguru import logger

from ai_content_pipeline.generation.publications_generator import ImageSpec
from ai_content_pipeline.integrations.comfyui.local import ComfyLocal

IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1080


class GenerationBackend(Protocol):
    """
    Where a single image is actually computed. The contract is only "when this
    returns, the file exists at `output_path`" — it says nothing about where
    the computation happened, so a future SlurmComfyBackend can run it on an
    HPC node and rsync the result back without the DAG noticing.
    """

    async def generate(self, spec: ImageSpec, output_path: Path) -> None: ...


class LocalComfyBackend:
    """
    Wraps the existing `ComfyLocal` client (same `settings.comfy_host`/
    `comfy_port` as `cli/commands/pipeline.py:generate`, so pointing those at
    another machine's GPU still works).

    `ComfyLocal.generate_image` is blocking (requests + websocket), so it runs
    in a worker thread: blocking the event loop here would stall the `plan` and
    `schedule` queues too, which is exactly the head-of-line blocking the
    per-type Queue exists to avoid.
    """

    def __init__(self, comfy: ComfyLocal):
        self._comfy = comfy

    async def generate(self, spec: ImageSpec, output_path: Path) -> None:
        logger.info("Generating image '{}'", output_path.name)
        success = await asyncio.to_thread(
            self._comfy.generate_image,
            prompt=spec.description,
            output_path=output_path,
            width=IMAGE_WIDTH,
            height=IMAGE_HEIGHT,
        )
        if not success or not output_path.exists():
            raise RuntimeError(f"Image generation failed for '{output_path}'")
