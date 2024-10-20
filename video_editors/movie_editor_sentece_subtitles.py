import os
import sys
from loguru import logger
import moviepy.editor as mp
from moviepy.video.tools.subtitles import SubtitlesClip

from video_editors.movie_editor_base import MovieEditorBase

# We could also do it with pysrt, but it becomes easier this way
if sys.platform.startswith('win'):
    import ftfy
    text_reencoder = lambda text: ftfy.fix_text(text)
else:
    text_reencoder = lambda text: text


class MovieEditorSentenceSubtitles(MovieEditorBase):
    def __init__(self, output_folder: str, check_validity: bool = True):
        super().__init__(output_folder, check_validity = check_validity)

    def _build_clip(self, item: dict):
        clip = super()._build_clip(item)
        if clip is None:
            return None

        subtitles_path = os.path.join(self.output_folder, 'subtitles', 'sentence', f"{item['id']}.srt")

        if os.path.isfile(subtitles_path):
            # Calculate the padded width
            padded_width, padded_height = clip.w * 0.9, clip.h * 0.9

            # Load and overlay subtitles with better styling and padding
            generator = lambda txt: mp.TextClip(text_reencoder(text=txt), font='Arial-Bold', fontsize=32, color='white',
                                                stroke_color='black', stroke_width=1, method='caption',
                                                size=(padded_width, None))
            subtitles = SubtitlesClip(subtitles_path, generator)

            # Create a dummy two-line TextClip for height estimation
            dummy_clip = generator("Line 1\nLine 2")
            subtitle_height = dummy_clip.h
            dummy_clip.close()  # Close the dummy clip to free resources

            # Calculate the y position to keep the entire subtitle block within the padded height
            position_x = (clip.w - padded_width) / 2
            position_y = padded_height - subtitle_height + (clip.h - padded_height) / 2

            # Overlay the subtitles clip onto the main clip with padding
            clip = mp.CompositeVideoClip([
                clip,
                subtitles.set_position((position_x, position_y))
            ])
        else:
            logger.warning(f"Missing subtitles file for ID: {item['id']}")

        return clip

