MOXFIELD_GET_DECK_URL = f"https://api2.moxfield.com/v3/decks/all/{{deck_id}}"

SCRYFALL_IMAGE_URL = f"https://cards.scryfall.io/png/front/{{first_letter}}/{{second_letter}}/{{uuid}}.png"

COLOR_TO_LAND = {
    'blue': 'U',
    'white': 'W',
    'black': 'B',
    'red': 'R',
    'green': 'G',
}

CARD_TYPE_ORDER = {
    'creature': 1,
    'planeswalker': 2,
    'artifact': 3,
    'enchantment': 4,
    'instant': 5,
    'sorcery': 6,
    'other': 7,
    'basic land': 8,
    'land': 9,
}

ORDER_BY_ROLE = {
    'commander': 0,
    'main': 1,
}