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
from httpx import ConnectTimeout as httpxConnectTimeout, ProxyError as httpxProxyError, \
				   ConnectError as httpxConnectError, RemoteProtocolError as httpxRemoteProtocolError
from gradio_client.exceptions import AppError

from proxy_spinner import ProxySpinner

from generation_tools.image_generator.flux.constants import SPACE_IS_DOWN_ERRORS, ALTERNATIVE_FLUX_DEV_SPACE, \
	QUOTA_EXCEEDED_ERRORS, ORIGINAL_FLUX_DEV_SPACE
from utils.exceptions import WaitAndRetryError, HFSpaceIsDownError

# Switch the spaces to work with the alternative space first
ALTERNATIVE_FLUX_DEV_SPACE, ORIGINAL_FLUX_DEV_SPACE = ORIGINAL_FLUX_DEV_SPACE, ALTERNATIVE_FLUX_DEV_SPACE
class MTGImageGenerator:
	def __init__(self, default_h: int = 1080, default_w: int = 1920,
				       default_card_h: int = 720):
		self.default_h = default_h
		self.default_w = default_w
		self.default_card_h = default_card_h


	def generate_image(self, card_urls: list[str], output_path: str, cols: int = 1, rows = 1):
		if isinstance(card_urls, str):
			card_urls = [card_urls]
		assert len(card_urls) > 0, "No card urls provided"
		assert len(card_urls) <= cols * rows, "Too many card urls provided"

		# Create the image
		card_images = []
		# The image will be a grid of cards with the same size
		card_h = self.default_card_h
		card_w = int(card_h * 0.7)
		for card_url in card_urls:
			# Download the image from URL
			card_image = requests.get(card_url)
			card_image.raise_for_status()
			card_image = Image.open(BytesIO(card_image.content))
			card_image = card_image.resize((card_w, card_h))
			card_images.append(card_image)

		# Create the grid
		grid_h = card_h * rows
		grid_w = card_w * cols
		grid = Image.new('RGB', (grid_w, grid_h))
		for i, card_image in enumerate(card_images):
			row = i // cols
			col = i % cols
			grid.paste(card_image, (col * card_w, row * card_h))
		grid.save(output_path)
		return output_path