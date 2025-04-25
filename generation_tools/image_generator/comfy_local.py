import json
import uuid
import time
import shutil
import pathlib
import logging
import httpx


class ComfyLocal:
    """
    Drop-in replacement for the old Flux client.
    Talks to a local ComfyUI API-server running on the same machine.
    Designed so PublicationsGenerator.generate_images() keeps working.
    """

    def __init__(
        self,
        workflow_path: str = r"C:\Users\Usuario\source\repos\Shared with Haru\el-xurrer\generation_tools\image_generator\test_workflow.json",
        host: str = "http://127.0.0.1:8188",
        output_dir: str | pathlib.Path = "ComfyUI/output",
    ) -> None:
        self.host: str = host.rstrip("/")
        self.output_dir = pathlib.Path(output_dir)
        # load & cache base workflow once
        self.base_flow: dict = json.loads(pathlib.Path(workflow_path).read_text())

    # ------------------------------------------------------------------ utils
    def _inject_prompt_seed(self, prompt: str, seed: int | None):
        """Return a deep-copied workflow JSON with prompt + seed patched in."""
        flow = json.loads(json.dumps(self.base_flow))  # cheap deep-copy
        for node in flow["nodes"]:
            ctype = node.get("type")
            if ctype == "CLIPTextEncode":
                # positive prompt is id 6 in sample workflow, negative is id 33 (empty)
                # we patch every CLIPTextEncode for safety
                node["widgets_values"][0] = prompt
            elif ctype == "KSampler":
                # widgets_values: [seed, "randomize", steps, cfg, sampler_name, scheduler, denoise]
                if seed is not None:
                    node["widgets_values"][0] = seed
                else:
                    node["widgets_values"][1] = (
                        "randomize"  # keeps random seed behaviour
                    )
        return flow

    def _wait_for_job(self, job_id: str, timeout: int = 300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            r = httpx.get(f"{self.host}/history/{job_id}").json()
            if r and r[-1]["status"] == "completed":
                return r[-1]
            time.sleep(1)
        raise RuntimeError("Comfy job timeout")

    # ------------------------------------------------------------------ public
    def generate_image(
        self,
        prompt: str,
        output_path: str,
        seed: int | None = None,
        width: int = 0,
        height: int = 0,
        guidance_scale: float = 0.0,
        num_inference_steps: int = 0,
        retries: int = 1,
    ) -> bool:
        """Mimic Flux.generate_image() signature but ignore extra params."""
        for attempt in range(retries):
            job_id = uuid.uuid4().hex
            try:
                payload = {
                    "prompt": self._inject_prompt_seed(prompt, seed),
                    "id": job_id,
                }
                print("Payload to ComfyUI:")
                print(json.dumps(payload, indent=2))  # <-- Add this line
                httpx.post(
                    f"{self.host}/prompt", json=payload, timeout=None
                ).raise_for_status()
                info = self._wait_for_job(job_id)
                image_rel = info["outputs"][0]["filename"]  # first image
                src = self.output_dir / image_rel
                shutil.copy(src, output_path)
                logging.info("[ComfyLocal] saved %s", output_path)
                return True
            except Exception as e:
                logging.error("ComfyLocal attempt %s failed: %s", attempt + 1, e)
                time.sleep(2)
        return False


# quick CLI test -----------------------------------------------------------
if __name__ == "__main__":
    cl = ComfyLocal()
    cl.generate_image(
        prompt="highly detailed portrait of a cyberpunk woman",
        output_path="test.png",
        seed=42,
    )
