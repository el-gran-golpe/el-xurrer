import os

_this_dir = os.path.dirname(os.path.abspath(__file__))

AVAILABLE_SPEAKERS = ['Claribel Dervla', 'Daisy Studious', 'Gracie Wise', 'Tammie Ema', 'Alison Dietlinde', 'Ana Florence', 'Annmarie Nele', 'Asya Anara', 'Brenda Stern', 'Gitta Nikolina', 'Henriette Usha', 'Sofia Hellen', 'Tammy Grit', 'Tanja Adelina', 'Vjollca Johnnie', 'Andrew Chipper', 'Badr Odhiambo', 'Dionisio Schuyler', 'Royston Min', 'Viktor Eka', 'Abrahan Mack', 'Adde Michal', 'Baldur Sanjin', 'Craig Gutsy', 'Damien Black', 'Gilberto Mathias', 'Ilkin Urbano', 'Kazuhiko Atallah', 'Ludvig Milivoj', 'Suad Qasim', 'Torcull Diarmuid', 'Viktor Menelaos', 'Zacharie Aimilios', 'Nova Hogarth', 'Maja Ruoho', 'Uta Obando', 'Lidiya Szekeres', 'Chandra MacFarland', 'Szofi Granger', 'Camilla Holmström', 'Lilya Stainthorpe', 'Zofija Kendrick', 'Narelle Moon', 'Barbora MacLean', 'Alexandra Hisakawa', 'Alma María', 'Rosemary Okafor', 'Ige Behringer', 'Filip Traverse', 'Damjan Chapman', 'Wulf Carlevaro', 'Aaron Dreschner', 'Kumar Dahl', 'Eugenio Mataracı', 'Ferran Simen', 'Xavier Hayasaka', 'Luis Moray', 'Marcos Rudaski']
DECENT_SPEAKERS_ENGLISH = ["Aaron Dreschner", "Asya Anara", "Badr Odhiambo", "Baldur Sanjin", "Brenda Stern", "Camilla Holmström", "Daisy Studious", "Damien Black", "Dionisio Schuyler", "Ferran Simen", "Filip Traverse", "Gitta Nikolina", "Maja Ruoho", "Narelle Moon", "Nova Hogarth", "Sofia Hellen", "Szofi Granger", "Tanja Adelina", "Torcull Diarmuid", "Uta Obando", "Viktor Menelaos", "Vjollca Johnnie", "Zofija Kendrick"]
TOP_SPEAKERS_SPANISH = ["Gitta Nikolina", "Camilla Holmström", "Viktor Menelaos", "Zofija Kendrick"]



AVAILABLE_EMOTIONS = ('cheerful', 'neutral', 'sad', 'serious', 'empathetic', 'angry', 'happy', 'aaaaaaa')

SAMPLE_VOICES = {
    'random_girl': os.path.join(_this_dir, 'voice_samples', 'sample-voice-1.wav'),
    'haru': os.path.join(_this_dir, 'voice_samples', 'sample-voice-haru.wav'),
}