import scrython
from cachetools.func import ttl_cache
import requests
from utils.mtg.constants import MOXFIELD_GET_DECK_URL, COLOR_TO_LAND, SCRYFALL_IMAGE_URL, CARD_TYPE_ORDER, ORDER_BY_ROLE


class MoxFieldDeck:
    def __init__(self, deck_id: str):
        self.raw_deck = self._get_raw_deck(deck_id=deck_id)

    @property
    def name(self) -> str:
        return self.raw_deck['name']

    @property
    def format(self) -> str:
        return self.raw_deck['format']

    @property
    def deck_list_description(self) -> str:
        deck_list = self.get_deck_list()
        plain_text = '\n\n'.join(card['plain_text_description'] for card in deck_list)
        return plain_text
    @ttl_cache(maxsize=256, ttl=60*60*12)
    def _get_raw_deck(self, deck_id: str) -> dict:
        url = MOXFIELD_GET_DECK_URL.format(deck_id=deck_id)

        response = requests.get(url)
        response.raise_for_status()

        return response.json()


    @ttl_cache(maxsize=1024, ttl=60*60*12)
    def get_deck_list(self) -> list[dict]:
        board = self.raw_deck['boards']['mainboard']['cards']
        format = self.raw_deck['format']
        deck_list = []
        board = []
        if format == 'commander':
            board += list(self.raw_deck['boards']['commanders']['cards'].values())
        board += list(self.raw_deck['boards']['mainboard']['cards'].values())
        for card in board:
            role = 'commander' if card['boardType'] == 'commanders' else 'main'
            quantity, card = card['quantity'], card['card']
            scryfall_uuid = card['scryfall_id']

            card_type = card['type_line'].split('—')[0].strip()
            card_subtype = card['type_line'].split('—')[1].strip() if '—' in card['type_line'] else None
            image_url = SCRYFALL_IMAGE_URL.format(first_letter=scryfall_uuid[0], second_letter=scryfall_uuid[1], uuid=scryfall_uuid)
            plain_text = f"{quantity} {card['name']}"


            card_description = {
                'role': role,
                'plain_text': plain_text,
                'image_url': image_url,
                'name': card['name'],
                'quantity': quantity,
                'card_type': card_type,
                'card_subtype': card_subtype,
                **card
            }
            card_description['plain_text_description'] = self._get_card_plain_text_description(card=card_description)
            deck_list.append(card_description)

        # Order the deck list by card type and then by cmc
        deck_list.sort(key=lambda card: (ORDER_BY_ROLE.get(card['role'], 9e10), card['type'],
                                         card['cmc'], card.get('edhrec_rank', 9e10),
                                         card['card_subtype'] or 'zzz', card['name']))

        return deck_list

    def _get_card_plain_text_description(self, card: dict, is_face: bool = False) -> str:
        full_text_description = ""
        if 'role' in card and card['role'] == 'commander':
            full_text_description += f"[COMMANDER]"
        full_text_description += f"\n{card['quantity']} {card['name']}" if not is_face else f"\t- Face {card['name']}"

        if 'card_faces' in card and len(card['card_faces']) > 1:
            for face in card['card_faces']:
                full_text_description += f"\n{self._get_card_plain_text_description(card=face, is_face=True)}"
            return full_text_description
        full_text_description += f"\n"
        if 'mana_cost' in card and card['mana_cost']:
            full_text_description += f"Cost: {card['mana_cost']}"
        if 'type_line' in card:
            full_text_description += f", Type: {card['type_line']}"

        if 'oracle_text' in card and not card['type_line'].lower().startswith('basic land'):
            if not is_face:
                full_text_description += f"\n{card['oracle_text']}"
            else:
                oracle_text = card['oracle_text'].replace('\n', '\n\t\t')
                full_text_description += f"\n\t\t{oracle_text}"
        if 'power' in card and 'toughness' in card:
            full_text_description += f"\nP/T: {card['power']}/{card['toughness']}" if not is_face else f"\n\t\tP/T: {card['power']}/{card['toughness']}"
        elif 'loyalty' in card:
            full_text_description += f"\nLoyalty: {card['loyalty']}" if not is_face else f"\n\t\tLoyalty: {card['loyalty']}"
        return full_text_description

    def get_deck_info(self) -> dict:
        return {
            'name': self.raw_deck['name'],
            'format': self.raw_deck['format'],
            'moxfield_url': self.raw_deck['publicUrl'],
            'author': ' & '.join(author['displayName'] for author in self.raw_deck['authors']),
            'colors': self.raw_deck['colors'],
            'color_percentages': {COLOR_TO_LAND[color.lower()]: percentage for color, percentage in self.raw_deck['colorPercentages'].items()},
            'deck_list': self.get_deck_list()
        }

    def get_deck_list_as_plain_text(self) -> str:
        deck_list = self.get_deck_list()
        plain_text = '\n'.join(card['plain_text'] for card in deck_list)
        return plain_text


    @ttl_cache(maxsize=1024, ttl=60*60*12)
    def get_card(self, card_name) -> scrython.cards.Named:
        return scrython.cards.Named(fuzzy=card_name)

    @ttl_cache(maxsize=1024, ttl=60*60*12)
    def get_card_by_id(self, card_id) -> scrython.cards.Id:
        return scrython.cards.Id(id=card_id)
