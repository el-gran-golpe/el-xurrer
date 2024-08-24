
import requests
import os
from loguru import logger
import base64
class Denoiser:
    def __init__(self, api_url: str = "https://aleksasp-nvidia-denoiser.hf.space/run/predict"):
        self.api_url = api_url
        self.base_download_url = "https://aleksasp-nvidia-denoiser.hf.space/file="

    def denoise_audio(self, audio_path: str, output_path: str) -> bool:
        """Denoise the given audio file using the specified API and download the result."""

        # Check that the file exists and is a WAV file
        assert os.path.isfile(audio_path), "The specified audio file does not exist."
        assert audio_path.lower().endswith('.wav'), "The audio file must be a WAV file."

        # Read and encode the audio file in base64
        with open(audio_path, "rb") as audio_file:
            audio_data_base64 = base64.b64encode(audio_file.read()).decode('utf-8')

        # Prepare the payload
        payload = {
            "data": [
                {
                    "name": os.path.basename(audio_path),
                    "data": f"data:audio/wav;base64,{audio_data_base64}"
                }
            ]
        }

        # Send the request to the API
        try:
            response = requests.post(self.api_url, json=payload)
            response.raise_for_status()
            result = response.json()['data'][0]
            assert result.get("data") is None and result.get("is_file") and result.get("name"), "Unexpected response format."
            # Check if the response contains the file name

            file_name = result["name"]
            download_url = f"{self.base_download_url}{file_name}"

            # Download the file
            file_response = requests.get(download_url)
            file_response.raise_for_status()

            # Save the downloaded file to the specified output path
            with open(output_path, "wb") as output_file:
                output_file.write(file_response.content)

            logger.info(f"Denoised audio saved to {output_path}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Error during the request: {e}")
            return False
