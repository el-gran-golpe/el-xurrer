import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from loguru import logger
from websocket import WebSocket


class HTTPClient:
    """Simple HTTP client for JSON and binary requests."""

    def __init__(self, timeout: int = 30) -> None:
        self.session = requests.Session()
        self.timeout = timeout

    def post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_json(self, url: str) -> Dict[str, Any]:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_bytes(self, url: str) -> bytes:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.content


class ComfyLocal:
    """Client for interacting with a local ComfyUI server to generate images."""

    def __init__(
        self,
        workflow_path: Path,
        server_host: str = "127.0.0.1",
        server_port: int = 8188,
        http_timeout: int = 30,
    ):
        self.server = f"{server_host}:{server_port}"
        self.workflow_path = workflow_path
        self.client = HTTPClient(timeout=http_timeout)
        logger.debug(
            f"Initialized ComfyLocal with server={self.server} and workflow={self.workflow_path}"
        )

    def check_connection(self, timeout: Optional[float] = None) -> None:
        """
        Try a simple GET against the ComfyUI server root to verify it’s up.
        Raises RuntimeError if the server cannot be reached or returns non‑2xx.
        """
        # Compose the health‑check URL (adjust if your server URL differs)
        url = f"http://{self.server}/"
        tm = timeout or self.client.timeout
        try:
            resp = self.client.session.get(url, timeout=tm)
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Cannot reach ComfyUI at {url!r}: {e}")

    def generate_image(
        self,
        prompt: str,
        output_path: Path,
        width: int = 512,
        height: int = 640,
        format: str = "jpeg",
        max_size: Optional[int] = None,  # TODO: make this happen
        seed: Optional[int] = None,
        timeout_in_seconds: int = 1000,
    ) -> bool:
        """Generate an image based on the provided prompt and save it to output_path."""
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("Prompt cannot be empty")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        seed = seed or uuid.uuid4().int & ((1 << 32) - 1)

        logger.debug(f"Generating image: prompt='{prompt[:50]}...', seed={seed}")
        prompt_id = self._enqueue_prompt(prompt, seed)
        ws_client = self._wait_for_completion(prompt_id, timeout_in_seconds)
        try:
            img_bytes = self._fetch_result(prompt_id)
            output_path.write_bytes(img_bytes)
            return True
        finally:
            ws_client.close()

    def _enqueue_prompt(self, prompt: str, seed: int) -> str:
        workflow = json.loads(self.workflow_path.read_text())

        # Patch workflow nodes
        for node in workflow.values():
            if node.get("class_type") == "CLIPTextEncode":
                # Here I pass my prompt to the image generation workflow
                node["inputs"]["text"] = prompt
            if node.get("class_type") == "KSampler":
                node["inputs"]["seed"] = seed

        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}
        url = f"http://{self.server}/prompt"
        response = self.client.post_json(url, payload)
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise RuntimeError("Failed to enqueue prompt; no prompt_id returned.")

        logger.debug(f"Enqueued prompt ID={prompt_id}")
        # Store client_id for websocket
        self._client_id = client_id
        return prompt_id

    def _wait_for_completion(self, prompt_id: str, timeout_in_seconds) -> WebSocket:
        ws = WebSocket()
        ws.connect(
            f"ws://{self.server}/ws?clientId={self._client_id}",
            timeout=timeout_in_seconds,
        )
        logger.debug("WebSocket connection opened.")

        while True:
            msg = ws.recv()
            if not isinstance(msg, str):
                continue

            data = json.loads(msg)
            if data.get("type") == "executing":
                info = data.get("data", {})
                if info.get("node") is None and info.get("prompt_id") == prompt_id:
                    logger.debug("Execution complete on server.")
                    break
        return ws

    def _fetch_result(self, prompt_id: str) -> bytes:
        # Retrieve history
        history_url = f"http://{self.server}/history/{prompt_id}"
        history = self.client.get_json(history_url)

        outputs = history.get(prompt_id, {}).get("outputs", {})
        if not outputs:
            raise RuntimeError("No outputs found in history.")

        img_info = next(iter(outputs.values()))["images"][0]
        params = {k: v for k, v in img_info.items()}

        view_url = f"http://{self.server}/view?{requests.compat.urlencode(params)}"
        return self.client.get_bytes(view_url)
