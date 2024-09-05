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

# Ordered following LMArena leaderboard https://lmarena.ai/
DEFAULT_PREFERRED_MODELS = ('gpt-4o', 'meta-llama-3.1-405b-instruct', 'gpt-4o-mini', 'mistral-large',
                            'Phi-3-medium-128k-instruct', 'AI21-Jamba-Instruct', 'Phi-3.5-mini-instruct')
PREFERRED_PAID_MODELS = ('gpt-4o-mini', 'gpt-4o')