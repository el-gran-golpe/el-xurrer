import os
import shutil
import json

def migrate_resources():
    """
    Migrate from old resource structure to new profile-based structure.
    """
    old_inputs_path = os.path.join('.', 'resources', 'inputs', 'instagram_profiles')
    old_outputs_path = os.path.join('.', 'resources', 'outputs', 'instagram_profiles')
    new_base_path = os.path.join('.', 'resources', 'instagram_profiles')
    
    os.makedirs(new_base_path, exist_ok=True)
    
    # Get all profile names from inputs and outputs
    input_profiles = set()
    output_profiles = set()
    
    if os.path.exists(old_inputs_path):
        input_profiles = {d for d in os.listdir(old_inputs_path) 
                         if os.path.isdir(os.path.join(old_inputs_path, d))}
    
    if os.path.exists(old_outputs_path):
        output_profiles = {d for d in os.listdir(old_outputs_path) 
                          if os.path.isdir(os.path.join(old_outputs_path, d))}
    
    # Union of all profile names
    all_profiles = input_profiles.union(output_profiles)
    
    for profile in all_profiles:
        print(f"Migrating profile: {profile}")
        
        # Create new structure
        new_profile_path = os.path.join(new_base_path, profile)
        new_inputs_path = os.path.join(new_profile_path, 'inputs')
        new_outputs_path = os.path.join(new_profile_path, 'outputs')
        
        os.makedirs(new_inputs_path, exist_ok=True)
        os.makedirs(new_outputs_path, exist_ok=True)
        
        # Move inputs if they exist
        old_profile_inputs = os.path.join(old_inputs_path, profile)
        if os.path.exists(old_profile_inputs):
            for item in os.listdir(old_profile_inputs):
                src = os.path.join(old_profile_inputs, item)
                dst = os.path.join(new_inputs_path, item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    print(f"  Copied: {src} -> {dst}")
                elif os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    print(f"  Copied directory: {src} -> {dst}")
        
        # Move outputs if they exist
        old_profile_outputs = os.path.join(old_outputs_path, profile)
        if os.path.exists(old_profile_outputs):
            for item in os.listdir(old_profile_outputs):
                src = os.path.join(old_profile_outputs, item)
                dst = os.path.join(new_outputs_path, item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    print(f"  Copied: {src} -> {dst}")
                elif os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    print(f"  Copied directory: {src} -> {dst}")
    
    print("\nMigration complete. Please verify the new structure before removing old directories.")
    print("To remove old directories after verification, run:\n")
    print(f"import shutil")
    print(f"shutil.rmtree('{old_inputs_path.replace(os.sep, '/')}', ignore_errors=True)")
    print(f"shutil.rmtree('{old_outputs_path.replace(os.sep, '/')}', ignore_errors=True)")

if __name__ == "__main__":
    migrate_resources()
