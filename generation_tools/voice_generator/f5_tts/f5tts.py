from concurrent.futures import CancelledError
from gradio_client import Client, handle_file
import os
from shutil import copyfile
from httpx import ReadTimeout, ConnectError, ReadError
from loguru import logger
from contextlib import nullcontext
from requests.exceptions import ConnectionError, ProxyError, ConnectTimeout
from httpx import (
    ConnectTimeout as httpxConnectTimeout,
    ProxyError as httpxProxyError,
    ConnectError as httpxConnectError,
    RemoteProtocolError,
)
from gradio_client.exceptions import AppError

from proxy_spinner import ProxySpinner

from generation_tools.voice_generator.f5_tts.constants import (
    PERRO_SANXE,
    VOICE_SOURCES,
    AUDIO_PATH,
    AUDIO_TEXT,
    MISTERIOUS_VOICE,
    REQUIRES_SILENCE_REMOVAL,
)
from utils.exceptions import WaitAndRetryError


DEFAULT_VOICE = PERRO_SANXE

SRC_MODEL_BY_LANG = {"es": "jpgallegoar/Spanish-F5", "en": "mrfakename/E2-F5-TTS"}

API_NAME_BY_LANG = {"es": "/infer", "en": "/basic_tts"}


class F5TTS:
    def __init__(
        self, lang: str = "en", use_proxy: bool = True, load_on_demand: bool = False
    ):
        assert lang in SRC_MODEL_BY_LANG, (
            f"Language {lang} not found in the available languages."
        )
        self._lang = lang
        self._src_model = SRC_MODEL_BY_LANG[lang]
        self._api_name = API_NAME_BY_LANG[lang]
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
                RemoteProtocolError,
            ) as e:
                logger.error(f"Error creating client: {e}. Retry {retry + 1}/{retries}")
                self.proxy.renew_proxy()
        else:
            raise WaitAndRetryError(
                message=f"Failed to create client after {retries} retries",
                suggested_wait_time=60 * 60,
            )
        return client

    def generate_audio_to_file(
        self,
        text: str,
        output_path: str,
        voice: str = DEFAULT_VOICE,
        model: str = "F5-TTS",
        remove_silence: bool = None,
        cross_fade_duration: float = 0.15,
        speed: float = 1.0,
        retries: int = 3,
    ):
        assert voice in VOICE_SOURCES, (
            f"Voice {voice} not found in the available voices."
            f"Available voices {tuple(VOICE_SOURCES.keys())}"
        )
        ref_audio_orig_path = VOICE_SOURCES[voice][AUDIO_PATH]
        ref_text = VOICE_SOURCES[voice][AUDIO_TEXT]
        if remove_silence is None:
            remove_silence = VOICE_SOURCES[voice][REQUIRES_SILENCE_REMOVAL]

        assert os.path.exists(ref_audio_orig_path), (
            f"Reference audio file does not exist at {ref_audio_orig_path}"
        )
        assert isinstance(ref_text, str), "Reference text must be a string"
        assert isinstance(text, str), "Generated text must be a string"
        assert 0.1 <= cross_fade_duration <= 5.0, (
            "Cross fade duration must be between 0.1 and 5.0 seconds"
        )
        assert 0.5 <= speed <= 2.0, "Speed must be between 0.5 and 2.0"

        for i in range(retries):
            try:
                with self.proxy:
                    if self._lang == "es":
                        result = self.client.predict(
                            ref_audio_orig=handle_file(ref_audio_orig_path),
                            ref_text=ref_text,
                            gen_text=text,
                            model=model,
                            remove_silence=remove_silence,
                            cross_fade_duration=cross_fade_duration,
                            speed=speed,
                            api_name=self._api_name,
                        )
                    elif self._lang == "en":
                        result = self.client.predict(
                            ref_audio_input=handle_file(ref_audio_orig_path),
                            ref_text_input=ref_text,
                            gen_text_input=text,
                            remove_silence=remove_silence,
                            cross_fade_duration_slider=cross_fade_duration,
                            nfe_slider=32,
                            speed_slider=speed,
                            api_name=self._api_name,
                        )
                    else:
                        raise ValueError(f"Language {self._lang} not supported")
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
                RemoteProtocolError,
            ) as e:
                logger.error(f"Error generating audio: {e}. Retry {i + 1}/{retries}")

                if i == retries - 1:
                    raise WaitAndRetryError(
                        message=f"Failed to generate audio after {retries} retries",
                        suggested_wait_time=60 * 60,
                    )

                if isinstance(self.proxy, ProxySpinner):
                    self.proxy.renew_proxy()
                    self._client = self.get_new_client(retries=1)

        # Extract the WAV file path from the result
        wav_path = result[0]
        # Copy the WAV file to the specified output path
        copyfile(wav_path, output_path)

        return True


if __name__ == "__main__":
    f5tts = F5TTS()
    gen_text = (
        "Ojalá vivir en un mundo sembrado de Senpais fuertes y emprendedores como mi Yon Carlos. "
        "Mi senpai es tan fuerte que puede levantarme con un biceps, mientras con el otro "
        "saca la cartera para pagarme el Guchi."
    )

    output_path = "./output_audio.wav"
    f5tts.generate_audio_to_file(gen_text, output_path, voice=MISTERIOUS_VOICE)
    print(f"Audio saved to {output_path}")
