import os
from loguru import logger
import json
import moviepy.editor as mp
from tqdm import tqdm


class MovieEditorBase:
    def __init__(self, output_folder: str):
        self.output_folder = output_folder

        # Load the script as before
        with open(os.path.join(output_folder, 'script.json'), 'r') as f:
            self.script = json.load(f)
            self.check_script_validity(self.script)


    def _build_clip(self, item: dict):
        _id = item["id"]
        audio_path = os.path.join(self.output_folder, 'audio', f"{_id}.wav")
        image_path = os.path.join(self.output_folder, 'images', f"{_id}.png")

        if not os.path.isfile(audio_path):
            logger.warning(f"Missing audio file for ID: {_id}")
            return None

        if not os.path.isfile(image_path):
            logger.warning(f"Missing image file for ID: {_id}")
            return None

        audio_clip = mp.AudioFileClip(audio_path)
        image_clip = mp.ImageClip(image_path).set_duration(audio_clip.duration)
        return image_clip.set_audio(audio_clip)

    def generate_video_from_clips(self, output_video_path: str):
        video_clips = []
        for item in tqdm(self.script["content"], desc="Generating video clips"):
            clip = self._build_clip(item)
            if clip:
                video_clips.append(clip)

        if video_clips:
            self._save_video(output_video_path, video_clips)
        else:
            logger.error("No video clips were generated. Check if all audio and image files are present.")

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
