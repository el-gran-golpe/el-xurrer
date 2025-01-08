import scipy
from diffusers import AudioLDM2Pipeline
import torch
import os
import numpy as np
from loguru import logger

class AudioLDM:
    def __init__(self, load_on_demand: bool = False):
        self.repo_id = 'cvssp/audioldm2-large'#"cvssp/audioldm2"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if load_on_demand:
            self._pipe = None
        else:
            self._pipe = self.load_model()

    def load_model(self):
        if self.device == "cuda":
            return AudioLDM2Pipeline.from_pretrained(self.repo_id, torch_dtype=torch.float16).to(self.device)
        else:
            return AudioLDM2Pipeline.from_pretrained(self.repo_id).to(self.device)

    @property
    def pipe(self):
        if self._pipe is None:
            self._pipe = self.load_model()
        return self._pipe

    def generate_audio(self, prompt: str, output_path: str, negative_prompt: str = "noise, bad quality, artifacts",
                       num_inference_steps: int = 100, audio_length_in_s: int = 5, num_waveforms_per_prompt: int = 3):
        output_dir = os.path.dirname(output_path)
        assert os.path.isdir(output_dir), f"Output folder {output_dir} does not exist"
        logger.info(f"Generating audio for: {prompt} [{audio_length_in_s}s]")
        audio = self.pipe(
            prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=num_inference_steps,
            audio_length_in_s=audio_length_in_s,
            num_waveforms_per_prompt=num_waveforms_per_prompt,
        ).audios

        # Normalize and convert to int16 if it's in another format (e.g., float32)
        if audio[0].dtype != np.int16:
            audio_int16 = np.int16(audio[0] / np.max(np.abs(audio[0])) * 32767)
        else:
            audio_int16 = audio[0]

        scipy.io.wavfile.write(output_path, rate=16000, data=audio_int16)
        return output_path


if __name__ == '__main__':
    audio_ldm = AudioLDM()
    audio_ldm.generate_audio(prompt="The sound of crackling fire", output_path="./output-test.wav", num_inference_steps=2,
                             audio_length_in_s=3, num_waveforms_per_prompt=1)