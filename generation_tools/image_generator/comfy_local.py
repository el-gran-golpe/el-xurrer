"""A very small WebSocket helper to send a *workflow JSON* to ComfyUI,
wait until execution finishes, then save the first resulting image.

Follows official example semantics (queue_prompt + /view).

Usage
-----
from comfylocal_ws_simple import generate_image

generate_image(
    server="127.0.0.1:8188",
    workflow_path="workflow.json",   # the JSON you exported
    prompt_text="a cute cat in space",  # replaces text in first CLIPTextEncode
    seed=123,
    out_file="cat.png",
)

Or use the class-based interface:

from comfy_local import ComfyLocal

comfy = ComfyLocal(server="127.0.0.1:8188", workflow_path="workflow.json")
comfy.generate_image(
    prompt="a cute cat in space",
    output_path="cat.png",
    seed=123
)
"""

from __future__ import annotations

import json
import uuid
import pathlib
import urllib.request
import urllib.parse
import websocket
import logging
from contextlib import nullcontext
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from utils.exceptions import WaitAndRetryError

__all__ = ["generate_image", "ComfyLocal"]


# ---------------------------------------------------------------------------
# tiny HTTP helpers (urllib so we avoid extra deps)
# ---------------------------------------------------------------------------


def _http_post_json(url: str, payload: dict[str, Any]):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _http_get_json(url: str):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _http_get_bytes(url: str):
    with urllib.request.urlopen(url) as r:
        return r.read()


# ---------------------------------------------------------------------------
# public convenience
# ---------------------------------------------------------------------------


def generate_image(
    server: str,
    workflow_path: str,
    prompt_text: str,
    seed: int,
    out_file: str,
) -> None:
    """Send *one* generation job and save the first PNG/JPG it produces."""

    # 1. load and patch workflow dict ------------------------------------------------
    workflow: Dict[str, Any] = json.loads(pathlib.Path(workflow_path).read_text())

    # naive: use first CLIPTextEncode + first KSampler we find
    for node in workflow.values():
        if node.get("class_type") == "CLIPTextEncode":
            # THOUGHTS: In some models we have to take into account the negative prompt
            node["inputs"]["text"] = prompt_text
            break
    for node in workflow.values():
        if node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = seed
            break

    # 2. open websocket -------------------------------------------------------------
    client_id = str(uuid.uuid4())
    ws = websocket.WebSocket()
    ws.connect(f"ws://{server}/ws?clientId={client_id}")

    # 3. queue prompt via HTTP ------------------------------------------------------
    prompt_payload = {"prompt": workflow, "client_id": client_id}
    rsp = _http_post_json(f"http://{server}/prompt", prompt_payload)
    prompt_id = rsp["prompt_id"]

    # 4. wait for execution done ----------------------------------------------------
    while True:
        msg_raw = ws.recv()
        if isinstance(msg_raw, bytes):  # previews we ignore
            continue
        msg = json.loads(msg_raw)
        if msg.get("type") == "executing":
            data = msg["data"]
            if data["node"] is None and data["prompt_id"] == prompt_id:
                break  # generation finished

    ws.close()

    # 5. fetch history + download first image ---------------------------------------
    hist = _http_get_json(f"http://{server}/history/{prompt_id}")[prompt_id]
    # find first image descriptor
    img_info = next(iter(hist["outputs"].values()))["images"][0]
    img_bytes = _http_get_bytes(
        f"http://{server}/view?{urllib.parse.urlencode(img_info)}"
    )

    pathlib.Path(out_file).write_bytes(img_bytes)
    logging.info("Image saved → %s", out_file)


# ---------------------------------------------------------------------------
# Class-based interface that follows the Flux API
# ---------------------------------------------------------------------------


class ComfyLocal:
    """Client for the ComfyUI local image generation with Flux-compatible interface."""

    def __init__(
        self,
        server: str = "127.0.0.1:8188",
        workflow_path: str = r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\generation_tools\image_generator\test_workflow.json",
        use_proxy: bool = False,
        api_name: str = "",  # Not used, for compatibility with Flux
        load_on_demand: bool = False,  # Not used, for compatibility with Flux
    ):
        """Initialize ComfyLocal client."""
        self._server = server
        self._workflow_path = workflow_path

        # These are for compatibility with Flux interface but not used
        self.proxy = nullcontext()
        if not use_proxy:
            self.proxy.__setattr__("renew_proxy", lambda **kwargs: None)

    def get_new_client(self, retries: int = 3):
        """
        Compatibility method with Flux interface.
        ComfyLocal doesn't use a client object, so this is a no-op.
        """
        return None

    @property
    def client(self):
        """
        Lazy-loaded client getter for compatibility with Flux interface.
        ComfyLocal doesn't use a client object, so this returns None.
        """
        return None

    def _extract_wait_time(self, error_msg: str) -> Tuple[Optional[int], Optional[str]]:
        """
        Extract waiting time from error message.
        This is for compatibility with Flux interface.

        Returns:
            Tuple of (wait time in seconds, formatted time string)
        """
        import re

        match = re.search(r"\d+:\d+:\d+", error_msg)
        if not match:
            return None, None

        time_str = match.group()
        hours, minutes, seconds = map(int, time_str.split(":"))
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds, time_str

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        seed: Optional[int] = None,
        width: int = 512,  # Not used in ComfyLocal, for compatibility with Flux
        height: int = 512,  # Not used in ComfyLocal, for compatibility with Flux
        guidance_scale: float = 3.5,  # Not used in ComfyLocal, for compatibility with Flux
        num_inference_steps: int = 25,  # Not used in ComfyLocal, for compatibility with Flux
        retries: int = 3,
    ) -> bool:
        """Generate an image using ComfyUI local server."""
        # Validate parameters
        assert prompt, "Prompt must not be empty"
        assert output_path, "Output path must not be empty"
        assert 0 < retries <= 10, "Number of retries must be between 0 and 10"

        # Use seed if provided, otherwise use 0 (ComfyUI will randomize)
        actual_seed = seed if seed is not None else 0

        for attempt in range(retries):
            try:
                with self.proxy:  # For compatibility with Flux interface
                    # Use the functional implementation
                    generate_image(
                        server=self._server,
                        workflow_path=self._workflow_path,
                        prompt_text=prompt,
                        seed=actual_seed,
                        out_file=output_path,
                    )
                    return True

            except Exception as e:
                # Check for specific error types (for compatibility with Flux interface)
                wait_time_seconds, wait_time_str = None, None

                # Log the error
                logger.error(
                    f"Error generating image: {e}. Retry {attempt + 1}/{retries}"
                )

                # Handle last retry failure
                if attempt == retries - 1:
                    message = f"Failed to generate image after {retries} retries"
                    if wait_time_str:
                        message += f". Wait for {wait_time_str}"
                    raise WaitAndRetryError(
                        message=message,
                        suggested_wait_time=wait_time_seconds
                        or 60 * 60,  # Default 1 hour wait
                    )

        return True


# ------------------ demo when run directly ----------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Test the functional interface
    generate_image(
        server="127.0.0.1:8188",
        workflow_path="c:/Users/Usuario/source/repos/Shared with Haru/el-xurrer/generation_tools/image_generator/test_workflow.json",  # your JSON
        prompt_text="Laura Vigne is a captivating 22-year-old AI influencer with fair, luminous skin, striking blue almond-shaped eyes, high cheekbones, a delicate nose, and full pink lips. Her soft, wavy blonde hair frames her refined features, giving her a timeless and approachable charm. A close-up shot of Siena’s hands coding furiously on a neon-backlit keyboard. Bright green lines of code blur on the monitor in the foreground, a jumble of text that hints at something overwhelming but vital. The soft clinking of keys contrasts sharply with the palpable tension surrounding her.",
        seed=443,
        out_file="demo.png",
    )

    # Test the class-based interface
    comfy = ComfyLocal(server="127.0.0.1:8188", workflow_path="test_workflow.json")
    comfy.generate_image(
        prompt="portrait of a neon cyber cat with Flux interface",
        output_path="demo_class.png",
        seed=42,
    )
