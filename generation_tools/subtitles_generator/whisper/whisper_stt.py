from copy import deepcopy

import whisper
import os
import nltk
from nltk.metrics import edit_distance
from nltk.tokenize import sent_tokenize, word_tokenize
from loguru import logger
import math
from utils.utils import get_audio_length
import string
import torch

PUNCTUATION = f"{string.punctuation}“”‘’¿¡"
# If punkt_tab is not downloaded, download it
nltk.download('punkt_tab')
device = "cuda" if torch.cuda.is_available() else "cpu"
class Whisper:
    def __init__(self, size: str = "small", load_on_demand: bool = False):
        self._size = size
        if load_on_demand:
            self._model = None
        else:
            self._model = whisper.load_model(size, device=device)

    @property
    def model(self):
        if self._model is None:
            self._model = whisper.load_model(self._size, device=device)
        return self._model

    def _transcribe(self, audio_path: str, prompt: str = None) -> dict:
        assert any(audio_path.endswith(ext) for ext in
                   [".wav", ".mp3", ".flac"]), "Audio file must be in .wav, .mp3 or .flac format"
        assert os.path.isfile(audio_path), f"Audio file {audio_path} does not exist"
        # Try with and without prompt and get the closer result
        if prompt is None:
            result = self.model.transcribe(audio_path, word_timestamps=True)
        else:
            result_prompt = self.model.transcribe(audio_path, word_timestamps=True, initial_prompt=prompt)
            prompt_dist = edit_distance(prompt.strip().lower(), result_prompt['text'].strip().lower())
            result_no_prompt = self.model.transcribe(audio_path, word_timestamps=True)
            no_prompt_dist = edit_distance(prompt.strip().lower(), result_no_prompt['text'].strip().lower())
            result = result_prompt if prompt_dist < no_prompt_dist else result_no_prompt
        return result

    def check_audio_quality(self, audio_path: str, expected_text: str) -> float:
        result = self._transcribe(audio_path, prompt=expected_text)
        segments = result['segments']
        expected_sentences = sent_tokenize(expected_text)
        original_segments_count = len(segments)
        original_segments = deepcopy(segments)
        # Calculate the difference in sentence count. Penalty 0.3 by sentence
        difference = abs(len(expected_sentences) - len(segments))
        missmatch_penalty = min(0.6, 0.3 * difference)
        try:
            segments = self._adjust_segments_to_sentences(segments=segments, sentences=expected_sentences, force_reassignment=True)
        except AssertionError as e:
            logger.warning(f"Error adjusting segments to sentences. Probably there is a lost phrase. {e}")
            return -1.0


        # Calculate the difference in audio length. Penalty 0.3 by second
        audio_length = get_audio_length(audio_path=audio_path)
        start_difference, end_difference = abs(segments[0]['start'] - 0.), abs(segments[-1]['end'] - audio_length)
        audio_length_penalty = 0.1 * (start_difference + end_difference)

        # Calculate the difference in text. Penalty 0.03 by each edit_distance unit
        distance = sum(edit_distance(expected_sentence.strip().lower(), segment['text'].strip().lower())
                       for expected_sentence, segment in zip(expected_sentences, segments)
                       if len(segment['text']) > 0)
        text_penalty = 0.03 * distance
        if text_penalty > 1.0:
            logger.warning(f"Text mismatch penalty is too high: {text_penalty:.2f}. "
                            f"Expected: {expected_text} "
                            f"Transcribed: {' - '.join([segment['text'] for segment in segments])}")
            segments = self._adjust_segments_to_sentences(segments=original_segments, sentences=expected_sentences, force_reassignment=True)

        # Calculate the audio stability as the average time/word for each segment
        word_pace_by_segment = [(segment['end'] - segment['start']) / len(segment['words']) for segment in segments]
        # Calculate the standard deviation of the time/word
        std = math.sqrt(sum((time - sum(word_pace_by_segment) / len(word_pace_by_segment)) ** 2
                            for time in word_pace_by_segment) / len(word_pace_by_segment))
        # For each 0.1 of standard deviation, add 0.2 of penalty
        stability_penalty = 0.2 * (std / 0.1)
        perfect_pace = 0.275 # Ideal time/word
        average_pace = sum(word_pace_by_segment) / len(word_pace_by_segment)
        # Apply a penalty of 0.2 for each 0.1 of difference from the perfect pace
        pace_penalty = 0.2 * abs(average_pace - perfect_pace) / 0.1

        # Calculate the final quality score (1.0 best quality, 0.0 worst quality)
        penalties = min(1.0, missmatch_penalty + audio_length_penalty + text_penalty + stability_penalty + pace_penalty)
        score = 1.0 - penalties

        logger.debug(f"Quality score: {score:.2f} (Sentence Mismatch: {missmatch_penalty:.2f} "
                     f"({original_segments_count} vs {len(expected_sentences)}), "
                     f"Audio Lenght Missmatch: {audio_length_penalty:.2f} ({start_difference:.2f} + {end_difference:.2f}), "
                     f"Text Mismatch: {text_penalty:.2f} (dist: {distance}), "
                     f"Speed Stability: {stability_penalty:.2f} (std: {std:.2f}), "
                     f"Word Pace: {pace_penalty:.2f} (avg: {average_pace:.2f})")

        return score


    def audio_file_to_srt(self, audio_path: str, srt_sentence_output_path: str,
                          srt_words_output_path: str,
                          text_to_fit: str = None):
        result = self._transcribe(audio_path, prompt=text_to_fit)
        segments = result['segments']

        if text_to_fit:
            # If text_to_fit is provided, align it with Whisper's timestamps
            segments = self._fit_text_to_segments(segments=segments, text_to_fit=text_to_fit)

        # Generate sentence-based SRT
        self._generate_sentence_srt(segments=segments, srt_file_path=srt_sentence_output_path)

        # Generate word-based SRT
        self._generate_word_srt(segments=segments, srt_file_path=srt_words_output_path)

    def _fit_text_to_segments(self, segments, text_to_fit: str, max_edit_distance: int = 3):
        """
        Align the `text_to_fit` with the Whisper-predicted timestamps.
        Assumes that `text_to_fit` is a clean version of the original text.
        Uses a sliding window approach with edit distance to find the best match for words.
        Expands the window_end offset if no match is found.
        """
        sentences = sent_tokenize(text_to_fit)  # Split the provided text into sentences
        if len(sentences) != len(segments):
            logger.warning("Sentence count does not match segment count. Adjusting segments to match sentences.")
            logger.warning(f"Segments: {' - '.join([segment['text'] for segment in segments])}"\
                           f"\nSentences: {' - '.join(sentences)}")
        segments = self._adjust_segments_to_sentences(segments=segments, sentences=sentences, force_reassignment=True)
        assert len(sentences) == len(segments), "Sentence count does not match segment count"
        words_from_sentences = [word for sentence in sentences for word in sentence.split(" ")]  # Flatten all words
        word_index = 0

        for true_sentence, segment in zip(sentences, segments):
            window_end_offset = 2  # Initial window end offset

            for word_info in segment['words']:
                predicted_word = word_info['word'].strip().lower()

                # Sliding window around the current word index
                best_match, best_distance = None, float('inf')
                window_start = max(word_index - 2, 0)
                window_end = min(word_index + window_end_offset, len(words_from_sentences))

                for i in range(window_start, window_end):
                    actual_word = words_from_sentences[i].strip().lower()
                    distance = edit_distance(predicted_word, actual_word)
                    if distance < best_distance and distance <= max_edit_distance:
                        best_distance = distance
                        best_match = i

                if best_match is not None:
                    # Replace the predicted word with the best match from the original text
                    word_info['word'] = words_from_sentences[best_match]
                    word_index = best_match + 1  # Move the index forward
                else:
                    logger.warning(f"Word mismatch: {predicted_word} not found in window.")
                    window_end_offset += 1  # Expand the window if no match is found

            # Keep the original segment structure but replace the words with fitted words
            segment['text'] = true_sentence

            return segments

    import nltk
    from nltk.metrics import edit_distance
    from copy import deepcopy

    def _adjust_segments_to_sentences(self, segments:list[dict], sentences: list[str], force_reassignment: bool = False):
        """
        Adjusts the segments to ensure the count matches the sentence count.
        This involves iteratively creating segments with increasing words until
        the lowest edit distance is found for each sentence.
        """

        if not force_reassignment and len(segments) == len(sentences):
            return segments  # No adjustment needed

        # Function to calculate edit distance between a segment and a sentence
        def calculate_edit_distance(segment_text, sentence_text):
            return edit_distance(segment_text.strip().lower(), sentence_text.strip().lower())

        adjusted_segments = []
        remaining_words = [word for segment in segments for word in segment['words']]

        for sentence in sentences[:-1]:
            best_segment, best_distance = None, float('inf')
            words_to_use = []

            # Iteratively build the segment by adding words and checking the edit distance
            for i in range(1, len(remaining_words) + 1):
                candidate_segment_text = "".join(word['word'] for word in remaining_words[:i]).strip()
                clean_segment_text = candidate_segment_text.translate(str.maketrans('', '', PUNCTUATION)).strip().lower()
                clean_sentence = sentence.translate(str.maketrans('', '', PUNCTUATION)).strip().lower()
                distance = calculate_edit_distance(clean_segment_text, clean_sentence)

                if distance < best_distance:
                    best_distance, words_to_use = distance, remaining_words[:i]
                    best_segment = {
                        'start': words_to_use[0]['start'],
                        'end': words_to_use[-1]['end'],
                        'text': candidate_segment_text,
                        'words': words_to_use
                    }

            # Update the adjusted segments with the best found segment
            adjusted_segments.append(best_segment)

            # Remove the used words from remaining words
            remaining_words = remaining_words[len(words_to_use):]

        assert len(remaining_words) > 0, "Remaining words should not be empty, there is still one sentence left."

        # For the last sentence, just take all remaining words
        if remaining_words:
            last_segment_text = "".join(word['word'] for word in remaining_words)
            adjusted_segments.append({
                'start': remaining_words[0]['start'],
                'end': segments[-1]['end'],
                'text': last_segment_text,
                'words': remaining_words
            })

        return adjusted_segments

    def _format_time_srt(self, time_in_seconds: float) -> str:
        hours, remainder = divmod(time_in_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{milliseconds:03}"

    def _generate_sentence_srt(self, segments, srt_file_path):
        with open(srt_file_path, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(segments, start=1):
                start_time = segment['start']
                end_time = segment['end']
                text = segment['text'].strip()
                f.write(f"{i}\n")
                f.write(f"{self._format_time_srt(start_time)} --> {self._format_time_srt(end_time)}\n")
                f.write(f"{text}\n\n")

    def _generate_word_srt(self, segments, srt_file_path):
        with open(srt_file_path, 'w', encoding='utf-8') as f:
            index = 1
            for segment in segments:
                for word_info in segment['words']:
                    start_time = word_info['start']
                    end_time = word_info['end']
                    text = word_info['word'].strip()
                    f.write(f"{index}\n")
                    f.write(f"{self._format_time_srt(start_time)} --> {self._format_time_srt(end_time)}\n")
                    f.write(f"{text}\n\n")
                    index += 1

if __name__ == '__main__':
    file = 'audio-test.wav'

    whisper = Whisper()
    whisper.audio_file_to_srt(file, 'output-test.srt')