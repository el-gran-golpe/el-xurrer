from utils.mtg.mtg_deck_querier import MoxFieldDeck

if __name__ == '__main__':
    deck = MoxFieldDeck(deck_id='pagSTJu8jkafskzIH1hGMw')
    deck = deck.get_deck_info()
    card = deck.get_card('Black Lotus')
    print(card.name)