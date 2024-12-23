import os

PERRO_SANXE = 'perro_sanxe'

AUDIO_PATH = 'path'
AUDIO_TEXT = 'text'

VOICE_SOURCES = {
    PERRO_SANXE: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'perro_sanxe.wav'),
        AUDIO_TEXT: 'Entonces, nace la original teoria, del no soy presidente por que no quiero'
    }
}