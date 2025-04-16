import os
import re
import shutil
from concurrent.futures import CancelledError
from contextlib import nullcontext
from typing import Optional, Tuple

from gradio_client import Client
from gradio_client.exceptions import AppError
from httpx import (
    ConnectTimeout as httpxConnectTimeout,
    ProxyError as httpxProxyError,
    ReadError,
    ReadTimeout,
    RemoteProtocolError as httpxRemoteProtocolError,
)
from huggingface_hub.utils import RepositoryNotFoundError
from loguru import logger
from requests.exceptions import ConnectionError, ConnectTimeout, ProxyError

from generation_tools.image_generator.constants import (
    SPACE_IS_DOWN_ERRORS,
    QUOTA_EXCEEDED_ERRORS,
)
from proxy_spinner import ProxySpinner
from utils.exceptions import WaitAndRetryError

ORIGINAL_FLUX_DEV_SPACE = "black-forest-labs/FLUX.1-dev"

# Group common exceptions for cleaner error handling
CONNECTION_EXCEPTIONS = (
    ReadTimeout,
    ProxyError,
    ConnectionError,
    ConnectTimeout,
    httpxConnectTimeout,
    CancelledError,
    ReadError,
    httpxProxyError,
    httpxRemoteProtocolError,
)


class Flux:
    """Client for the FLUX image generation API with proxy handling and retry logic."""

    def __init__(
        self,
        src_model: str = ORIGINAL_FLUX_DEV_SPACE,
        use_proxy: bool = True,
        api_name: str = "/infer",
        load_on_demand: bool = False,
    ):
        """Initialize Flux client."""
        self._src_model = src_model
        self._api_name = api_name

        # Setup proxy context
        self.proxy = ProxySpinner(proxy=None) if use_proxy else nullcontext()
        if not use_proxy:
            self.proxy.__setattr__("renew_proxy", lambda **kwargs: None)

        # Initialize client (lazily if requested)
        self._client = None if load_on_demand else self.get_new_client(retries=1)

    @property
    def client(self):
        """Lazy-loaded client getter."""
        if self._client is None:
            self._client = self.get_new_client(retries=1)
        return self._client

    def get_new_client(self, retries: int = 3):
        """Create a new client with retry logic."""
        for retry in range(retries):
            try:
                with self.proxy:
                    return Client(src=self._src_model)
            except CONNECTION_EXCEPTIONS as e:
                error_msg = str(e.args[0] if hasattr(e, "args") and e.args else e)

                # Handle special case: space is down
                if error_msg in SPACE_IS_DOWN_ERRORS or isinstance(
                    e, RepositoryNotFoundError
                ):
                    logger.error(
                        f"Error creating client: {e}. Space is down. Retry {retry + 1}/{retries}"
                    )
                    return self.get_new_client(retries=1)

                logger.error(f"Error creating client: {e}. Retry {retry + 1}/{retries}")
                self.proxy.renew_proxy()

        # All retries failed
        raise WaitAndRetryError(
            message=f"Failed to create client after {retries} retries",
            suggested_wait_time=60 * 60,  # Default 1 hour wait
        )

    def _extract_wait_time(self, error_msg: str) -> Tuple[Optional[int], Optional[str]]:
        """Extract waiting time from quota exceeded error message."""
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
        width: int = 512,
        height: int = 512,
        guidance_scale: float = 3.5,
        num_inference_steps: int = 25,
        retries: int = 3,
    ) -> bool:
        """Generate an image using FLUX."""
        # Validate parameters
        assert 0 < width <= 2048, "Width must be between 0 and 2048"
        assert 0 < height <= 2048, "Height must be between 0 and 2048"
        assert 0 < guidance_scale <= 10, "Guidance scale must be between 0 and 10"
        assert 0 < num_inference_steps <= 100, (
            "Number of inference steps must be between 0 and 100"
        )
        assert 0 < retries <= 10, "Number of retries must be between 0 and 10"

        wait_time_seconds, wait_time_str = None, None
        randomize_seed = seed is None

        for attempt in range(retries):
            try:
                with self.proxy:
                    image_path, seed = self.client.predict(
                        prompt=prompt,
                        seed=seed,
                        randomize_seed=randomize_seed,
                        width=width,
                        height=height,
                        guidance_scale=guidance_scale,
                        num_inference_steps=num_inference_steps,
                        api_name=self._api_name,
                    )
                    # Success - copy output and clean up
                    shutil.copy(image_path, output_path)
                    os.remove(image_path)
                    return True

            except (AppError, *CONNECTION_EXCEPTIONS) as e:
                error_msg = str(e.args[0] if hasattr(e, "args") and e.args else e)

                # Check if quota exceeded
                if any(error_msg.startswith(err) for err in QUOTA_EXCEEDED_ERRORS):
                    logger.error(f"Quota exceeded: {e}. Retry {attempt + 1}/{retries}")
                    wait_time_seconds, wait_time_str = self._extract_wait_time(
                        error_msg
                    )
                else:
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
                        suggested_wait_time=wait_time_seconds or 60 * 60,
                    )

                # For non-final retries, renew proxy and client
                if isinstance(self.proxy, ProxySpinner):
                    self.proxy.renew_proxy(verbose=True)
                    self._client = self.get_new_client(retries=1)
        return True


if __name__ == "__main__":
    flux = Flux(use_proxy=True)
    prompt = "A sexy blonde girl with blue eyes showing a sex position and showing her pussy superrealistic"
    output_path = "./output.jpg"
    flux.generate_image(prompt, output_path, width=1080, height=1080)
    print(f"Image saved to {output_path}")
