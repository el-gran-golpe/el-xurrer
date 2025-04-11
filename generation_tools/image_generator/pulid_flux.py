import shutil
from concurrent.futures import CancelledError
from typing import Optional

from gradio_client import Client
import os
import re
from httpx import ReadTimeout, ConnectError, ReadError
from huggingface_hub.utils import RepositoryNotFoundError
from contextlib import nullcontext
from requests.exceptions import ConnectionError, ProxyError, ConnectTimeout
from loguru import logger
from httpx import (
    ConnectTimeout as httpxConnectTimeout,
    ProxyError as httpxProxyError,
    ConnectError as httpxConnectError,
    RemoteProtocolError as httpxRemoteProtocolError,
)
from gradio_client.exceptions import AppError

from proxy_spinner import ProxySpinner

from generation_tools.image_generator.constants import (
    SPACE_IS_DOWN_ERRORS,
    QUOTA_EXCEEDED_ERRORS,
)
from utils.exceptions import WaitAndRetryError


class PulidFlux:
    def __init__(
        self,
        use_proxy: bool = True,
        load_on_demand: bool = False,
    ):
        self._src_model = "yanze/PuLID-FLUX"
        self._api_name = "/generate_image"

        if use_proxy:
            self.proxy = ProxySpinner(proxy=None)
        else:
            self.proxy = nullcontext()
            self.proxy.__setattr__("renew_proxy", lambda: None)

        if load_on_demand:
            self._client = None
        else:
            self._client = self.get_new_client(retries=1)

    @property
    def client(self):
        if self._client is None:
            self._client = self.get_new_client(retries=1)
        return self._client

    def get_new_client(self, retries: int = 3) -> Client:
        logger.info("Creating new gradio client")
        suggested_wait_time = None
        # Create a custom session with the proxy
        for retry in range(retries):
            try:
                with self.proxy:
                    client = Client(src=self._src_model)
                break
            except (
                ReadTimeout,
                ProxyError,
                ConnectionError,
                ConnectTimeout,
                httpxConnectTimeout,
                CancelledError,
                ReadError,
                httpxConnectError,
                httpxProxyError,
                RepositoryNotFoundError,
                httpxRemoteProtocolError,
            ) as e:
                reason = e.args[0] if hasattr(e, "args") and len(e.args) > 0 else None
                if reason in SPACE_IS_DOWN_ERRORS or isinstance(
                    e, RepositoryNotFoundError
                ):
                    logger.error(f"Space is down: {e}. Retry {retry + 1}/3")
                else:
                    logger.error(f"Error creating client: {e}. Retry {retry + 1}/3")
        else:
            raise WaitAndRetryError(
                message=f"Failed to create client after {retries} retries",
                suggested_wait_time=suggested_wait_time or 60 * 60,
            )
        return client

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        seed: Optional[int] = None,
        width: int = 512,
        height: int = 512,
        guidance_scale: float = 3.5,
        num_inference_steps: int = 25,
        retries: int = 3,
    ):
        assert 0 < width <= 2048, "Width must be between 0 and 2048"
        assert 0 < height <= 2048, "Height must be between 0 and 2048"
        assert 0 < guidance_scale <= 10, "Guidance scale must be between 0 and 10"
        assert 0 < num_inference_steps <= 100, (
            "Number of inference steps must be between 0 and 100"
        )
        assert 0 < retries <= 10, "Number of retries must be between 0 and 10"

        recommended_waiting_time_seconds, recommended_waiting_time_str = None, None

        randomize_seed: str = "-1" if seed is None else str(seed)

        for i in range(retries):
            try:
                with self.proxy:
                    image_path, seed, _ = self.client.predict(
                        prompt=prompt,
                        id_image="",
                        seed=randomize_seed,
                        width=width,
                        height=height,
                        guidance=guidance_scale,
                        num_steps=num_inference_steps,
                        api_name=self._api_name,
                    )
                    break
            except (
                AppError,
                ConnectionError,
                ConnectError,
                ConnectTimeout,
                httpxConnectTimeout,
                ReadTimeout,
                httpxProxyError,
                httpxConnectError,
                CancelledError,
                ReadError,
                httpxRemoteProtocolError,
            ) as e:
                error_message = (
                    e.args[0] if hasattr(e, "args") and len(e.args) > 0 else str(e)
                )
                # If the error is quota exceeded, get the waiting time and trigger a exception
                if any(
                    error_message.startswith(error) for error in QUOTA_EXCEEDED_ERRORS
                ):
                    logger.error(f"Quota exceeded: {e}. Retry {i + 1}/{retries}")
                    # Get the waiting time like 1:35:06 at the end of the message
                    waiting_time_re = re.search(r"\d+:\d+:\d+", error_message)
                    if waiting_time_re:
                        waiting_time = waiting_time_re.group()
                        hours, minutes, seconds = map(int, waiting_time.split(":"))
                        recommended_waiting_time_str = waiting_time
                        recommended_waiting_time_seconds = (
                            hours * 60 * 60 + minutes * 60 + seconds
                        )
                    else:
                        logger.warning(
                            f"Quota exceeded error message does not contain waiting time: {error_message}"
                        )
                else:
                    logger.error(
                        f"Error generating image: {e}. Retry {i + 1}/{retries}"
                    )

                if i == retries - 1:
                    if recommended_waiting_time_seconds is not None:
                        raise WaitAndRetryError(
                            message=f"Failed to generate image after {retries} retries. Wait for {recommended_waiting_time_str}",
                            suggested_wait_time=recommended_waiting_time_seconds
                            or 60 * 60,
                        )
                    else:
                        raise WaitAndRetryError(
                            message="Failed to generate image with unknown errors",
                            suggested_wait_time=60 * 60,
                        )

                # If the proxy is activated, renew the proxy
                elif isinstance(self.proxy, ProxySpinner):
                    # THOUGHTS: Maybe we have to put a loop to try to get a new client with a working proxy
                    while self.proxy.renew_proxy():
                        try:
                            self._client = self.get_new_client()
                            break
                        except Exception as e:
                            continue

        shutil.copy(image_path, output_path)

        # Remove the image from the original temporary folder
        os.remove(image_path)

        return True


if __name__ == "__main__":
    pulid_flux = PulidFlux()
    prompt = "A sexy blonde girl with blue eyes in Lyon showing a sex position and showing her pussy superrealistic"
    output_path = "./output.jpg"
    pulid_flux.generate_image(prompt, output_path, width=1080, height=1080)
    print(f"Image saved to {output_path}")
