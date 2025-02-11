OPENAI, AZURE = 'openai', 'azure'

MODEL_BY_BACKEND = {
    'o1': OPENAI,
    'o1-preview': OPENAI,
    'o1-mini': OPENAI,
    'o3-mini': OPENAI,
    'gpt-4o': OPENAI,
    'gpt-4o-mini': OPENAI,
    'DeepSeek-R1': AZURE,
    'mistral-large': AZURE,
    'Meta-Llama-3.1-405B-Instruct': AZURE,
    'Meta-Llama-3.1-70B-Instruct': AZURE,
    'Llama-3.3-70B-Instruct': AZURE,
    'Phi-3-medium-128k-instruct': AZURE,
    'Phi-3.5-mini-instruct': AZURE,
    'Phi-3.5-MoE-instruct': AZURE,
    'Mistral-large-2411': AZURE,
    'Mistral-large': AZURE,
    'Mistral-Nemo': AZURE,

}

# Ordered following LMArena leaderboard https://lmarena.ai/
DEFAULT_PREFERRED_MODELS = ('gpt-4o', 'gpt-4o-mini',
                            'o1-mini', 'o1-preview', 'o1',
                            'o3-mini', 'DeepSeek-R1',
                            'Llama-3.3-70B-Instruct',
                            'Meta-Llama-3.1-405B-Instruct',
                            'Meta-Llama-3.1-70B-Instruct',
                            'Phi-3-medium-128k-instruct',
                            'Phi-3.5-mini-instruct',
                            'Phi-3.5-MoE-instruct',
                            'Mistral-large-2411',
                            'Mistral-large',
                            'Mistral-Nemo')

LARGER_OUTPUT_MODELS = ('o1', 'o3-mini', 'o1-mini', 'o1-preview')

MODELS_NOT_ACCEPTING_SYSTEM_ROLE = ('o1', 'o3-mini', 'o1-mini', 'o1-preview')
MODELS_NOT_ACCEPTING_STREAM = ('o1', 'o3-mini', 'o1-mini', 'o1-preview')
REASONING_MODELS = ('o1', 'o3-mini', 'o1-mini', 'o1-preview')

PREFERRED_PAID_MODELS = ('gpt-4o-mini', )

MODELS_ACCEPTING_JSON_FORMAT = ('Mistral-large', 'Mistral-large-2411', 'Mistral-Nemo', 'Meta-Llama-3.1-70B-Instruct',
                                'Meta-Llama-3.1-405B-Instruct', 'Llama-3.3-70B-Instruct', 'gpt-4o', 'gpt-4o-mini', 'o1', 'o1-mini', 'o1-preview',
                                'o3-mini')
MODELS_INCLUDING_CHAIN_THOUGHT = ('DeepSeek-R1', )
CANNOT_ASSIST_PHRASES = ("I'm sorry, I can't assist with that", "Lo siento, no puedo procesar esa solicitud", "Lo siento, no puedo hacer eso.")


VALIDATION_SYSTEM_PROMPT = ("You are a categorization assistant tasked with analyzing the finish_reason "
                            "of a provided user prompt output.\n"
                            "Your role is to classify the finish_reason into one of the following categories:\n\n"
                            "\t- 'stop': The output is complete and looks like a satisfactory answer.\n"
                            "\t- 'length': The output appears incomplete. Look for markers such as phrases like "
                            "\"Due to character limitations I will continue in the next comments...\", \"This pattern continues exhaustively through...\" or "
                            "\"Continuaré con las secciones restantes en los siguientes comentarios...\"."
                            "\t- 'content_filter': The output was not completed due to a content filter being triggered. "
                            "Common markers include phrases like \"I can't assist with that task\" or similar wording.\n\n"
                            "You must return the result in the following JSON format:\n\n"
                            "```json \n"
                            "{\n"
                            "\"finish_reason\": \"<one of: stop, length, content_filter>\",\n"
                            "\"markers\": [\"<list of the exact phrases contained in the text, "
                            "from which the finish reason was inferred, leave empty if 'stop'>\"]\n"
                            "}\n"
                            "```\n"
                            "When the finish_reason is 'stop', the \"markers\" field must be an empty array.\n"
                            "Ensure that all markers are exact matches to facilitate downstream processing. "
                            "Include any surrounding special character linked to that markers in the text, "
                            "like '\"', '.', '*', ... \n"
                            "Be concise and focus solely on the categorization task.\n"
                            "Your output must include ONLY a single JSON object with the keys 'finish_reason' "
                            "and 'markers'. Without further context or additional information.\n"
                            )
