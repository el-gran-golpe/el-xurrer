OPENAI, AZURE = 'openai', 'azure'

MODEL_BY_BACKEND = {
    'o1': OPENAI,
    'o1-preview': OPENAI,
    'o1-mini': OPENAI,
    'gpt-4o': OPENAI,
    'gpt-4o-mini': OPENAI,
    'mistral-large': AZURE,
    'Meta-Llama-3.1-405B-Instruct': AZURE,
    'Meta-Llama-3.1-70B-Instruct': AZURE,
    'Phi-3-medium-128k-instruct': AZURE,
    'Phi-3.5-mini-instruct': AZURE,
    'Phi-3.5-MoE-instruct': AZURE,
    'Mistral-large-2411': AZURE,
    'Mistral-large': AZURE,
    'AI21-Jamba-Instruct': AZURE,

}

# Ordered following LMArena leaderboard https://lmarena.ai/
DEFAULT_PREFERRED_MODELS = ('gpt-4o', 'gpt-4o-mini',
                            'o1-mini', 'o1-preview', 'o1',
                            'Meta-Llama-3.1-405B-Instruct',
                            'Meta-Llama-3.1-70B-Instruct'
                            'Phi-3-medium-128k-instruct',
                            'Phi-3.5-mini-instruct',
                            'Phi-3.5-MoE-instruct',
                            'Mistral-large-2411',
                            'Mistral-large',
                            'AI21-Jamba-Instruct')

LARGER_OUTPUT_MODELS = ('o1', 'o1-mini', 'o1-preview')

MODELS_NOT_ACCEPTING_SYSTEM_ROLE = ('o1', 'o1-mini')
MODELS_NOT_ACCEPTING_STREAM = ('o1', 'o1-mini')

PREFERRED_PAID_MODELS = ('gpt-4o-mini', )

CANNOT_ASSIST_PHRASES = ("I'm sorry, I can't assist with that", "Lo siento, no puedo procesar esa solicitud", "Lo siento, no puedo hacer eso.")

INCOMPLETE_OUTPUT_PHRASES = ("Continuaré con las secciones restantes en los siguientes comentarios debido a las limitaciones de longitud",
                             "Continue similarly for the",
                             "following the same structure and guidelines ",
                             "Continue in this format for the remaining",
                             "Continuar las escenas de cada sección",
                             "siguiendo el mismo nivel de detalle y formato, según lo solicitado",
                             "Continue this format for all remaining",
                             "Continue with the detailed descriptions",
                             "(Continues...)",
                             "This pattern continues exhaustively through",
                             "(Continuar...)",
                             "Due to character limitations")