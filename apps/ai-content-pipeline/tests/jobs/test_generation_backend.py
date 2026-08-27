import asyncio
import threading
from pathlib import Path

import pytest

from ai_content_pipeline.generation.publications_generator import ImageSpec
from ai_content_pipeline.jobs.generation_backend import LocalComfyBackend


class FakeComfyLocal:
    """Stands in for ComfyLocal: records the call and writes the file."""

    def __init__(self, *, succeed: bool = True, write_file: bool = True) -> None:
        self.succeed = succeed
        self.write_file = write_file
        self.calls: list[dict] = []
        self.thread_name: str | None = None

    def generate_image(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        self.thread_name = threading.current_thread().name
        if self.write_file:
            kwargs["output_path"].write_bytes(b"jpeg")
        return self.succeed


@pytest.mark.asyncio
async def test_generate_delegates_to_comfy_with_the_current_dimensions(tmp_path: Path):
    comfy = FakeComfyLocal()
    output_path = tmp_path / "post_0.jpeg"

    await LocalComfyBackend(comfy).generate(ImageSpec("a cat", 0), output_path)

    assert comfy.calls == [
        {
            "prompt": "a cat",
            "output_path": output_path,
            "width": 1080,
            "height": 1080,
        }
    ]


@pytest.mark.asyncio
async def test_generate_runs_off_the_event_loop_thread(tmp_path: Path):
    comfy = FakeComfyLocal()

    await LocalComfyBackend(comfy).generate(
        ImageSpec("a cat", 0), tmp_path / "post_0.jpeg"
    )

    assert comfy.thread_name != threading.current_thread().name


@pytest.mark.asyncio
async def test_generate_raises_when_comfy_reports_failure(tmp_path: Path):
    comfy = FakeComfyLocal(succeed=False)

    with pytest.raises(RuntimeError):
        await LocalComfyBackend(comfy).generate(
            ImageSpec("a cat", 0), tmp_path / "post_0.jpeg"
        )


@pytest.mark.asyncio
async def test_generate_raises_when_no_file_was_written(tmp_path: Path):
    comfy = FakeComfyLocal(write_file=False)

    with pytest.raises(RuntimeError):
        await LocalComfyBackend(comfy).generate(
            ImageSpec("a cat", 0), tmp_path / "post_0.jpeg"
        )


@pytest.mark.asyncio
async def test_two_generates_overlap_because_neither_blocks_the_loop(tmp_path: Path):
    class SlowComfy(FakeComfyLocal):
        current = 0
        max_seen = 0

        def generate_image(self, **kwargs) -> bool:
            SlowComfy.current += 1
            SlowComfy.max_seen = max(SlowComfy.max_seen, SlowComfy.current)
            threading.Event().wait(0.05)
            SlowComfy.current -= 1
            return super().generate_image(**kwargs)

    backend = LocalComfyBackend(SlowComfy())
    await asyncio.gather(
        backend.generate(ImageSpec("a", 0), tmp_path / "a.jpeg"),
        backend.generate(ImageSpec("b", 1), tmp_path / "b.jpeg"),
    )

    assert SlowComfy.max_seen == 2
