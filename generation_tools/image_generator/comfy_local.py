import json
import uuid
import pathlib
import urllib.request
import urllib.parse
import websocket
import random
from typing import Any, Dict, Optional
from loguru import logger


# -- HTTP Utilities -----------------------------------------------------------


def _http_post_json(
    url: str, payload: Dict[str, Any], timeout: int = 30
) -> Dict[str, Any]:
    """Send HTTP POST request with JSON payload."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get_json(url: str, timeout: int = 30) -> Dict[str, Any]:
    """Send HTTP GET request and return JSON response."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get_bytes(url: str, timeout: int = 60) -> bytes:
    """Send HTTP GET request and return raw bytes."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


# -- Class-based Interface ----------------------------------------------------


class ComfyLocal:
    """Class-based interface for ComfyUI local image generation."""

    def __init__(
        self, server: str = "127.0.0.1:8188", workflow_path: Optional[str] = None
    ) -> None:
        """Initialize ComfyLocal instance."""
        if not server or not server.strip():
            raise ValueError("Server address cannot be empty")

        self.server = server.strip()
        self.workflow_path = workflow_path

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        width: int = 1080,
        height: int = 1080,
        seed: Optional[int] = None,
    ) -> bool:
        """Generate image using ComfyUI."""
        try:
            if not prompt or not prompt.strip():
                logger.error("Prompt cannot be empty")
                return False

            if not output_path or not output_path.strip():
                logger.error("Output path cannot be empty")
                return False

            if seed is None:
                seed = random.randint(0, 2**32 - 1)

            # Create output directory if needed
            output_file = pathlib.Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            logger.info(f"Starting image generation for prompt: '{prompt[:50]}...'")

            # Use the functional interface
            _generate_image_internal(
                server=self.server,
                workflow_path=self.workflow_path,
                prompt_text=prompt.strip(),
                seed=seed,
                out_file=output_path,
            )

            # Verify file was created
            if not output_file.exists() or output_file.stat().st_size == 0:
                logger.error(f"Image generation failed: {output_path}")
                return False

            logger.success(f"Image generated successfully: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return False


# -- Functional Interface (your existing code, enhanced) ---------------------


def _generate_image_internal(
    server: str,
    workflow_path: Optional[str],
    prompt_text: str,
    seed: int,
    out_file: str,
) -> None:
    """Generate image using ComfyUI workflow."""

    if not workflow_path:
        raise ValueError("Workflow path is required")

    if not pathlib.Path(workflow_path).exists():
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")

    # Load and patch workflow
    workflow: Dict[str, Any] = json.loads(pathlib.Path(workflow_path).read_text())

    # Patch prompt and seed
    for node in workflow.values():
        if node.get("class_type") == "CLIPTextEncode":
            node["inputs"]["text"] = prompt_text
            break

    for node in workflow.values():
        if node.get("class_type") == "KSampler":
            node["inputs"]["seed"] = seed
            break

    # WebSocket connection
    client_id = str(uuid.uuid4())
    ws = websocket.WebSocket()

    try:
        ws.connect(f"ws://{server}/ws?clientId={client_id}", timeout=10)

        # Queue prompt
        prompt_payload = {"prompt": workflow, "client_id": client_id}
        response = _http_post_json(f"http://{server}/prompt", prompt_payload)
        prompt_id = response["prompt_id"]

        logger.info(f"Queued prompt with ID: {prompt_id}")

        # Wait for completion
        while True:
            msg_raw = ws.recv()
            if isinstance(msg_raw, bytes):
                continue

            msg = json.loads(msg_raw)
            if msg.get("type") == "executing":
                data = msg["data"]
                if data["node"] is None and data["prompt_id"] == prompt_id:
                    break

        # Get result
        history = _http_get_json(f"http://{server}/history/{prompt_id}")
        img_info = next(iter(history[prompt_id]["outputs"].values()))["images"][0]
        img_bytes = _http_get_bytes(
            f"http://{server}/view?{urllib.parse.urlencode(img_info)}"
        )

        # Save image
        output_path = pathlib.Path(out_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(img_bytes)

        logger.info(f"Image saved → {out_file} ({len(img_bytes)} bytes)")

    finally:
        try:
            ws.close()
        except Exception:
            pass
