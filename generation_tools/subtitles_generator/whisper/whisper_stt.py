from copy import deepcopy
import wave
import whisper
import os
import nltk
from nltk.metrics import edit_distance
from nltk.tokenize import sent_tokenize, word_tokenize
from loguru import logger

# If punkt is not downloaded, download it
if not nltk.data.find('tokenizers/punkt'):
    nltk.download('punkt')

class Whisper:
    def __init__(self):
        self.model = whisper.load_model("small")

    def _transcribe(self, audio_path: str, prompt: str = None) -> dict:
        assert any(audio_path.endswith(ext) for ext in
                   [".wav", ".mp3", ".flac"]), "Audio file must be in .wav, .mp3 or .flac format"
        assert os.path.isfile(audio_path), f"Audio file {audio_path} does not exist"
        result = self.model.transcribe(audio_path, word_timestamps=True, initial_prompt=prompt)
        return result

    def check_audio_quality(self, audio_path: str, expected_text: str) -> float:
        result = self._transcribe(audio_path, prompt=expected_text)
        segments = result['segments']
        expected_sentences = sent_tokenize(expected_text)
        original_segments_count = len(segments)
        # Calculate the difference in sentence count. Penalty 0.4 by sentence
        difference = abs(len(expected_sentences) - len(segments))
        missmatch_penalty = min(0.8, 0.4 * difference)
        if len(expected_sentences) != len(segments):
            segments = self._adjust_segments_to_sentences(segments=segments, sentences=expected_sentences)


        # Calculate the difference in audio length. Penalty 0.3 by second
        audio_length = get_audio_length(audio_path)
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
                            f"Transcribed: {' '.join([segment['text'] for segment in segments])}")
        # Calculate the final quality score (1.0 best quality, 0.0 worst quality)
        penalties = min(1.0, missmatch_penalty + audio_length_penalty + text_penalty)
        score = 1.0 - penalties

        logger.debug(f"Quality score: {score:.2f} (Sentence Mismatch: {missmatch_penalty:.2f} "
                     f"({original_segments_count} vs {len(expected_sentences)}), "
                     f"Audio Lenght Missmatch: {audio_length_penalty:.2f} ({start_difference:.2f} + {end_difference:.2f}), "
                     f"Text Mismatch: {text_penalty:.2f} (dist: {distance})")

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
            segments = self._adjust_segments_to_sentences(segments=segments, sentences=sentences)
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

    def _adjust_segments_to_sentences(self, segments, sentences):
        """
        Adjusts the segments to ensure the count matches the sentence count.
        This involves merging segments if there are more segments than sentences,
        or distributing sentences if there are more sentences than segments.
        """

        if len(segments) == len(sentences):
            return segments # No adjustment needed

        # More segments than sentences, need to merge segments
        if len(segments) > len(sentences):
            logger.info("Merging segments to match sentence count.")
            # Generate all possible combinations of merging segments
            best_combination = self._find_best_segment_combination(segments=segments, sentences=sentences)
            return best_combination

        # More sentences than segments, need to split sentences across segments
        elif len(segments) < len(sentences):
            logger.info("Splitting sentences to match segment count.")
            adjusted_segments = []
            sentence_index = 0

            for segment in segments:
                # Calculate the number of words in the segment and split sentences accordingly
                segment_word_count = len(segment['text'].split())
                current_sentence_words = sentences[sentence_index].split()

                while segment_word_count > len(current_sentence_words) and sentence_index < len(sentences) - 1:
                    sentence_index += 1
                    current_sentence_words.extend(sentences[sentence_index].split())

                adjusted_segments.append({
                    'start': segment['start'],
                    'end': segment['end'],
                    'text': " ".join(current_sentence_words),
                    'words': segment['words']  # Keep the original words
                })
                sentence_index += 1

            return adjusted_segments

    def _find_best_segment_combination(self, segments, sentences):
        """
        Generate all possible combinations of merged segments to match the number of sentences.
        Then, select the combination with the lowest total edit distance to the sentences.
        """
        segment_texts = [segment['text'].strip() for segment in segments]
        possible_combinations = self._generate_combinations(segments, len(sentences))
        best_combination, best_distance = None, float('inf')

        for combination in possible_combinations:
            total_distance = sum(edit_distance(combination[i]['text'].strip().lower(),
                                               sentences[i].strip().lower()) for i in range(len(sentences)))
            if total_distance < best_distance:
                best_distance, best_combination = total_distance, combination

        """
        # Create new segments based on the best combination
        adjusted_segments = []
        segment_index = 0
        for combined_text in best_combination:
            start_time = segments[segment_index]['start']
            end_time = segments[segment_index]['end']
            merged_words = segments[segment_index]['words']

            while len(" ".join([s['text'] for s in
                                segments[segment_index:segment_index + len(combined_text.split())]]).split()) < len(
                    combined_text.split()):
                segment_index += 1
                merged_words.extend(segments[segment_index]['words'])
                end_time = segments[segment_index]['end']

            adjusted_segments.append({
                'start': start_time,
                'end': end_time,
                'text': combined_text,
                'words': merged_words
            })
            segment_index += 1
        """
        return best_combination


    def _generate_combinations(self, segments, target_length):
        """
        Generate all possible combinations of merging segments to reduce the number of segments
        to match the number of sentences.
        """

        def combine_segments(segments, target_length):
            if len(segments) == target_length:
                return [segments]

            result = []
            for i in range(1, len(segments)):
                for j in range(i + 1, len(segments) + 1):
                    merged_segment = self.segments_merge(segments[i-1:j])
                    remaining_segments = segments[:i - 1] + [merged_segment] + segments[j:]
                    if len(remaining_segments) == target_length:
                        result.append(remaining_segments)
                    elif len(remaining_segments) > target_length:
                        result.extend(combine_segments(remaining_segments, target_length))
            return result

        return combine_segments(segments, target_length)

    def segments_merge(self, segments_list: list[dict[str, str]]) -> dict[str, str]:
        """
        Merge segments that are too short or too long.
        """
        current_segment = deepcopy(segments_list[0])
        for segment in segments_list[1:]:
            current_segment['text'] = f"{current_segment['text'].strip()} {segment['text'].strip()}"
            current_segment['end'] = segment['end']
            current_segment['words'].extend(segment['words'])
            current_segment['tokens'].extend(segment['tokens'])


        return current_segment

    def _format_time_srt(self, time_in_seconds: float) -> str:
        hours, remainder = divmod(time_in_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{milliseconds:03}"

    def _generate_sentence_srt(self, segments, srt_file_path):
        with open(srt_file_path, 'w') as f:
            for i, segment in enumerate(segments, start=1):
                start_time = segment['start']
                end_time = segment['end']
                text = segment['text'].strip()
                f.write(f"{i}\n")
                f.write(f"{self._format_time_srt(start_time)} --> {self._format_time_srt(end_time)}\n")
                f.write(f"{text}\n\n")

    def _generate_word_srt(self, segments, srt_file_path):
        with open(srt_file_path, 'w') as f:
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

def get_audio_length(audio_path: str) -> float:
    with wave.open(audio_path, 'r') as audio_file:
        frames = audio_file.getnframes()
        rate = audio_file.getframerate()
        duration = frames / float(rate)
    return duration

if __name__ == '__main__':
    file = 'audio-test.wav'

    whisper = Whisper()
    whisper.audio_file_to_srt(file, 'output-test.srt')