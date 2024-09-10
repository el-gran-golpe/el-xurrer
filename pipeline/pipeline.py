import os
from loguru import logger
import json
from time import time
from tqdm import tqdm

from generation_tools.thumbnails_generator.templated import Templated
from utils.utils import time_between_two_words_in_srt
from video_editors.movie_editor_sentece_subtitles import MovieEditorSentenceSubtitles
from generation_tools.voice_generator.xtts.xtts import Xtts
from generation_tools.image_generator.flux.flux import Flux
from generation_tools.subtitles_generator.whisper.whisper_stt import Whisper
from generation_tools.sounds_generator.audio_ldm import AudioLDM

WH_BY_ASPECT_RATIO = {
    "16:9": (1280, 720),
    "4:3": (960, 720),
    "1:1": (720, 720),
    "9:16": (720, 1280),
}

class Pipeline:
    def __init__(self, output_folder: str):

        self.voice_generator = Xtts(load_on_demand=True)
        self.image_generator = Flux(load_on_demand=True)
        self.subtitle_generator = Whisper(load_on_demand=True)
        self.sounds_generator = AudioLDM(load_on_demand=True)
        self.thumbnail_generator = Templated()

        self.prepare_output_folder(output_folder=output_folder)
        self.output_folder = output_folder

        # Read the script file
        with open(os.path.join(output_folder, 'script.json'), 'r', encoding='utf-8') as f:
            script = json.load(f)
            self.check_script_validity(script=script)

        self.script = script

    def generate_video(self):
        lang = self.script["lang"]
        w, h = WH_BY_ASPECT_RATIO[self.script["aspect_ratio"]]

        self._generate_thumbnail_if_not_exists()

        for item in tqdm(self.script["content"]):
            _id, text, image_prompt, sound = item["id"], item["text"], item["image"], item["sound"]
            audio_path = os.path.join(self.output_folder, 'audio', f"{_id}.wav")
            image_path = os.path.join(self.output_folder, 'images', f"{_id}.png")
            sounds_path = os.path.join(self.output_folder, 'sounds', f"{_id}.wav")
            subtitle_sentence_path = os.path.join(self.output_folder, 'subtitles', 'sentence', f"{_id}.srt")
            subtitle_word_path = os.path.join(self.output_folder, 'subtitles', 'word', f"{_id}.srt")
            regenerate_subtitles = False
            if text and not os.path.isfile(audio_path):
                start = time()
                self.voice_generator.generate_audio_to_file(text=text, output_path=audio_path,
                                                            language=lang, retries=3)
                logger.info(f"Audio generation: {time() - start:.2f}s")
                assert os.path.isfile(audio_path), f"Audio file {audio_path} was not generated"
                regenerate_subtitles = True

            if not os.path.isfile(image_path):
                start = time()
                self.image_generator.generate_image(prompt=image_prompt, output_path=image_path, width=w, height=h)
                logger.info(f"Image generation: {time() - start:.2f}s")
                assert os.path.isfile(image_path), f"Image file {image_path} was not generated"

            if text and (regenerate_subtitles or not os.path.isfile(subtitle_sentence_path) or not os.path.isfile(subtitle_word_path)):
                start = time()
                self.subtitle_generator.audio_file_to_srt(audio_path=audio_path, srt_sentence_output_path=subtitle_sentence_path,
                                                           srt_words_output_path=subtitle_word_path, text_to_fit=text)
                logger.info(f"Subtitle generation: {time() - start:.2f}s")
                assert os.path.isfile(subtitle_sentence_path), f"Sentence subtitle file {subtitle_sentence_path} was not generated"
                assert os.path.isfile(subtitle_word_path), f"Word subtitle file {subtitle_word_path} was not generated"

            if sound is not None and not os.path.isfile(sounds_path):
                start = time()
                from_word, to_word, prompt = sound['from'], sound['to'], sound['prompt']
                sound_length = time_between_two_words_in_srt(srt_file_path=subtitle_word_path,
                                                             word1=from_word, word2=to_word, max_distance=1) or 5.0

                self.sounds_generator.generate_audio(prompt=sound['prompt'], output_path=sounds_path,
                                                     num_inference_steps=500,
                                                     audio_length_in_s=sound_length, num_waveforms_per_prompt=5)
                logger.info(f"Sound generation: {time() - start:.2f}s")
                assert os.path.isfile(sounds_path), f"Sound file {sounds_path} was not generated"

        self.generate_video_from_clips(output_video_path=os.path.join(self.output_folder, f"video.mp4"))


    def _generate_thumbnail_if_not_exists(self) -> bool:
        thumbnail_path = os.path.join(self.output_folder, 'thumbnail', 'thumbnail.png')
        thumbnail_background_path = os.path.join(self.output_folder, 'thumbnail', 'background.png')
        if os.path.isfile(thumbnail_path):
            return False

        thumbnail_prompt, thumbnail_text = self.script["thumbnail_prompt"], self.script["thumbnail_text"]

        if not os.path.isfile(thumbnail_background_path):
            # Generate the background image
            self.image_generator.generate_image(prompt=thumbnail_prompt, output_path=thumbnail_background_path, width=1280, height=720)
            assert os.path.isfile(thumbnail_background_path), f"Thumbnail background file {thumbnail_background_path} was not generated"

        # Generate the thumbnail
        self.thumbnail_generator.generate_thumbnail(image=thumbnail_background_path, text=thumbnail_text,
                                                    output_path=thumbnail_path)

        assert os.path.isfile(thumbnail_path), f"Thumbnail file {thumbnail_path} was not generated"
        return True

    def generate_video_from_clips(self, output_video_path: str):
        movie_editor = MovieEditorSentenceSubtitles(output_folder=self.output_folder)
        movie_editor.generate_video_from_clips(output_video_path=output_video_path)

    def prepare_output_folder(self, output_folder: str) -> None:
        assert os.path.isdir(output_folder), f"{output_folder} must exists and contain a file named script.json"
        assert os.path.isfile(os.path.join(output_folder, 'script.json')), f"{output_folder} must contain a file named script.json"
        if not os.path.isdir(os.path.join(output_folder, 'audio')):
            os.makedirs(os.path.join(output_folder, 'audio'))
        if not os.path.isdir(os.path.join(output_folder, 'images')):
            os.makedirs(os.path.join(output_folder, 'images'))
        if not os.path.isdir(os.path.join(output_folder, 'subtitles', 'sentence')):
            os.makedirs(os.path.join(output_folder, 'subtitles', 'sentence'))
        if not os.path.isdir(os.path.join(output_folder, 'subtitles', 'word')):
            os.makedirs(os.path.join(output_folder, 'subtitles', 'word'))
        if not os.path.isdir(os.path.join(output_folder, 'video')):
            os.makedirs(os.path.join(output_folder, 'video'))
        if not os.path.isdir(os.path.join(output_folder, 'sounds')):
            os.makedirs(os.path.join(output_folder, 'sounds'))
        if not os.path.isdir(os.path.join(output_folder, 'thumbnail')):
            os.makedirs(os.path.join(output_folder, 'thumbnail'))

    def check_script_validity(self, script) -> None:
        assert "lang" in script, "Script must contain a lang key"
        assert "title" in script, "Script must contain a title"
        assert "description" in script, "Script must contain a description"
        assert "content" in script, "Script must contain a content"
        content = script["content"]
        assert isinstance(content, list), "Content must be a list"
        assert all("text" in item for item in content), "All items in content must contain a text key"
        assert all("image" in item for item in content), "All items in content must contain an image key"
        assert all("sound" in item for item in content), "All items in content must contain a sound key"
        assert all("id" in item for item in content), "All items in content must contain an id key"

        for item in content:
            if item["sound"] is not None:
                assert all(key in item["sound"] for key in ["from", "to", "prompt"]), \
                    "Sound must contain from, to and prompt keys"