import os

PERRO_SANXE = 'perro_sanxe'
LOLI = 'loli'
MISTERIOUS_VOICE = 'misterious_voice'
MISTERIOUS_VOICE_ENGLISH = 'misterious_voice_english'
NOELLE = 'noelle'

AUDIO_PATH = 'path'
AUDIO_TEXT = 'text'
LANG = 'lang'
REQUIRES_SILENCE_REMOVAL = 'requires_silence_removal'
FROM_DATASET = 'from_dataset'

VOICE_SOURCES = {
    PERRO_SANXE: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'perro_sanxe.wav'),
        AUDIO_TEXT: 'Entonces, nace la original teoria, del no soy presidente por que no quiero',
        LANG: 'es',
        REQUIRES_SILENCE_REMOVAL: False,
        FROM_DATASET: False
    },
    LOLI: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'english_loli.wav'),
        AUDIO_TEXT: "I'd like to ask you a favor because I'm suddenly curious. Can you speak in a higher pitch voice? It would be really Gatmoe!",
        LANG: 'en',
        REQUIRES_SILENCE_REMOVAL: True,
        FROM_DATASET: False

    },
    MISTERIOUS_VOICE: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'misterious_voice.wav'),
        AUDIO_TEXT: 'Blanco, o frio... Con olor a proxima podredumbre',
        LANG: 'es',
        REQUIRES_SILENCE_REMOVAL: False,
        FROM_DATASET: True
    },
    MISTERIOUS_VOICE_ENGLISH: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'misterious_voice_english.wav'),
        AUDIO_TEXT: "A chance to leave him alone, but... No. She just wanted to see him again. Anna, you don't know how it feels to lose a sister.",
        LANG: 'en',
        REQUIRES_SILENCE_REMOVAL: True,
        FROM_DATASET: True
    },
    NOELLE: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'noelle.wav'),
        AUDIO_TEXT: "My name is Noelle, maid of the Knights of Favonius, and it's my pleasure to be joininh you on your adventure today. "
                    "Should you encounter any problems at all at any point throughout your journey, please do not hesitate to call me and "
                    "I will be delighted to provide you with my full assistance. Yes, starting right now - what do you need?",
        LANG: 'en',
        REQUIRES_SILENCE_REMOVAL: False,
        FROM_DATASET: False
    }
}