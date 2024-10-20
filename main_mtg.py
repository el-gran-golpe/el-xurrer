import os
import os

from llm.youtube.youtube_mtg_llm import YoutubeMTGLLM
from pipeline.youtube.mtggarden_pipeline import MTGGardenPipeline
from pipeline.youtube.pipeline import Pipeline
from llm.youtube.youtube_llm import YoutubeLLM
from loguru import logger
from time import sleep
import json
from slugify import slugify
from tqdm import tqdm

from utils.exceptions import WaitAndRetryError
from utils.utils import missing_video_assets
from utils.mtg.mtg_deck_querier import MoxFieldDeck

PLANNING_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'youtube', 'prompts', 'planning')
VIDEOS_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'youtube', 'prompts', 'videos')

PROBABLE_OUTPUT_FOLDER_BASE_PATHS = [os.path.join('.', 'youtube_channels'), os.path.join('H:', 'Otros ordenadores', 'My Mac', 'youtube_channels')]
for output_folder in PROBABLE_OUTPUT_FOLDER_BASE_PATHS:
    if os.path.isdir(output_folder):
        OUTPUT_FOLDER_BASE_PATH = output_folder
        logger.info(f"Output folder: {output_folder}")
        break
else:
    raise FileNotFoundError("Output folder not found")

OUTPUT_FOLDER_BASE_PATH_VIDEOS = os.path.join(OUTPUT_FOLDER_BASE_PATH, 'videos')
OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join(OUTPUT_FOLDER_BASE_PATH, 'planning', 'mtg')

def generate_videos():
    assert os.path.isdir(OUTPUT_FOLDER_BASE_PATH_PLANNING), f"Planning folder not found: {OUTPUT_FOLDER_BASE_PATH_PLANNING}"

    # Ask the user for which channel wanna generate the videos
    available_plannings = [template[:-len('.json')] for template in os.listdir(OUTPUT_FOLDER_BASE_PATH_PLANNING)
                           if template.endswith('.json')]
    assert len(available_plannings) > 0, "No planning files found, please generate a planning first"
    print("Available planning files:")
    if len(available_plannings) == 1:
        channel_index = 0
    else:
        for i, channel in enumerate(available_plannings):
            output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_VIDEOS, channel)
            if not os.path.isdir(output_path):
                subtext = "(New)"
            else:
                subtext = f"(Existent lists: {len(os.listdir(output_path))})"
            print(f"{i + 1}: {channel} {subtext}")
        channel_index = int(input("Select a channel number: ")) - 1
    assert 0 <= channel_index < len(available_plannings), "Invalid channel number"
    channel_name = available_plannings[channel_index]

    prompt_template_path =  os.path.join(VIDEOS_TEMPLATE_FOLDER, f"{channel_name}.json")
    assert os.path.isfile(prompt_template_path), f"Prompt template file not found: {prompt_template_path}"

    output_folder = os.path.join(OUTPUT_FOLDER_BASE_PATH_VIDEOS, channel_name)
    os.makedirs(output_folder, exist_ok=True)

    # Read the planning
    with open(os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, f"{channel_name}.json"), 'r', encoding='utf-8') as file:
        planning = json.load(file)

    for list_name, deck_url_ids in planning.items():
        slug_list_name = slugify(list_name)
        for deck_id in tqdm(deck_url_ids, desc=f"Generating videos for {list_name}", total=len(deck_url_ids)):
            deck = MoxFieldDeck(deck_id=deck_id)
            slug_deck_name = slugify(deck.name)
            output_path = os.path.join(output_folder, slug_list_name, slug_deck_name)
            if not os.path.isdir(output_path):
                os.makedirs(output_path)
            script_path = os.path.join(output_path, 'script.json')
            if not os.path.isfile(script_path):
                script = YoutubeMTGLLM().generate_script(deck=deck,
                                                      prompt_template_path=prompt_template_path)
                with open(script_path, 'w', encoding='utf-8') as f:
                    json.dump(script, f, indent=4, ensure_ascii=False)

            assert os.path.isfile(script_path), "Script file not found"

            # If the video file already exists, skip it
            #if not missing_video_assets(assets_path=output_path):
                #continue

            for retrial in range(25):
                try:
                    MTGGardenPipeline(output_folder=output_path, deck=deck).generate_video()
                    break
                except WaitAndRetryError as e:
                    sleep_time = e.suggested_wait_time
                    hours, minutes, seconds = sleep_time // 3600, sleep_time // 60 % 60, sleep_time % 60

                    for _ in tqdm(range(100),
                                  desc=f"Waiting {str(hours)}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}"):
                        sleep(sleep_time / 100)



if __name__ == '__main__':

        generate_videos()

"""
if __name__ == '__main__':
    deck = MoxFieldDeck(deck_id='pagSTJu8jkafskzIH1hGMw')
    deck = deck.get_deck_info()
    for card in deck['deck_list']:
        print(card['plain_text_description'])
        print("\n")
"""