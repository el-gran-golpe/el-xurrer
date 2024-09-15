from uuid import uuid4

import pysrt
import os
from nltk.metrics import edit_distance
from loguru import logger
import wave
import string
from datetime import datetime, timedelta
from pydub import AudioSegment
from pydub.silence import split_on_silence
import json

from slugify import slugify

PUNCTUATION = f"{string.punctuation}“”‘’¿¡"


def find_word_timing(srt_file_path: str, word: str, max_distance: int = 1, retrieve_last: bool = False):
    """
    Find the start and end times of a word in a subtitle file.

    :param srt_file_path: Path to the .srt subtitle file
    :param word: The word to search for
    :param max_distance: Maximum allowed edit distance for matching words
    :param retrieve_last: If True, retrieves the last occurrence instead of the first
    :return: A tuple with start time and end time in seconds, or (None, None) if the word is not found
    """
    assert os.path.isfile(srt_file_path), f"Subtitle file {srt_file_path} does not exist"
    assert max_distance >= 0, "max_distance must be a non-negative integer"
    assert isinstance(word, str) and word != "", "word must be a non-empty string"

    #TODO: Accept complete phrases
    # By the moment, if it is a phrase just keep the last word if retrieve_last and the first word if not retrieve_last
    if " " in word:
        words = word.split()
        word = words[-1] if retrieve_last else words[0]

    # Normalize the search word: strip, lowercase, remove punctuation
    normalized_word = word.strip().lower().translate(str.maketrans('', '', PUNCTUATION))

    # Load the .srt file
    subs = pysrt.open(srt_file_path)

    found_time = None

    for sub in subs:
        # Split subtitle text into words
        srt_words = sub.text.split()

        for srt_word in srt_words:
            # Normalize the current subtitle word
            normalized_srt_word = srt_word.strip().lower().translate(str.maketrans('', '', PUNCTUATION))

            # Use edit_distance to compare words
            if edit_distance(normalized_srt_word, normalized_word) <= max_distance:
                # Convert start and end times to float representing seconds
                start_time_seconds = sub.start.ordinal / 1000.0
                end_time_seconds = sub.end.ordinal / 1000.0
                found_time = (start_time_seconds, end_time_seconds)

                # If retrieve_last is False, return the first found occurrence
                if not retrieve_last:
                    return found_time

    if found_time:
        return found_time

    logger.warning(f"Could not find word {word} in subtitle file {srt_file_path}")
    return None, None

def time_between_two_words_in_srt(srt_file_path: str, word1: str, word2: str, max_distance=1):
    start_word1, end_word1 = find_word_timing(srt_file_path=srt_file_path, word=word1, max_distance=max_distance, retrieve_last=False)
    start_word2, end_word2 = find_word_timing(srt_file_path=srt_file_path, word=word2, max_distance=max_distance, retrieve_last=True)

    if start_word1 is None or start_word2 is None:
        logger.warning(f"Could not find timing between words {word1} and {word2}")
        return None

    return end_word2 - start_word1

def get_audio_length(audio_path: str) -> float:
    with wave.open(audio_path, 'r') as audio_file:
        frames = audio_file.getnframes()
        rate = audio_file.getframerate()
        duration = frames / float(rate)
    return duration

def trim_silence_from_audio(input_file, output_file, silence_thresh=-40, min_silence_len=500, keep_silence=350):
    # Load the audio file
    audio = AudioSegment.from_wav(input_file)

    # Split the audio where silence is detected
    chunks = split_on_silence(audio,
                              min_silence_len=min_silence_len,
                              silence_thresh=silence_thresh,
                              keep_silence=keep_silence)

    # Combine the chunks together
    trimmed_audio = AudioSegment.silent(duration=0)
    for chunk in chunks:
        trimmed_audio += chunk

    # Export the trimmed audio
    trimmed_audio.export(output_file, format="wav")



def get_closest_monday():
    """
    Get the closest Monday to today's date.
    """

    today = datetime.now()
    closest_monday = today + timedelta(days=(0 - today.weekday()))
    return closest_monday


def generate_ids_in_script(script: dict):
    """
    Generate unique identifiers for each item in the script
    """
    for i, item in enumerate(script["content"]):
        assert isinstance(item, dict), "Items in content must be dictionaries"
        if "id" not in item:
            section_slug = slugify(item.get('section', 'NoSection'))
            item["id"] = f"{section_slug}--{i + 1}--{str(uuid4())[:4]}"
    return script



def check_script_validity(script) -> None:
    assert "lang" in script, "Script must contain a lang key"
    assert "title" in script, "Script must contain a title"
    assert "description" in script, "Script must contain a description"
    assert "content" in script, "Script must contain a content"
    content = script["content"]
    assert isinstance(content, list), "Content must be a list"
    assert len(content) > 0, "Content must not be empty"

    assert all("text" in item for item in content), "All items in content must contain a text key"
    assert all("image" in item for item in content), "All items in content must contain an image key"
    assert all("sound" in item for item in content), "All items in content must contain a sound key"
    assert all("id" in item for item in content), "All items in content must contain an id key"

    for item in content:
        if item["sound"] is not None:
            assert all(key in item["sound"] for key in ("from", "to", "prompt")), \
                "Sound must contain from, to and prompt keys"
        assert all(isinstance(item[key], str) for key in ("text", "image")), \
            "Text and image must be strings"

def missing_video_assets(assets_path: str) -> bool:
    """
    Check if the video assets are missing
    """
    assert os.path.isdir(assets_path), f"Assets file {assets_path} does not exist"
    script_path = os.path.join(assets_path, 'script.json')
    if not os.path.isfile(script_path):
        return True
    with open(script_path, 'r', encoding='utf-8') as f:
        script = json.load(f)

    assert 'content' in script, "Content not found in script"
    for item in script["content"]:
        _id, text, image_prompt, sound = item["id"], item["text"], item["image"], item["sound"]
        audio_path = os.path.join(assets_path, 'audio', f"{_id}.wav")
        image_path = os.path.join(assets_path, 'images', f"{_id}.png")
        sounds_path = os.path.join(assets_path, 'sounds', f"{_id}.wav")
        subtitle_sentence_path = os.path.join(assets_path, 'subtitles', 'sentence', f"{_id}.srt")
        subtitle_word_path = os.path.join(assets_path, 'subtitles', 'word', f"{_id}.srt")
        if text and not os.path.isfile(audio_path):
            return True
        if not os.path.isfile(image_path):
            return True
        if text and not os.path.isfile(subtitle_sentence_path) or not os.path.isfile(subtitle_word_path):
            return True
        if sound is not None and not os.path.isfile(sounds_path):
            return True
    video_path = os.path.join(assets_path, 'video.mp4')
    if not os.path.isfile(video_path):
        return True
    return False
