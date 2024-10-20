import os
import json
from collections import defaultdict
from copy import deepcopy

from llm.base_llm import BaseLLM
from llm.constants import DEFAULT_PREFERRED_MODELS
from tqdm import tqdm

from utils.exceptions import InvalidScriptException
from utils.mtg.mtg_deck_querier import MoxFieldDeck
from utils.utils import get_closest_monday, generate_ids_in_script, check_script_validity, generate_ids_in_dict
import re
from loguru import logger



class YoutubeMTGLLM(BaseLLM):
    def __init__(self, preferred_models: list|tuple = DEFAULT_PREFERRED_MODELS):
        super().__init__(preferred_models=preferred_models)

    def generate_script(self, prompt_template_path: str, deck: MoxFieldDeck, retries: int = 3) -> dict:

        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(deck, MoxFieldDeck), f"Invalid deck object: {deck}"
        assert retries > 0, "Retries must be a positive integer"
        with open(prompt_template_path, 'r', encoding='utf-8') as file:
            prompt_template = json.load(file)

        prompts_definition = prompt_template["prompts"]
        prefill_cache = {
            'deck': deck.deck_list_description,
            'format': deck.format,
            'moxfield_deck_structure': deck
        }

        for retry in range(retries):
            try:
                script = self._generate_dict_from_prompts(prompts=prompts_definition, preferred_models=self.preferred_models,
                                                          cache=prefill_cache, desc="Generating script")
                script = generate_ids_in_dict(dict_to_fill=script, leaf_suggestions=('card_name',))
                break
            except InvalidScriptException as e:
                logger.error(f"Error generating script: {e}. Retry {retry + 1}/{retries}")

        else:
            raise InvalidScriptException(f"Error generating script after {retries} retries")
        return script

    def generate_youtube_planning(self, prompt_template_path: str, list_count: int = 6) -> dict:
        assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"
        assert isinstance(list_count, int) and list_count > 0, "Videos count must be a positive integer"

        with open(prompt_template_path, 'r', encoding='utf-8') as file:
            prompt_template = json.load(file)

        prompts = prompt_template["prompts"]
        lang = prompt_template["lang"]
        assert isinstance(prompts, list), "Prompts must be a list"
        assert len(prompts) > 0, "No prompts found in the prompt template file"

        monday_date = get_closest_monday().strftime('%Y-%m-%d')
        monday = 'Lunes' if lang == 'es' else 'Monday'
        day = f"{monday} {monday_date}"
        prompts[0]['prompt'] = prompts[0]['prompt'].format(list_count=list_count)
        prompts[1]['system_prompt'] = prompts[1]['system_prompt'].format(day=day)

        planning = self._generate_dict_from_prompts(prompts=prompts, preferred_models=self.preferred_models,
                                                    desc="Generating planning")
        return planning



    def build_card_descriptions(self, cache: dict, system_prompt: str,
                                      prompt: str, preferred_models: list[str]) -> dict:
        categories = self.decode_json_from_message(message=cache['deck_categories'])
        assert 'categories' in categories and len(categories) == 1, "Invalid categories data"
        categories_dict = categories['categories']
        deck = cache['moxfield_deck_structure'].get_deck_info()
        categories = self._improve_card_categories(categories_dict=categories_dict, deck=deck, cache=cache)
        deck_list = deck['deck_list_by_card_name']
        responses = []
        for category_info in categories:
            category, category_description = category_info['category'], category_info['category_description']
            card_names = category_info['cards']

            card_descriptions = {card_name: deck_list[card_name]['plain_text_description']
                                 for card_name in card_names if card_name in deck_list}

            category_prompt = (prompt.replace("{category}", category).
                               replace('{category_description}', category_description).
                               replace("{cards_description}", '\n\n'.join(f"{name}:\n{description}"
                                                                          for name, description in card_descriptions.items())))

            conversation = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'system', 'content': category_prompt}
            ]

            assistant_reply, _ = self.get_model_response(conversation=conversation,
                                                      preferred_models=preferred_models)

            assistant_reply = self.decode_json_from_message(message=assistant_reply)

            responses.append(assistant_reply)
        return {'categories': responses}



    def _improve_card_categories(self, categories_dict: list[dict[str, str|dict]], deck: dict, cache: dict) -> list[dict]:
        categories = deepcopy(categories_dict)
        categories = self.solve_card_typos(categories=categories, deck=deck)

        category_map = {cat['category']: cat for cat in categories}

        # Map cards to their categories
        card_to_categories = defaultdict(set)
        for cat in categories:
            for card in cat['cards']:
                card_to_categories[card].add(cat['category'])

        # Identify cards needing reclassification
        cards_in_multiple_categories = {card for card, cats in card_to_categories.items() if len(cats) > 1}
        deck_cards = {card['name'] for card in deck['deck_list']}
        categorized_cards = set(card_to_categories.keys())
        missing_cards = deck_cards - categorized_cards
        cards_to_reclassify = missing_cards | cards_in_multiple_categories

        if not cards_to_reclassify:
            return categories

        # Prepare descriptions for the cards to reclassify
        cards_description = '\n\n'.join(
            deck['deck_list_by_card_name'][card]['plain_text_description']
            for card in cards_to_reclassify
        )

        # Build the prompts for the model
        categories_str = ', '.join(category_map.keys())
        system_prompt = (
            f"Eres un experto en Magic: The Gathering y análisis de mazos de {deck['format']}. "
            "Se te proporcionará una descripción de la estrategia del mazo, y una lista con algunas de las cartas que contiene.\n"
            f"Tu trabajo es categorizar las cartas del mazo en una de las siguientes categorias: {categories_str}.\n"
            "Todas las cartas deben incluirse en una y solo una categoría. "
            "Si una carta podría pertenecer a varias categorías, elige la más relevante dada la estrategia del mazo."
        )

        prompt = (
            f"Descripción de la estrategia: \n{cache['deck_summary']}\n\n"
            f"Lista de Categorías: {categories_str}\n\n"
            "Lista de Cartas: \n\n"
            f"{cards_description}\n\n"
            "Genera un JSON donde cada categoría está asociada a una lista de cartas que pertenecen a ella. "
            "Cada carta debe estar en una y solo una categoría, eligiendo la más relevante si corresponde a múltiples categorías.\n\n"
            "El output debe ser exclusivamente este JSON, sin comentarios ni explicaciones adicionales.\n\n"
            "Formato de salida esperado:\n\n"
            "```json\n{\"categories\": [\n"
            "{\"category\": \"<category_name>\",\n"
            "\"cards\": [\"<card_name1>\", \"<card_name2>\", ...]\n},\n"
            "...]\n}```"
        )

        conversation = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'system', 'content': prompt}
        ]

        assistant_reply, _ = self.get_model_response(
            conversation=conversation,
            preferred_models=self.preferred_models
        )

        # Decode and validate the model's response
        new_categories_data = self.decode_json_from_message(message=assistant_reply)
        assert 'categories' in new_categories_data and len(new_categories_data) == 1, "Invalid response from the model"
        new_categories = new_categories_data['categories']

        if not new_categories:
            raise InvalidScriptException("Invalid response from the model")

        # Remove reclassified cards from existing categories
        for cat in categories:
            cat['cards'] = [card for card in cat['cards'] if card not in cards_to_reclassify]

        # Add reclassified cards to their new categories
        for new_cat in new_categories:
            category_name = new_cat['category']
            if category_name not in category_map:
                raise InvalidScriptException(f"Invalid category {category_name} in the response")
            category_map[category_name]['cards'].extend(new_cat['cards'])

        categories = self.solve_card_typos(categories=categories, deck=deck)

        return categories

    def solve_card_typos(self, categories: list, deck: dict) -> list:
        deck_card_names = set(deck['deck_list_by_card_name'].keys())

        for category_entry in categories:
            card_list = category_entry.get('cards', [])
            for i, card in enumerate(card_list):
                if card not in deck_card_names:
                    # Find a matching card name in the deck
                    matching_card = next(
                        (deck_card_name for deck_card_name in deck_card_names
                         if deck_card_name.startswith(card) or deck_card_name.endswith(card)),
                        card  # Keep original card if no match is found
                    )
                    if matching_card is None:
                        logger.warning(f"Could not find a matching card for {card}")
                    card_list[i] = matching_card
        return categories

