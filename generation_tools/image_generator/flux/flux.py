from gradio_client import Client
from PIL import Image
import os

from httpx import ReadTimeout, ConnectError
from loguru import logger
import json
from requests.exceptions import ConnectionError, ProxyError, ConnectTimeout
from httpx import ConnectTimeout as httpxConnectTimeout
from gradio_client.exceptions import AppError

from proxy_spinner import ProxySpinner

class Flux:
	def __init__(self, src_model: str = "black-forest-labs/FLUX.1-dev", api_name: str = '/infer', load_on_demand: bool = False):
		self._src_model = src_model
		self._api_name = api_name
		self.proxy = ProxySpinner(proxy=None)
		if load_on_demand:
			self._client = None
		else:
			self._client = self.get_new_client()

	@property
	def client(self):
		if self._client is None:
			self._client = self.get_new_client()
		return self._client

	def get_new_client(self):
		self.__client_predictions = 0
		# Create a custom session with the proxy
		for retry in range(3):
			try:
				with self.proxy:
					client = Client(src=self._src_model)
				break
			except (ReadTimeout, ProxyError, ConnectionError, ConnectTimeout, httpxConnectTimeout) as e:
				logger.error(f"Error creating client: {e}. Retry {retry + 1}/3")
				self.proxy.renew_proxy()
				continue
		return client

	def generate_image(self, prompt, output_path: str, seed: int|None = None, width=512, height=512,
					   guidance_scale=3.5, num_inference_steps=20, retries: int = 5,
					   token_rotation: bool = True):

		assert isinstance(prompt, str), "Prompt must be a string"
		assert seed is None or isinstance(seed, int), "Seed must be an integer or None"
		assert 0 < width <= 2048, "Width must be between 0 and 2048"
		assert 0 < height <= 2048, "Height must be between 0 and 2048"
		assert 0 < guidance_scale <= 10, "Guidance scale must be between 0 and 10"
		assert 0 < num_inference_steps <= 100, "Number of inference steps must be between 0 and 100"

		assert 0 < retries <= 10, "Number of retries must be between 0 and 10"

		randomize_seed = seed is None

		for i in range(retries):
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
						api_name=self._api_name
					)
					break
			except (AppError, ConnectionError, ConnectError, ConnectTimeout, httpxConnectTimeout, ReadTimeout) as e:
				logger.error(f"Error generating image: {e}. Retry {i + 1}/{retries}")
				if i == retries - 1:
					raise e
				if token_rotation:
					self.proxy.renew_proxy()
					self._client = self.get_new_client()


		# Open the image from the temporary path
		image = Image.open(image_path)
		# Save the image to the specified output path
		image.save(output_path)
		# Remove the image from the original temporary folder
		os.remove(image_path)

		return True


if __name__ == '__main__':

	flux = Flux()
	prompt = "A girl pouring oil on her feet with colored nails. Erotic, sensual, and sexy."
	output_path = "./output.jpg"
	flux.generate_image(prompt, output_path)
	print(f"Image saved to {output_path}")
