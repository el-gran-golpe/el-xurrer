import os
from loguru import logger
import json
import moviepy.editor as mp
from tqdm import tqdm

from utils.exceptions import EmptyScriptException
from utils.utils import get_audio_length, find_word_timing
import sys
from moviepy.video.fx.resize import resize

# We could also do it with pysrt, but it becomes easier this way
if sys.platform.startswith('win'):
    import ftfy
    text_reencoder = lambda text: ftfy.fix_text(text)
else:
    text_reencoder = lambda text: text

class MovieEditorBase:
    def __init__(self, output_folder: str, check_validity: bool = True):
        self.output_folder = output_folder

        # Load the script as before
        with open(os.path.join(output_folder, 'script.json'), 'r', encoding='utf-8') as f:
            self.script = json.load(f)
            if check_validity:
                self.check_script_validity(self.script)

    def _build_clip(self, item: dict, include_screen_text_from_start: bool = True) -> mp.CompositeVideoClip:
        _id, sound, screen_text = item["id"], item.get("sound"), item.get("screen_text")
        audio_path = os.path.join(self.output_folder, 'audio', f"{_id}.wav")
        image_path = os.path.join(self.output_folder, 'images', f"{_id}.png")
        sounds_path = os.path.join(self.output_folder, 'sounds', f"{_id}.wav")
        word_subtitles_path = os.path.join(self.output_folder, 'subtitles', 'word', f"{_id}.srt")

        clip_length = get_audio_length(audio_path=audio_path)
        if not os.path.isfile(audio_path):
            logger.warning(f"Missing audio file for ID: {_id}")
            return None

        if not os.path.isfile(image_path):
            logger.warning(f"Missing image file for ID: {_id}")
            return None

        audio_clip = mp.AudioFileClip(audio_path)
        image_clip = mp.ImageClip(image_path).set_duration(clip_length)

        # Apply a zoom-out effect: Start at 110% size and end at 100%
        image_clip = image_clip.fx(resize, 1.1)  # Start at 110% size
        # Gradually zoom out over the clip duration
        image_clip = image_clip.resize(lambda t: 1.1 - 0.1 * (t / clip_length))

        if sound is not None and os.path.isfile(sounds_path):
            assert os.path.isfile(word_subtitles_path), f"Missing word subtitle file for ID: {_id}"
            from_word, to_word = sound['from'], sound['to']
            sound_start, _ = find_word_timing(srt_file_path=word_subtitles_path, word=from_word, retrieve_last=False)
            _, sound_end = find_word_timing(srt_file_path=word_subtitles_path, word=to_word, retrieve_last=True)

            sound_length = get_audio_length(audio_path=sounds_path)
            if sound_end is None and sound_start is not None:
                sound_end = sound_start + sound_length
            elif sound_start is None and sound_end is not None:
                sound_start = sound_end - sound_length
            elif sound_start is None and sound_end is None:
                sound_start, sound_end = 0., sound_length

            sound_end = min(sound_end, clip_length)

            # Load the sound clip and check its duration
            sound_clip = mp.AudioFileClip(sounds_path)
            sound_clip_duration = sound_clip.duration

            # Create the subclip with the original sound clip duration
            sound_clip = sound_clip.subclip(0, sound_clip_duration).volumex(0.25)
            fade_duration = 1. if sound_clip_duration > 5 else sound_clip_duration / 5
            sound_clip = sound_clip.audio_fadein(fade_duration).audio_fadeout(fade_duration)
            # Position the sound clip at the desired time range in the main audio
            sound_clip = sound_clip.set_start(sound_start).set_end(sound_end)

            # Merge the audio and sound clips
            audio_clip = mp.CompositeAudioClip([audio_clip, sound_clip])

        if screen_text is not None:
            from_word, to_word, text = screen_text['from'], screen_text['to'], screen_text['text']
            if include_screen_text_from_start:
                start = 0.
            else:
                start, _ = find_word_timing(srt_file_path=word_subtitles_path, word=from_word, retrieve_last=False)
                assert start is not None, f"Could not find word {from_word} in subtitle file {word_subtitles_path}"
            _, end = find_word_timing(srt_file_path=word_subtitles_path, word=to_word, retrieve_last=True)
            assert end is not None, f"Could not find word {to_word} in subtitle file {word_subtitles_path}"
            end = min(end, clip_length)

            # Define the text generator, similar to how SubtitlesClip would generate the text
            generator = lambda txt: mp.TextClip(text_reencoder(text=txt), font='Arial-Bold', fontsize=64, color='white',
                                                stroke_color='black', stroke_width=2, method='caption',
                                                size=(image_clip.w * 0.6, None))

            # Generate the text clip for the given text
            text_clip = generator(text).set_start(start).set_duration(end - start).set_position(('center', 'center'))

            # Overlay the text clip onto the image clip
            image_clip = mp.CompositeVideoClip([image_clip, text_clip])

        clip = image_clip.set_audio(audio_clip)
        return clip

    def generate_video_from_clips(self, output_video_path: str):
        video_clips = []
        for item in tqdm(self.script["content"], desc="Generating video clips"):
            clip = self._build_clip(item)
            if clip:
                video_clips.append(clip)

        if video_clips:
            self._save_video(output_video_path, video_clips)
        elif len(self.script["content"]) == 0:
            raise EmptyScriptException("Script content is empty")
        else:
            raise Exception(f"No video clips were generated for {output_video_path}")

    def _save_video(self, output_video_path: str, video_clips: list) -> str:
        temp_audio_file_path = os.path.join(self.output_folder, 'video', 'temp_audio.m4a')
        final_video = mp.concatenate_videoclips(video_clips)
        final_video.write_videofile(
            output_video_path,
            codec="libx264",
            temp_audiofile=temp_audio_file_path,
            remove_temp=True,
            audio_codec="aac",
            fps=24
        )
        logger.info(f"Video saved to {output_video_path}")
        return output_video_path


    def check_script_validity(self, script) -> None:
        assert "lang" in script, "Script must contain a lang key"
        assert "title" in script, "Script must contain a title key"
        assert "description" in script, "Script must contain a description key"
        assert "content" in script, "Script must contain a content key"

        content = script["content"]
        assert isinstance(content, list), "Content must be a list"
        assert all("text" in item for item in content), "All items in content must contain a text key"
        assert all("image" in item for item in content), "All items in content must contain an image key"
        assert all("id" in item for item in content), "All items in content must contain an id key"
