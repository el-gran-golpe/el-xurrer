from uuid import uuid4
import os
from loguru import logger
import json
from time import time
from tqdm import tqdm
from slugify import slugify

from pipeline.movie_editor.movie_editor_sentece_subtitles import MovieEditorSentenceSubtitles
from generation_tools.voice_generator.xtts.xtts import Xtts
from generation_tools.image_generator.flux.flux import Flux
from generation_tools.subtitles_generator.whisper.whisper_stt import Whisper

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
        self.subtitle_generator = Whisper()

        self.prepare_output_folder(output_folder=output_folder)
        self.output_folder = output_folder

        # Read the script file
        with open(os.path.join(output_folder, 'script.json'), 'r') as f:
            script = json.load(f)
            self.check_script_validity(script=script)

        self.script = self.generate_missing_identifiers(script=script)

    def generate_video(self):
        lang = self.script["lang"]
        w, h = WH_BY_ASPECT_RATIO[self.script["aspect_ratio"]]
        for item in tqdm(self.script["content"]):
            _id, text, image_prompt = item["id"], item["text"], item["image"]
            audio_path = os.path.join(self.output_folder, 'audio', f"{_id}.wav")
            image_path = os.path.join(self.output_folder, 'images', f"{_id}.png")
            subtitle_sentence_path = os.path.join(self.output_folder, 'subtitles', 'sentence', f"{_id}.srt")
            subtitle_word_path = os.path.join(self.output_folder, 'subtitles', 'word', f"{_id}.srt")

            if text and not os.path.isfile(audio_path):
                start = time()
                self.voice_generator.generate_audio_cloning_voice_to_file(text=text, output_path=audio_path,
                                                                          language=lang, retries=3)
                logger.info(f"Audio generation: {time() - start:.2f}s")
                assert os.path.isfile(audio_path), f"Audio file {audio_path} was not generated"

            if not os.path.isfile(image_path):
                start = time()
                self.image_generator.generate_image(prompt=image_prompt, output_path=image_path, width=w, height=h)
                logger.info(f"Image generation: {time() - start:.2f}s")
                assert os.path.isfile(image_path), f"Image file {image_path} was not generated"

            if text and not os.path.isfile(subtitle_sentence_path) or not os.path.isfile(subtitle_word_path):
                start = time()
                self.subtitle_generator.audio_file_to_srt(audio_path=audio_path, srt_sentence_output_path=subtitle_sentence_path,
                                                           srt_words_output_path=subtitle_word_path, text_to_fit=text)
                logger.info(f"Subtitle generation: {time() - start:.2f}s")
                assert os.path.isfile(subtitle_sentence_path), f"Sentence subtitle file {subtitle_sentence_path} was not generated"
                assert os.path.isfile(subtitle_word_path), f"Word subtitle file {subtitle_word_path} was not generated"


        self.generate_video_from_clips(output_video_path=os.path.join(self.output_folder, 'video', f"video.mp4"))


    def generate_video_from_clips(self, output_video_path: str):
        movie_editor = MovieEditorSentenceSubtitles(output_folder=self.output_folder)
        movie_editor.generate_video_from_clips(output_video_path=output_video_path)

    def generate_missing_identifiers(self, script: dict[str, str | dict[str, str]], override: bool = True) -> dict[str, str | dict[str, str]]:
        new_content = False
        for i, item in enumerate(script["content"]):
            assert isinstance(item, dict), "Items in content must be dictionaries"
            if "id" not in item:
                section_slug = slugify(item.get('section', 'NoSection'))
                item["id"] = f"{section_slug}--{i + 1}--{str(uuid4())[:4]}"
                new_content = True

        if override or new_content:
            with open(os.path.join(self.output_folder, 'script.json'), 'w') as f:
                json.dump(script, f, indent=4, ensure_ascii=False)
        return script



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

    def check_script_validity(self, script) -> None:
        assert "lang" in script, "Script must contain a lang key"
        assert "title" in script, "Script must contain a title"
        assert "description" in script, "Script must contain a description"
        assert "content" in script, "Script must contain a content"
        content = script["content"]
        assert isinstance(content, list), "Content must be a list"
        assert all("text" in item for item in content), "All items in content must contain a text key"
        assert all("image" in item for item in content), "All items in content must contain an image key"