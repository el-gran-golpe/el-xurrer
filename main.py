import os
from pipeline.pipeline import Pipeline
from llm.youtube.youtube_llm import YoutubeLLM
from loguru import logger
from time import sleep
import json
from slugify import slugify
from tqdm import tqdm

EXECUTE_PLANNING = False
PLANNING_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'youtube', 'prompts', 'planning')
VIDEOS_TEMPLATE_FOLDER = os.path.join('.', 'llm', 'youtube', 'prompts', 'videos')
VIDEOS_COUNT = 40

OUTPUT_FOLDER_BASE_PATH_VIDEOS = os.path.join('.', 'youtube_channels', 'videos')
OUTPUT_FOLDER_BASE_PATH_PLANNING = os.path.join('.', 'youtube_channels', 'planning')


def generate_planning():
    assert os.path.isdir(PLANNING_TEMPLATE_FOLDER), f"Planning template folder not found: {PLANNING_TEMPLATE_FOLDER}"
    # Ask the user for which channel wanna generate the planning
    available_plannings = [template for template in os.listdir(PLANNING_TEMPLATE_FOLDER) if template.endswith('.json')]
    print("Available planning templates:")
    for i, template in enumerate(available_plannings):
        output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_VIDEOS, template[:-len('.json')])
        if not os.path.isdir(output_path):
            subtext = "(New)"
        else:
            subtext = f"(Existent lists: {len(os.listdir(output_path))})"
        print(f"{i + 1}: {template[:-len('.json')]} {subtext}")
    template_index = int(input("Select a template number: ")) - 1
    assert 0 <= template_index < len(available_plannings), "Invalid template number"
    template_path = os.path.join(PLANNING_TEMPLATE_FOLDER, available_plannings[template_index])

    channel_name = available_plannings[template_index][:-len('.json')]


    # Generate the planning
    planning = YoutubeLLM().generate_youtube_planning(prompt_template_path=template_path, list_count=6)

    # Save the planning
    output_path = os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, channel_name)
    os.makedirs(output_path, exist_ok=True)

    if os.path.isfile(os.path.join(output_path, 'mitos-y-ritos.json')):
        print(f"Warning: The planning file already exists in the folder: {output_path}")
        overwrite = input("Do you want to overwrite it? (y/n): ")
        if overwrite.lower() not in ('y', 'yes'):
            print("The planning was not saved")
            return

    with open(os.path.join(output_path, 'mitos-y-ritos.json'), 'w') as file:
        json.dump(planning, file, indent=4, ensure_ascii=False)

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
    with open(os.path.join(OUTPUT_FOLDER_BASE_PATH_PLANNING, f"{channel_name}.json"), 'r') as file:
        planning = json.load(file)

    for list_name, videos_in_list in planning.items():
        list_name_slug = slugify(list_name)
        for video_name, video_data in tqdm(videos_in_list.items(), desc=f"Generating videos for {list_name}", total=len(videos_in_list)):
            video_name_slug = slugify(video_name)
            duration, description, thumbnail_text = video_data['duration_minutes'], video_data['description'], video_data['thumbnail_text']
            theme_prompt = f"{video_name} -- {description}"
            output_path = os.path.join(output_folder, list_name_slug, video_name_slug)
            if not os.path.isdir(output_path):
                os.makedirs(output_path)
            script_path = os.path.join(output_path, 'script.json')
            if not os.path.isfile(script_path):
                script = YoutubeLLM().generate_script(duration=duration, theme_prompt=theme_prompt,
                                                   title=video_name,
                                                   prompt_template_path=prompt_template_path)
                with open(script_path, 'w') as f:
                    json.dump(script, f, indent=4, ensure_ascii=False)

            assert os.path.isfile(script_path), "Script file not found"

            # If the video file already exists, skip it
            video_path = os.path.join(output_path, 'video.mp4')
            if os.path.isfile(video_path):
                continue
            Pipeline(output_folder=output_path).generate_video()



if __name__ == '__main__':

    if EXECUTE_PLANNING:
        generate_planning()
    else:
        generate_videos()
        """
        while True:
            try:

            except Exception as e:
                sleep(60*60*2)
        """