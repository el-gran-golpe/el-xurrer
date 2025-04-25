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
"""

from __future__ import annotations

import json
import uuid
import pathlib
import urllib.request
import urllib.parse
import websocket
import logging
from typing import Any, Dict

__all__ = ["generate_image"]


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


# ------------------ demo when run directly ----------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_image(
        server="127.0.0.1:8188",
        workflow_path="test_workflow.json",  # your JSON
        prompt_text="portrait of a neon cyber cat",
        seed=42,
        out_file="demo.png",
    )
