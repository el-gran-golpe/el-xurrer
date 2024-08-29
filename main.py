import os
from pipeline.pipeline import Pipeline
from chat_gpt.chat_gpt import ChatGPT
from loguru import logger
import json

OUTPUT_FOLDER = 'youtube_channels/Mitologia/vikinga/hela'
PROMPT_TEMPLATE_PATH = 'chat_gpt/prompts/youtube/mithology.json'
DURATION = 5
LANG = 'es'
PROMPT = "Hela, la diosa de la muerte en la mitología nórdica"


if __name__ == '__main__':

    if not os.path.isdir(OUTPUT_FOLDER) or not os.path.isfile(os.path.join(OUTPUT_FOLDER, 'script.json')):
        logger.info(f"Generating script for the folder: {OUTPUT_FOLDER}")
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        script = ChatGPT().generate_script(duration=DURATION, lang=LANG, prompt_template_path=PROMPT_TEMPLATE_PATH,
                                           prompt=PROMPT)

        with open(os.path.join(OUTPUT_FOLDER, 'script.json'), 'w') as f:
            json.dump(script, f, indent=4, ensure_ascii=False)


    assert os.path.isfile(os.path.join(OUTPUT_FOLDER, 'script.json')), "Script file not found"
    Pipeline(output_folder=OUTPUT_FOLDER).generate_video()