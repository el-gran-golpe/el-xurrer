import torch
from TTS.api import TTS
from uuid import uuid4
import os
from loguru import logger
from shutil import rmtree

from generation_tools.voice_generator.denoising.denoiser import Denoiser
from generation_tools.voice_generator.xtts.constants import SAMPLE_VOICES
from generation_tools.subtitles_generator.whisper.whisper_stt import Whisper
# Get device
device = "cuda" if torch.cuda.is_available() else "cpu"

class Xtts:
    def __init__(self, load_on_demand: bool = False):
        if load_on_demand:
            self._tts = None
        else:
            self._tts = self.load_model()
        self.transcriber = Whisper(load_on_demand=True)
        self.denoiser = Denoiser()

    @property
    def tts(self):
        if self._tts is None:
            self._tts = self.load_model()
        return self._tts


    def generate_audio_cloning_voice_to_file(self, text: str, output_path: str,  language: str = 'en', speaker_wav: str = SAMPLE_VOICES['random_girl'],
                                             speed: float = 1.75, retries: int = 1, quality_threshold: float = 0.8,
                                             denoise: bool = False) -> str:

        assert isinstance(retries, int) and 0 <= retries <= 10, \
            "Retries must be an integer between 0 and 10"

        output_dir = os.path.dirname(output_path)
        assert os.path.isdir(output_dir), f"Output folder {output_dir} does not exist"
        if retries == 1:
            ret = self.tts.tts_to_file(text=text,
                                 file_path=output_path,
                                 speaker_wav=speaker_wav,
                                 language=language,
                                 speed=speed)
        else:
            temp_out_dir = f"{output_dir}/temp"
            os.makedirs(temp_out_dir, exist_ok=True)
            generated_files = {}
            for i in range(retries):
                temp_output_path = f"{temp_out_dir}/{uuid4()}.wav"
                ret = self.tts.tts_to_file(text=text,
                                     file_path=temp_output_path,
                                     speaker_wav=speaker_wav,
                                     language=language,
                                     speed=speed)
                # Check if transcription sentences match with expected text
                quality = self.transcriber.check_audio_quality(audio_path=temp_output_path, expected_text=text)
                generated_files[temp_output_path] = quality
                if quality > quality_threshold:
                    break
                else:
                    logger.warning(f"Quality of generated audio is {quality:.2f}, retrying ({i + 1}/{retries})")

            best_file = max(generated_files, key=generated_files.get)
            os.rename(best_file, output_path)
            rmtree(temp_out_dir)

            if denoise:
                self.denoiser.denoise_audio(audio_path=output_path, output_path=output_path)

        return True


    def generate_audio_cloning_voice(self, text: str,  language: str = 'en', speaker_wav: str = SAMPLE_VOICES['random_girl'],
                                     speed: float = 1.75) -> list[float]:
        return self.tts.tts(text=text, speaker_wav=speaker_wav, language=language, speed=speed)


    def load_model(self):
        return TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=True).to(device)


if __name__ == '__main__':
    xtts = Xtts()
    xtts.generate_audio_cloning_voice_to_file("Baldur es un dios de la mitologia griega que no tenía ni un pelo de tonto,"
                                              " listo, valiente ni cobarde, pues era mas calvo que un huevo frito",
                                              "./output-test-angry.wav", language='es', speaker_wav=SAMPLE_VOICES['random_girl'],
                                              emotion='angry', speed=1.75)
    print("done")