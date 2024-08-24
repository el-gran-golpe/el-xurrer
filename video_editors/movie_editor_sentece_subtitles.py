import os
from loguru import logger
import moviepy.editor as mp
from moviepy.video.tools.subtitles import SubtitlesClip

from video_editors.movie_editor_base import MovieEditorBase


class MovieEditorSentenceSubtitles(MovieEditorBase):
    def __init__(self, output_folder: str):
        super().__init__(output_folder)

    def _build_clip(self, item: dict):
        clip = super()._build_clip(item)
        if clip is None:
            return None

        subtitles_path = os.path.join(self.output_folder, 'subtitles', 'sentence', f"{item['id']}.srt")

        if os.path.isfile(subtitles_path):
            # Load and overlay subtitles with better styling
            generator = lambda txt: mp.TextClip(txt, font='Arial-Bold', fontsize=32, color='white',
                                                stroke_color='black', stroke_width=1, method='caption', size=(clip.w, None))
            subtitles = SubtitlesClip(subtitles_path, generator)

            # Add padding to the bottom to avoid cropping
            clip = mp.CompositeVideoClip([
                clip,
                subtitles.set_position(('center', 'bottom'))
            ])
        else:
            logger.warning(f"Missing subtitles file for ID: {item['id']}")

        return clip
