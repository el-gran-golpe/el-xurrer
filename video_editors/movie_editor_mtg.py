import os
import sys
from loguru import logger
import moviepy.editor as mp
from moviepy.video.tools.subtitles import SubtitlesClip
from tqdm import tqdm

from utils.exceptions import EmptyScriptException
from utils.utils import get_audio_length
from video_editors.movie_editor_base import MovieEditorBase

# We could also do it with pysrt, but it becomes easier this way
if sys.platform.startswith('win'):
    import ftfy
    text_reencoder = lambda text: ftfy.fix_text(text)
else:
    text_reencoder = lambda text: text


class MovieEditorMtg(MovieEditorBase):
    def __init__(self, output_folder: str, check_validity: bool = True):
        super().__init__(output_folder, check_validity = check_validity)

    def _build_clip(self, item: dict):
        _id = item["id"]
        audio_path = os.path.join(self.output_folder, 'audio', f"{_id}.wav")
        image_path = os.path.join(self.output_folder, 'images', f"{_id}.png")


        clip_length = get_audio_length(audio_path=audio_path)
        if not os.path.isfile(audio_path):
            logger.warning(f"Missing audio file for ID: {_id}")
            return None

        if not os.path.isfile(image_path):
            logger.warning(f"Missing image file for ID: {_id}")
            return None

        audio_clip = mp.AudioFileClip(audio_path)
        image_clip = mp.ImageClip(image_path).set_duration(clip_length)


        clip = image_clip.set_audio(audio_clip)
        return clip

    def generate_video_from_clips(self, output_video_path: str):
        video_clips = []
        for category in tqdm(self.script["categories"], desc="Generating video clips"):
            for card in category["cards"]:
                clip = self._build_clip(item=card)
                if clip:
                    video_clips.append(clip)

        if video_clips:
            self._save_video(output_video_path, video_clips)
        elif len(self.script["categories"]) == 0:
            raise EmptyScriptException("Script content is empty")
        else:
            raise Exception(f"No video clips were generated for {output_video_path}")