import torch
from TTS.api import TTS
from uuid import uuid4
import os
from loguru import logger
from shutil import rmtree

from generation_tools.voice_generator.denoising.denoiser import Denoiser
from generation_tools.voice_generator.xtts.constants import (
    SAMPLE_VOICES,
    AVAILABLE_SPEAKERS,
    DECENT_SPEAKERS_ENGLISH,
)
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

    def generate_audio_to_file(
        self,
        text: str,
        output_path: str,
        language: str = "en",
        speaker: str = "Gitta Nikolina",
        speed: float = 1.75,
        retries: int = 1,
        quality_threshold: float = 0.8,
        denoise: bool = False,
    ) -> str:
        assert isinstance(retries, int) and 0 <= retries <= 10, (
            "Retries must be an integer between 0 and 10"
        )

        output_dir = os.path.dirname(output_path)
        assert os.path.isdir(output_dir), f"Output folder {output_dir} does not exist"
        if retries == 1:
            self._generate_audio_file(
                text=text,
                output_path=output_path,
                language=language,
                speaker=speaker,
                speed=speed,
            )
        else:
            temp_out_dir = f"{output_dir}/temp"
            os.makedirs(temp_out_dir, exist_ok=True)
            generated_files = {}
            for i in range(retries):
                temp_output_path = f"{temp_out_dir}/{uuid4()}.wav"
                self._generate_audio_file(
                    text=text,
                    output_path=temp_output_path,
                    language=language,
                    speaker=speaker,
                    speed=speed,
                )
                # Check if transcription sentences match with expected text
                quality = self.transcriber.check_audio_quality(
                    audio_path=temp_output_path, expected_text=text, language=language
                )
                generated_files[temp_output_path] = quality
                if quality > quality_threshold:
                    break
                else:
                    logger.warning(
                        f"Quality of generated audio is {quality:.2f}, retrying ({i + 1}/{retries})"
                    )

            best_file = max(generated_files, key=generated_files.get)
            os.rename(best_file, output_path)
            rmtree(temp_out_dir)

            if denoise:
                self.denoiser.denoise_audio(
                    audio_path=output_path, output_path=output_path
                )

        return True

    def _generate_audio_file(
        self,
        text: str,
        output_path: str,
        language: str,
        speaker: str,
        speed: float = 1.75,
    ):
        if speaker in AVAILABLE_SPEAKERS:
            speaker_name = speaker
            speaker_wav = None
        else:
            assert speaker in SAMPLE_VOICES, f"Speaker {speaker} is not available"
            speaker_name = None
            speaker_wav = SAMPLE_VOICES[speaker]

        self.tts.tts_to_file(
            text=text,
            file_path=output_path,
            speaker_wav=speaker_wav,
            speaker=speaker_name,
            language=language,
            speed=speed,
            split_sentences=len(text) > 220,
        )
        # Trim silences
        trim_silence_from_audio(input_file=output_path, output_file=output_path)

    def generate_audio_cloning_voice(
        self,
        text: str,
        language: str = "en",
        speaker_wav: str = SAMPLE_VOICES["random_girl"],
        speed: float = 1.75,
    ) -> list[float]:
        return self.tts.tts(
            text=text,
            speaker_wav=speaker_wav,
            language=language,
            speed=speed,
            split_sentences=False,
        )

    def load_model(self):
        return TTS(
            "tts_models/multilingual/multi-dataset/xtts_v2",
            progress_bar=True,
            gpu=device == "cuda",
        ).to(device)


if __name__ == "__main__":
    xtts = Xtts()

    for speaker in DECENT_SPEAKERS_ENGLISH:
        xtts._generate_audio_file(
            text="Thousands of years ago, in a Greece ruled by gods and monsters, a hero was born whose legend lives on to this day. Hercules, son of Zeus and a mortal, was destined for greatness from the moment he opened his eyes. But his path was not easy; his life was marked by tragedy and the fury of Hera, the queen of the gods.",
            output_path=f"voice_test_english/{speaker}_1.wav",
            language="en",
            speaker=speaker,
        )
        xtts._generate_audio_file(
            text="Hello, mythology lovers, welcome to a new journey through time! Today we will unravel the life of Hercules, that hero who not only lifted weights in the gym, but also faced monsters from another world.",
            output_path=f"voice_test_english/{speaker}_2.wav",
            language="en",
            speaker=speaker,
        )
        xtts._generate_audio_file(
            text="But, of course, in mythology nothing is easy and much less for Hercules, who had to face 12 challenging tasks that would test even the strongest.",
            output_path=f"voice_test_english/{speaker}_3.wav",
            language="en",
            speaker=speaker,
        )
