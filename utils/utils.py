import pysrt
import os
from nltk.metrics import edit_distance
from loguru import logger
import wave
import string
from datetime import datetime, timedelta
from pydub import AudioSegment
from pydub.silence import split_on_silence


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
    print(f"Trimmed audio saved to: {output_file}")



def get_closest_monday():
    """
    Get the closest Monday to today's date.
    """

    today = datetime.now()
    closest_monday = today + timedelta(days=(0 - today.weekday()))
    return closest_monday
