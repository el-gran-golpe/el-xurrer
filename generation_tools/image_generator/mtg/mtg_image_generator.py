from concurrent.futures import CancelledError
from io import BytesIO

import requests
from gradio_client import Client
from PIL import Image
import os
import re
from httpx import ReadTimeout, ConnectError, ReadError
from huggingface_hub.utils import RepositoryNotFoundError
from loguru import logger
from contextlib import nullcontext
from requests.exceptions import ConnectionError, ProxyError, ConnectTimeout
from httpx import (
    ConnectTimeout as httpxConnectTimeout,
    ProxyError as httpxProxyError,
    ConnectError as httpxConnectError,
    RemoteProtocolError as httpxRemoteProtocolError,
)
from gradio_client.exceptions import AppError

from proxy_spinner import ProxySpinner

from generation_tools.image_generator.flux.constants import (
    SPACE_IS_DOWN_ERRORS,
    ALTERNATIVE_FLUX_DEV_SPACE,
    QUOTA_EXCEEDED_ERRORS,
    ORIGINAL_FLUX_DEV_SPACE,
)
from utils.exceptions import WaitAndRetryError, HFSpaceIsDownError

# Switch the spaces to work with the alternative space first
ALTERNATIVE_FLUX_DEV_SPACE, ORIGINAL_FLUX_DEV_SPACE = (
    ORIGINAL_FLUX_DEV_SPACE,
    ALTERNATIVE_FLUX_DEV_SPACE,
)


class MTGImageGenerator:
    def __init__(
        self,
        default_h: int = 1080,
        default_w: int = 1920,
        min_vertical_padding: int = 100,
        min_horizontal_padding: int = 100,
    ):
        self.default_h = default_h
        self.default_w = default_w
        self.min_vertical_padding = min_vertical_padding
        self.min_horizontal_padding = min_horizontal_padding

    def generate_image(self, card_urls: list[str], output_path: str):
        if isinstance(card_urls, str):
            card_urls = [card_urls]
        assert len(card_urls) > 0, "No card URLs provided"
        assert len(card_urls) <= 3, "Too many card URLs provided"

        # Load card images
        card_images = []
        for card_url in card_urls:
            card_image = requests.get(card_url)
            img = Image.open(BytesIO(card_image.content)).convert("RGBA")
            card_images.append(img)

        # Background settings
        background_w, background_h = self.default_w, self.default_h
        min_padding_vertical, min_padding_horizontal = (
            self.min_vertical_padding,
            self.min_horizontal_padding,
        )
        inter_card_padding = self.min_horizontal_padding
        background_color = (159, 172, 143, 255)  # Include alpha channel
        background = Image.new("RGBA", (background_w, background_h), background_color)

        # Calculate maximum card dimensions
        max_card_h = background_h - 2 * min_padding_vertical
        n = len(card_images)
        max_total_card_w = (
            background_w - 2 * min_padding_horizontal - (n - 1) * inter_card_padding
        )

        # Original card size
        original_card_w, original_card_h = card_images[0].size

        # Scaling factors to maintain aspect ratio and fit within dimensions
        scale_h = max_card_h / original_card_h
        scale_w = max_total_card_w / (n * original_card_w)
        scaling_factor = min(scale_h, scale_w)

        # Resize card images
        card_w = int(original_card_w * scaling_factor)
        card_h = int(original_card_h * scaling_factor)
        card_images = [
            card.resize((card_w, card_h), Image.LANCZOS) for card in card_images
        ]

        # Calculate starting x position for centering
        total_cards_width = n * card_w + (n - 1) * inter_card_padding
        start_x = (background_w - total_cards_width) // 2

        # Center cards vertically
        y_position = int((background_h - card_h) / 2)

        # Paste cards onto the background with inter-card padding
        for i, card_image in enumerate(card_images):
            x_position = start_x + i * (card_w + inter_card_padding)
            background.paste(card_image, (x_position, y_position), mask=card_image)

        # Save the final image
        background = background.convert("RGB")  # Convert back to 'RGB' if desired
        background.save(output_path)
        logger.info(f"Image saved: {output_path}")
