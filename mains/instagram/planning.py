import os
import json
from llm.meta_llm import InstagramLLM
from utils.utils import read_initial_conditions

def generate_instagram_planning(planning_template_folder):
    """
    Generate Instagram planning based on template files.
    """
    assert os.path.isdir(planning_template_folder), f"Planning template folder not found: {planning_template_folder}"
    
    # 1) Gather all available .json planning templates under planning_template_folder
    available_plannings = []
    
    # Check for new structure
    for profile_dir in os.listdir(planning_template_folder):
        profile_path = os.path.join(planning_template_folder, profile_dir)
        if os.path.isdir(profile_path):
            inputs_path = os.path.join(profile_path, "inputs")
            if os.path.isdir(inputs_path):
                for file_name in os.listdir(inputs_path):
                    if file_name.endswith('.json'):
                        template_path = os.path.join(inputs_path, file_name)
                        available_plannings.append((profile_dir, template_path, "new"))
    
    # If no templates found, check old structure for backward compatibility
    if not available_plannings:
        old_inputs_path = os.path.join('resources', 'inputs', 'instagram_profiles')
        if os.path.isdir(old_inputs_path):
            for profile_dir in os.listdir(old_inputs_path):
                profile_path = os.path.join(old_inputs_path, profile_dir)
                if os.path.isdir(profile_path):
                    for file_name in os.listdir(profile_path):
                        if file_name.endswith('.json'):
                            template_path = os.path.join(profile_path, file_name)
                            available_plannings.append((profile_dir, template_path, "old"))
                            print(f"Warning: Using template from old structure: {template_path}")
    
    if not available_plannings:
        print("No planning templates found in either new or old structure.")
        return

    print("Available planning templates:")
    for i, (profile, template, structure) in enumerate(available_plannings):
        print(f"{i + 1}: {profile} {'(old structure)' if structure == 'old' else ''}")
    
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
    
    for profile_name, template_path, structure in selected_templates:
        profile_initials = ''.join([word[0] for word in profile_name.split('_')])
        planning_filename = f"{profile_initials}_planning.json"
        
        # Always save to new structure
        output_path = os.path.join(planning_template_folder, profile_name, "outputs")
        os.makedirs(output_path, exist_ok=True)
        
        full_output_path = os.path.join(output_path, planning_filename)
        
        # Check if file exists in new structure
        if os.path.isfile(full_output_path):
            existing_files.append((profile_name, template_path, full_output_path, structure))
        else:
            # Check if it exists in old structure
            old_output_path = os.path.join('resources', 'outputs', 'instagram_profiles', profile_name, planning_filename)
            if os.path.isfile(old_output_path):
                existing_files.append((profile_name, template_path, full_output_path, structure))
                print(f"Note: File exists in old structure. Will be saved to new location: {full_output_path}")
            else:
                not_existing_files.append((profile_name, template_path, full_output_path, structure))

    # If we have existing files, ask user for permission to overwrite them
    overwrite_all = False
    if existing_files:
        print("\nThe following planning files already exist and would be overwritten:")
        for (_, _, fpath, _) in existing_files:
            print(f"  {fpath}")
        
        overwrite_input = input("Do you want to overwrite these existing files? (y/n): ")
        overwrite_all = overwrite_input.lower() in ('y', 'yes')
    
    # 4) Combine the list of all to-be-processed files,
    #    but skip the existing ones if user doesn't want to overwrite
    final_templates = []
    for (profile_name, template_path, output_path, structure) in existing_files:
        if overwrite_all:
            final_templates.append((profile_name, template_path, output_path, structure))
        else:
            print(f"Skipping overwrite for {output_path}")

    # Add the files that don't exist yet (always processed)
    for (profile_name, template_path, output_path, structure) in not_existing_files:
        final_templates.append((profile_name, template_path, output_path, structure))
    
    # 5) Now do the actual generation for everything in final_templates
    for (profile_name, template_path, full_output_path, structure) in final_templates:
        # Read previous storyline - check both structures
        if structure == "new":
            initial_conditions_path = os.path.join(planning_template_folder, profile_name, "inputs", "initial_conditions.md")
        else:
            initial_conditions_path = os.path.join('resources', 'inputs', 'instagram_profiles', profile_name, "initial_conditions.md")
            
        previous_storyline = read_initial_conditions(initial_conditions_path)
        
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
        
        # Always save to new structure location
        with open(full_output_path, 'w', encoding='utf-8') as file:
            json.dump(planning, file, indent=4, ensure_ascii=False)

        print(f"Planning saved to: {full_output_path}")
