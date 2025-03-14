from concurrent.futures import CancelledError

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
#ALTERNATIVE_FLUX_DEV_SPACE, ORIGINAL_FLUX_DEV_SPACE = ORIGINAL_FLUX_DEV_SPACE, ALTERNATIVE_FLUX_DEV_SPACE
class Flux:
	def __init__(self, src_model: str = ORIGINAL_FLUX_DEV_SPACE, use_proxy: bool = True,
				 api_name: str = '/infer', load_on_demand: bool = False):
		self._src_model = src_model
		self._api_name = api_name
		if use_proxy:
			self.proxy = ProxySpinner(proxy=None)
		else:
			self.proxy = nullcontext()
			self.proxy.renew_proxy = lambda: None
		if load_on_demand:
			self._client = None
		else:
			self._client = self.get_new_client(retries=1)


	@property
	def client(self):
		if self._client is None:
			self._client = self.get_new_client(retries=1)
		return self._client

	def get_new_client(self, retries: int = 3):
		self.__client_predictions = 0
		suggested_wait_time = None
		# Create a custom session with the proxy
		for retry in range(retries):
			try:
				with self.proxy:
					client = Client(src=self._src_model)
				break
			except (ReadTimeout, ProxyError, ConnectionError, ConnectTimeout, httpxConnectTimeout, CancelledError,
					ReadError, httpxConnectError, httpxProxyError, RepositoryNotFoundError,
					httpxRemoteProtocolError) as e:
				reason = e.args[0] if hasattr(e, 'args') and len(e.args) > 0 else None
				if ((reason in SPACE_IS_DOWN_ERRORS or isinstance(e, RepositoryNotFoundError))
						and self._src_model != ALTERNATIVE_FLUX_DEV_SPACE):
					logger.error(f"Error creating client: {e}. Space is down. Retry {retry + 1}/3")
					self._src_model = ALTERNATIVE_FLUX_DEV_SPACE
					client = self.get_new_client(retries=1)
					break
				else:
					logger.error(f"Error creating client: {e}. Retry {retry + 1}/3")
					self.proxy.renew_proxy()
		else:
			raise WaitAndRetryError(message=f"Failed to create client after {retries} retries",
									suggested_wait_time=suggested_wait_time or 60*60)
		return client

	def generate_image(self, prompt, output_path: str, seed: int = None, width=512, height=512,
					   guidance_scale=3.5, num_inference_steps=25, retries: int = 3):

		assert isinstance(prompt, str), "Prompt must be a string"
		assert seed is None or isinstance(seed, int), "Seed must be an integer or None"
		assert 0 < width <= 2048, "Width must be between 0 and 2048"
		assert 0 < height <= 2048, "Height must be between 0 and 2048"
		assert 0 < guidance_scale <= 10, "Guidance scale must be between 0 and 10"
		assert 0 < num_inference_steps <= 100, "Number of inference steps must be between 0 and 100"
		assert 0 < retries <= 10, "Number of retries must be between 0 and 10"

		recommended_waiting_time_seconds, recommended_waiting_time_str = None, None

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
			except (AppError, ConnectionError, ConnectError, ConnectTimeout, httpxConnectTimeout, ReadTimeout,
					httpxProxyError, httpxConnectError, CancelledError, ReadError, httpxRemoteProtocolError) as e:

				error_message = e.args[0] if hasattr(e, 'args') and len(e.args) > 0 else str(e)
				# If the error is quota exceeded, get the waiting time and trigger a exception
				if any(error_message.startswith(error) for error in QUOTA_EXCEEDED_ERRORS):
					logger.error(f"Quota exceeded: {e}. Retry {i + 1}/{retries}")
					# Get the waiting time like 1:35:06 at the end of the message
					waiting_time = re.search(r'\d+:\d+:\d+', error_message)
					if waiting_time:
						waiting_time = waiting_time.group()
						hours, minutes, seconds = map(int, waiting_time.split(':'))
						recommended_waiting_time_str = waiting_time
						recommended_waiting_time_seconds = hours*60*60 + minutes*60 + seconds
					else:
						logger.warning(f"Quota exceeded error message does not contain waiting time: {error_message}")
				else:
					logger.error(f"Error generating image: {e}. Retry {i + 1}/{retries}")

				if i == retries - 1:
					if recommended_waiting_time_seconds is not None:
						raise WaitAndRetryError(message=f"Failed to generate image after {retries} retries. Wait for {recommended_waiting_time_str}",
												suggested_wait_time=recommended_waiting_time_seconds or 60*60)
					else:
						raise WaitAndRetryError(message=f"Failed to generate image with unknown errors",
												suggested_wait_time=60*60)

				# If the proxy is activated, renew the proxy
				elif isinstance(self.proxy, ProxySpinner):
					self.proxy.renew_proxy()
					self._client = self.get_new_client(retries=1)


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
	flux.generate_image(prompt, output_path, width=1080, height=1080)
	print(f"Image saved to {output_path}")
