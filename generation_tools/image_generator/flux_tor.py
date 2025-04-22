from __future__ import annotations

import os
import re
import shutil
import random
import time
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

from loguru import logger
from requests.exceptions import ConnectionError, ConnectTimeout, ProxyError
from stem import Signal
from stem.control import Controller
from dotenv import load_dotenv
import requests

load_dotenv()

# ---------------------------- CONFIG --------------------------------------- #

TOR_SOCKS_PORT = int(os.getenv("TOR_SOCKS_PORT", 9050))
TOR_CONTROL_PORT = int(os.getenv("TOR_CONTROL_PORT", 9051))
TOR_PASSWORD = os.getenv("TOR_CONTROL_PASSWORD")  # MUST be set

if TOR_PASSWORD is None:
    raise RuntimeError(
        "Set TOR_CONTROL_PASSWORD env‑var to the password configured in torrc"
    )

# Target Space (public)
# ORIGINAL_FLUX_DEV_SPACE = "black-forest-labs/FLUX.1-dev"
ORIGINAL_FLUX_DEV_SPACE = "black-forest-labs/FLUX.1-schnell"

# Default UA pool (basic)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]

# Customise if your Space uses other param names / ranges
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 512
DEFAULT_GUIDANCE = 7.5
DEFAULT_STEPS = 30

# ---------------------------- EXCEPTION GROUPS ----------------------------- #

CONNECTION_EXCEPTIONS = (
    ReadTimeout,
    ProxyError,
    ConnectionError,
    ConnectTimeout,
    httpxConnectTimeout,
    ReadError,
    httpxProxyError,
    httpxRemoteProtocolError,
)

# Quota‑exceeded and downtime signatures (fallback; keep small)
SPACE_IS_DOWN_ERRORS = [
    "The Space is too busy",
    "ServerError",
]

QUOTA_EXCEEDED_ERRORS = [
    "You have exceeded your quota",
    "429 Too Many Requests",
    "You have exceeded your GPU quota",
]


# ---------------------------- TOR UTILS ------------------------------------ #


def _renew_tor_ip(sleep_seconds: int = 5) -> None:
    """Send NEWNYM to Tor, wait a bit for the new circuit."""
    try:
        with Controller.from_port(port=TOR_CONTROL_PORT) as ctrl:
            ctrl.authenticate(password=TOR_PASSWORD)
            ctrl.signal(Signal.NEWNYM)
        time.sleep(sleep_seconds)
        logger.debug("Tor exit‑node rotated.")
    except Exception as e:
        logger.error(f"Failed to rotate Tor IP: {e}")


def _build_httpx_kwargs(user_agent: str) -> dict:
    return {
        "proxies": {
            "http://": f"socks5://127.0.0.1:{TOR_SOCKS_PORT}",
            "https://": f"socks5://127.0.0.1:{TOR_SOCKS_PORT}",
        },
        "timeout": 60,
    }


def get_current_ip() -> str:
    """Get the current public IP address through Tor."""
    proxies = {
        "http": f"socks5://127.0.0.1:{TOR_SOCKS_PORT}",
        "https": f"socks5://127.0.0.1:{TOR_SOCKS_PORT}",
    }
    try:
        ip = requests.get("https://api.ipify.org", proxies=proxies, timeout=10).text
        return ip
    except Exception as e:
        logger.error(f"Could not get current IP: {e}")
        return "unknown"


# ---------------------------- MAIN CLASS ----------------------------------- #


class FluxTor:
    """Gradio client for FLUX which rotates Tor IP before every call."""

    def __init__(
        self,
        src_model: str = ORIGINAL_FLUX_DEV_SPACE,
        api_name: str = "/infer",
        load_on_demand: bool = False,
    ) -> None:
        self._src_model = src_model
        self._api_name = api_name
        self._client: Optional[Client] = None if load_on_demand else self._new_client()

    # ---------------------------- INTERNALS ------------------------------ #

    def _new_client(self) -> Client:
        """Create a new Client wrapped in Tor."""
        ua = random.choice(USER_AGENTS)
        httpx_kwargs = _build_httpx_kwargs(ua)
        logger.debug(f"Creating client → UA: {ua}")
        return Client(src=self._src_model, httpx_kwargs=httpx_kwargs)

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = self._new_client()
        return self._client

    def _reset_client(self):
        self._client = self._new_client()

    # ---------------------------- PUBLIC API ----------------------------- #

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        guidance_scale: float = DEFAULT_GUIDANCE,
        num_inference_steps: int = DEFAULT_STEPS,
        backoff: tuple[int, int] = (1, 5),
    ) -> None:
        """
        Keep trying until an image is generated, rotating Tor IP on each attempt.
        Never raises WaitAndRetryError – it only returns when successful.
        """
        attempt = 1
        while True:
            _renew_tor_ip()
            ip = get_current_ip()
            print(f"[{attempt}] Rotated to Tor exit IP: {ip}")
            try:
                result = self.client.predict(
                    prompt,
                    width,
                    height,
                    guidance_scale,
                    num_inference_steps,
                    api_name=self._api_name,
                )
                # ----- save output exactly as before -----
                if isinstance(result, tuple):
                    image_path = result[0]
                else:
                    image_path = None

                if image_path and os.path.exists(image_path):
                    shutil.copy(image_path, output_path)
                    os.remove(image_path)
                else:
                    if hasattr(result, "save"):
                        result.save(output_path)
                    else:
                        with open(output_path, "wb") as f:
                            f.write(result)

                logger.info(f"[✓] Image saved to {output_path}")
                return  # ← SUCCESS!

            except (AppError, *CONNECTION_EXCEPTIONS) as e:
                error_msg = str(e)
                if any(msg in error_msg for msg in QUOTA_EXCEEDED_ERRORS):
                    logger.warning(
                        f"[{attempt}] GPU quota hit – rotating IP & retrying…"
                    )
                    # random back‑off inside the supplied window
                    wait = random.randint(*backoff)
                    time.sleep(wait)
                else:
                    logger.warning(f"[{attempt}] Other error: {error_msg}")
                    self._reset_client()
                    time.sleep(5)

            attempt += 1

    # ---------------------------- UTILITIES ------------------------------ #

    @staticmethod
    def _extract_wait_time(error_msg: str) -> Tuple[Optional[int], Optional[str]]:
        match = re.search(r"(\d{1,2}):(\d{1,2}):(\d{1,2})", error_msg)
        if not match:
            return None, None
        h, m, s = map(int, match.group().split(":"))
        seconds = h * 3600 + m * 60 + s
        return seconds, match.group()


# ---------------------------- CUSTOM ERROR ------------------------------- #


class WaitAndRetryError(RuntimeError):
    """Raised when the caller should wait then retry later."""

    def __init__(self, message: str, suggested_wait_time: int):
        super().__init__(message)
        self.suggested_wait_time = suggested_wait_time


# ---------------------------- CLI EXAMPLE ------------------------------- #

if __name__ == "__main__":
    flux = FluxTor()
    flux.generate_image(
        "Cyberpunk samurai portrait, hyper‑realistic, 8k",
        "./samurai.png",
        width=768,
        height=1024,
    )
