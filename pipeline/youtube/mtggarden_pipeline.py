import os
from loguru import logger
import json
from time import time
from tqdm import tqdm

from generation_tools.image_generator.mtg.mtg_image_generator import MTGImageGenerator
from generation_tools.thumbnails_generator.templated import Templated
from utils.mtg.mtg_deck_querier import MoxFieldDeck
from utils.utils import time_between_two_words_in_srt, check_script_validity
from video_editors.movie_editor_mtg import MovieEditorMtg
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

class MTGGardenPipeline:
    def __init__(self, output_folder: str, deck: MoxFieldDeck):

        self.voice_generator = Xtts(load_on_demand=True)
        self.image_generator = MTGImageGenerator()
        self.subtitle_generator = Whisper(load_on_demand=True)
        self.sounds_generator = AudioLDM(load_on_demand=True)
        self.thumbnail_generator = Templated()

        self.prepare_output_folder(output_folder=output_folder)
        self.output_folder = output_folder

        self.deck = deck
        # Read the script file
        with open(os.path.join(output_folder, 'script.json'), 'r', encoding='utf-8') as f:
            script = json.load(f)
            #check_script_validity(script=script)

        self.script = script

    def generate_video(self):
        lang = 'es'#self.script["lang"]
        #w, h = WH_BY_ASPECT_RATIO[self.script["aspect_ratio"]]
        self.generate_categories_assets()

        self.generate_video_from_clips(output_video_path=os.path.join(self.output_folder, f"video.mp4"))


    def generate_categories_assets(self, regenerate_subtitles: bool = False):

        categories = self.script["categories"]
        for category_entry in categories:
            category = category_entry["category"]
            for card in category_entry["cards"]:
                _id, card_name, comment = card['id'], card["card_name"], card["comment"]
                audio_path = os.path.join(self.output_folder, 'audio', f"{_id}.wav")
                image_path = os.path.join(self.output_folder, 'images', f"{_id}.png")
                subtitle_sentence_path = os.path.join(self.output_folder, 'subtitles', 'sentence', f"{_id}.srt")
                subtitle_word_path = os.path.join(self.output_folder, 'subtitles', 'word', f"{_id}.srt")

                if not os.path.isfile(image_path):
                    start = time()
                    card_url = self.deck.get_card_image_url(card_name=card_name)
                    self.image_generator.generate_image(card_urls=[card_url], output_path=image_path)
                    logger.info(f"Image generation: {time() - start:.2f}s")
                    assert os.path.isfile(image_path), f"Image file {image_path} was not generated"

                if not os.path.isfile(audio_path):
                    start = time()

                    self.voice_generator.generate_audio_to_file(text=comment, output_path=audio_path,
                                                                language='es', retries=3)
                    logger.info(f"Audio generation: {time() - start:.2f}s")
                    assert os.path.isfile(audio_path), f"Audio file {audio_path} was not generated"

                if comment and (regenerate_subtitles or not os.path.isfile(subtitle_sentence_path) or not os.path.isfile(
                        subtitle_word_path)):
                    start = time()
                    self.subtitle_generator.audio_file_to_srt(audio_path=audio_path,
                                                              srt_sentence_output_path=subtitle_sentence_path,
                                                              srt_words_output_path=subtitle_word_path,
                                                              text_to_fit=comment)
                    logger.info(f"Subtitle generation: {time() - start:.2f}s")
                    assert os.path.isfile(
                        subtitle_sentence_path), f"Sentence subtitle file {subtitle_sentence_path} was not generated"
                    assert os.path.isfile(
                        subtitle_word_path), f"Word subtitle file {subtitle_word_path} was not generated"

    def _generate_thumbnail_if_not_exists(self) -> bool:

        thumbnail_path = os.path.join(self.output_folder, 'thumbnail', 'thumbnail.png')
        thumbnail_background_path = os.path.join(self.output_folder, 'thumbnail', 'background.png')
        if os.path.isfile(thumbnail_path):
            return False

        thumbnail_prompt, thumbnail_text = self.script["thumbnail_prompt"], self.script["thumbnail_text"]

        if not os.path.isfile(thumbnail_background_path):
            # Generate the background image
            w, h = WH_BY_ASPECT_RATIO[self.script["aspect_ratio"]]
            self.image_generator.generate_image(prompt=thumbnail_prompt, output_path=thumbnail_background_path,
                                                width=w, height=h, retries=2)
            assert os.path.isfile(thumbnail_background_path), f"Thumbnail background file {thumbnail_background_path} was not generated"

        # Generate the thumbnail
        self.thumbnail_generator.generate_thumbnail(image=thumbnail_background_path, text=thumbnail_text,
                                                    output_path=thumbnail_path)

        assert os.path.isfile(thumbnail_path), f"Thumbnail file {thumbnail_path} was not generated"
        return True

    def generate_video_from_clips(self, output_video_path: str):
        movie_editor = MovieEditorMtg(output_folder=self.output_folder, check_validity=False)
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


