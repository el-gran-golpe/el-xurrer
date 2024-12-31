import os

PERRO_SANXE = 'perro_sanxe'
LOLI = 'loli'
LOLI2 = 'loli2'
LOLI_ANGRY = 'loli_angry'
MISTERIOUS_VOICE = 'misterious_voice'

AUDIO_PATH = 'path'
AUDIO_TEXT = 'text'

VOICE_SOURCES = {
    PERRO_SANXE: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'perro_sanxe.wav'),
        AUDIO_TEXT: 'Entonces, nace la original teoria, del no soy presidente por que no quiero'
    },
    LOLI: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'loli.wav'),
        AUDIO_TEXT: 'Así es como es como un susurro así también. Para... eh... sentir un poco de, seducción'
    },
    LOLI2: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'loli2.wav'),
        AUDIO_TEXT: 'También aprendan la escritura japonesa. Aunque... Yo no... No se muy... La escritura japonesa. '
                    'Pero, solamente... he aprendido, eh... Palabras en japonés con el traductor de Google'
    },
    LOLI_ANGRY: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'loli_angry.wav'),
        AUDIO_TEXT: 'No tomen Monster ¡No tomen Monster!. ¡La Monster es mala! ¡La Monster es mala!'
    },
    MISTERIOUS_VOICE: {
        AUDIO_PATH: os.path.join(os.path.dirname(__file__), 'source_voices', 'misterious_voice.wav'),
        AUDIO_TEXT: 'Blanco, o frio... Con olor a proxima podredumbre'
    }
}