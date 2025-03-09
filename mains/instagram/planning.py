import os
import json
from llm.instagram.instagram_llm import InstagramLLM
from utils.utils import read_initial_conditions

def generate_instagram_planning(planning_template_folder, output_folder_base_path_planning):
    """
    Generate Instagram planning based on template files.
    """
    assert os.path.isdir(planning_template_folder), f"Planning template folder not found: {planning_template_folder}"
    
    # 1) Gather all available .json planning templates under planning_template_folder
    available_plannings = []
    for root, dirs, files in os.walk(planning_template_folder):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            planning_found = False
            for file_name in os.listdir(dir_path):
                if file_name.endswith('.json'):
                    # The folder name should match the JSON file name (minus '.json')
                    assert file_name[:-len('.json')] == dir_name, f"Mismatch: {dir_name} != {file_name[:-5]}"
                    if file_name == f"{dir_name}.json":
                        available_plannings.append(os.path.join(dir_path, file_name))
                        planning_found = True
            if not planning_found:
                print(f"Warning: No planning file found for folder: {dir_name}")

    print("Available planning templates:")
    for i, template in enumerate(available_plannings):
        grandparent_folder = os.path.basename(os.path.dirname(os.path.dirname(template)))
        parent_folder = os.path.basename(os.path.dirname(template))
        print(f"{i + 1}: {grandparent_folder}\\{parent_folder}")
    
    # 2) Prompt the user to select one or more templates (or 'all')
    template_input = input("Select template numbers separated by commas or type 'all' to process all: ")
    if template_input.lower() == 'all':
        selected_templates = available_plannings
    else:
        template_indices = [int(index.strip()) - 1 for index in template_input.split(',')]
        for index in template_indices:
            assert 0 <= index < len(available_plannings), f"Invalid template number: {index + 1}"
        selected_templates = [available_plannings[index] for index in template_indices]
      
    # 3) Figure out which of these selected templates already have an existing output file
    existing_files = []
    not_existing_files = []
    
    for template_path in selected_templates:
        profile_name = os.path.basename(os.path.dirname(template_path))
        profile_initials = ''.join([word[0] for word in profile_name.split('_')])
        planning_filename = f"{profile_initials}_planning.json"
        
        output_path = os.path.join(output_folder_base_path_planning, profile_name)
        os.makedirs(output_path, exist_ok=True)
        
        full_output_path = os.path.join(output_path, planning_filename)
        if os.path.isfile(full_output_path):
            existing_files.append((template_path, full_output_path))
        else:
            not_existing_files.append((template_path, full_output_path))

    # If we have existing files, ask user for permission to overwrite them
    overwrite_all = False
    if existing_files:
        print("\nThe following planning files already exist and would be overwritten:")
        for (_, fpath) in existing_files:
            print(f"  {fpath}")
        
        overwrite_input = input("Do you want to overwrite these existing files? (y/n): ")
        overwrite_all = overwrite_input.lower() in ('y', 'yes')
    
    # 4) Combine the list of all to-be-processed files,
    #    but skip the existing ones if user doesn't want to overwrite
    final_templates = []
    for (template_path, output_path) in existing_files:
        if overwrite_all:
            final_templates.append((template_path, output_path))
        else:
            print(f"Skipping overwrite for {output_path}")

    # Add the files that don't exist yet (always processed)
    for (template_path, output_path) in not_existing_files:
        final_templates.append((template_path, output_path))
    
    # 5) Now do the actual generation for everything in final_templates
    for (template_path, full_output_path) in final_templates:
        profile_name = os.path.basename(os.path.dirname(template_path))
        
        # Read previous storyline
        previous_storyline = read_initial_conditions(
            os.path.join(os.path.dirname(template_path), 'initial_conditions.md')
        )
        
        # Attempt generation repeatedly if JSONDecodeError occurs
        while True:
            try:
                planning = InstagramLLM().generate_instagram_planning(
                    prompt_template_path=template_path,
                    previous_storyline=previous_storyline
                )
                break
            except (json.decoder.JSONDecodeError, TypeError) as e:
                print(f"Error decoding JSON or TypeError: {e}. Retrying...")
                continue
        
        # Finally, save the plan
        with open(full_output_path, 'w', encoding='utf-8') as file:
            json.dump(planning, file, indent=4, ensure_ascii=False)

        print(f"Planning saved to: {full_output_path}")
