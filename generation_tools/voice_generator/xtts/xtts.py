import torch
from TTS.api import TTS
from uuid import uuid4
import os
from loguru import logger
from shutil import rmtree

from generation_tools.voice_generator.denoising.denoiser import Denoiser
from generation_tools.voice_generator.xtts.constants import SAMPLE_VOICES, AVAILABLE_SPEAKERS
from generation_tools.subtitles_generator.whisper.whisper_stt import Whisper
from utils.utils import trim_silence_from_audio

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


    def generate_audio_cloning_voice_to_file(self, text: str, output_path: str,  language: str = 'en',
                                             speaker: str = 'random_girl',
                                             speed: float = 1.75, retries: int = 1, quality_threshold: float = 0.8,
                                             denoise: bool = False) -> str:

        assert isinstance(retries, int) and 0 <= retries <= 10, \
            "Retries must be an integer between 0 and 10"

        output_dir = os.path.dirname(output_path)
        assert os.path.isdir(output_dir), f"Output folder {output_dir} does not exist"
        if retries == 1:
            self._generate_audio_file(text=text, output_path=output_path, language=language,  speaker=speaker, speed=speed)
        else:
            temp_out_dir = f"{output_dir}/temp"
            os.makedirs(temp_out_dir, exist_ok=True)
            generated_files = {}
            for i in range(retries):
                temp_output_path = f"{temp_out_dir}/{uuid4()}.wav"
                self._generate_audio_file(text=text, output_path=temp_output_path, language=language, speaker=speaker, speed=speed)
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

    def _generate_audio_file(self, text: str, output_path: str, language: str, speaker: str, speed: float = 1.75):
        if speaker in AVAILABLE_SPEAKERS:
            speaker_name = speaker
            speaker_wav = None
        else:
            assert speaker in SAMPLE_VOICES, f"Speaker {speaker} is not available"
            speaker_name = None
            speaker_wav = SAMPLE_VOICES[speaker]

        ret = self.tts.tts_to_file(text=text,
                                   file_path=output_path,
                                   speaker_wav=speaker_wav,
                                   speaker=speaker_name,
                                   language=language,
                                   speed=speed,
                                   split_sentences=False)
        # Trim silences
        trim_silence_from_audio(input_file=output_path, output_file=output_path)

    def generate_audio_cloning_voice(self, text: str,  language: str = 'en', speaker_wav: str = SAMPLE_VOICES['random_girl'],
                                     speed: float = 1.75) -> list[float]:
        return self.tts.tts(text=text, speaker_wav=speaker_wav, language=language, speed=speed, split_sentences=False)


    def load_model(self):
        return TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=True).to(device)


if __name__ == '__main__':
    xtts = Xtts()
    for speaker in AVAILABLE_SPEAKERS:
        xtts._generate_audio_file(text="Ahora, hablemos de su reino: Helheim. Este es el lugar adonde van aquellos que no murieron en combate. Imagina un paisaje helado y árido, a veces considerado como un lugar de tristeza.",
                                  output_path=f"voice_test/{speaker}.wav", language='es', speaker=speaker)

    for speaker in AVAILABLE_SPEAKERS:
        xtts._generate_audio_file(text="Now, let's talk about your kingdom: Helheim. This is the place where those who did not die in combat go. Imagine an icy and barren landscape, sometimes considered a place of sadness.",
                                  output_path=f"voice_test_english/{speaker}.wav", language='en', speaker=speaker)