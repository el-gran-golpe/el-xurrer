OPENAI, AZURE = 'openai', 'azure'

MODEL_BY_BACKEND = {
    'gpt-4o': OPENAI,
    'gpt-4o-mini': OPENAI,
    'mistral-large': AZURE,
    'meta-llama-3.1-405b-instruct': AZURE,
    'Phi-3-medium-128k-instruct': AZURE,
    'AI21-Jamba-Instruct': AZURE,
    'Phi-3.5-mini-instruct': AZURE,
}

PREFERRED_PAID_MODELS = ('gpt-4o-mini', 'gpt-4o')