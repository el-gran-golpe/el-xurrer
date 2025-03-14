import os
import importlib

class BaseMain:
    """Base class with common functionality for content generation tools."""
    
    def __init__(self, platform_name=None):
        """Initialize base parameters."""
        self.platform_name = platform_name
    
    def find_available_items(self, base_path, search_pattern=None, subdirs=None, item_type="items"):
        """
        Generic method to find available items (profiles, templates, etc.).
        
        Args:
            base_path: Base directory to search in
            search_pattern: Function to filter file names
            subdirs: List of subdirectories to traverse from base_path
            item_type: Type of items being searched (for display messages)
        
        Returns:
            List of available items (format depends on search_pattern)
        """
        available_items = []
        
        if not os.path.isdir(base_path):
            print(f"Warning: Base path not found: {base_path}")
            return available_items
            
        for item_name in os.listdir(base_path):
            item_path = os.path.join(base_path, item_name)
            
            if os.path.isdir(item_path):
                # If subdirs specified, traverse through them
                current_path = item_path
                valid_path = True
                
                if subdirs:
                    for subdir in subdirs:
                        current_path = os.path.join(current_path, subdir)
                        if not os.path.isdir(current_path):
                            valid_path = False
                            break
                
                if valid_path:
                    if search_pattern:
                        # Apply custom search pattern
                        result = search_pattern(item_name, current_path)
                        if result:
                            available_items.append(result)
                    else:
                        # Default: just return the item name
                        available_items.append(item_name)
                        
        return available_items
    
    def prompt_user_selection(self, available_items, item_type="items", 
                             allow_multiple=True, display_function=None, 
                             not_found_message=None):
        """
        Generic method to prompt user to select from available items.
        
        Args:
            available_items: List of available items to choose from
            item_type: Type of items being selected (for display messages)
            allow_multiple: Whether to allow multiple selections
            display_function: Custom function to display each item
            not_found_message: Custom message to show when no items are found
        
        Returns:
            List of selected items
        """
        if not available_items:
            message = not_found_message or f"No {item_type} found for {self.platform_name}."
            print(message)
            return []

        print(f"\nAvailable {self.platform_name} {item_type}:")
        
        # Display items
        for i, item in enumerate(available_items):
            if display_function:
                display_text = display_function(item)
                print(f"{i + 1}: {display_text}")
            else:
                # Default display based on item type
                if isinstance(item, tuple) and len(item) > 0:
                    print(f"{i + 1}: {item[0]}")
                else:
                    print(f"{i + 1}: {item}")
        
        # Prompt for selection
        if allow_multiple:
            prompt = "\nSelect item numbers separated by commas or type 'all' to process all: "
        else:
            prompt = f"\nSelect {item_type} number: "
            
        user_input = input(prompt)
        
        # Process selection
        try:
            if allow_multiple and user_input.lower() == 'all':
                return available_items
            elif allow_multiple:
                indices = [int(index.strip()) - 1 for index in user_input.split(',')]
                for index in indices:
                    assert 0 <= index < len(available_items), f"Invalid number: {index + 1}"
                return [available_items[index] for index in indices]
            else:  # Single selection
                index = int(user_input.strip()) - 1
                assert 0 <= index < len(available_items), f"Invalid number: {index + 1}"
                return [available_items[index]]
        except (ValueError, AssertionError) as e:
            print(f"Error in selection: {e}")
            return []
        
    def load_dynamic_class(self, module_path, class_name, create_instance=True, **kwargs):
        """
        Dynamically import and optionally create an instance of a specified class.
        
        Args:
            module_path: Path to the module (e.g., "llm.meta_llm")
            class_name: Name of the class to import (e.g., "MetaLLM")
            create_instance: Whether to create an instance or return the class
            **kwargs: Optional arguments to pass to class constructor
            
        Returns:
            Instance of the class or the class itself
        """
        try:
            # Import the module
            module = importlib.import_module(module_path)
            
            # Get the class from the module
            class_object = getattr(module, class_name)
            
            # Create an instance of the class if requested
            if create_instance:
                return class_object(**kwargs)
            else:
                return class_object
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to import {class_name} from {module_path}: {str(e)}")
            
    def create_directory(self, directory_path):
        """Create directory if it doesn't exist."""
        os.makedirs(directory_path, exist_ok=True)
        return directory_path
        
    def check_existing_files(self, items_list, output_path_generator):
        """
        Check which items already have output files.
        
        Args:
            items_list: List of items to check
            output_path_generator: Function that takes an item and returns output path
            
        Returns:
            Tuple of (existing_files, not_existing_files)
        """
        existing_files = []
        not_existing_files = []
        
        for item in items_list:
            output_path = output_path_generator(item)
            
            if os.path.isfile(output_path):
                existing_files.append(item + (output_path,))
            else:
                not_existing_files.append(item + (output_path,))
            
        return existing_files, not_existing_files
        
    def prompt_overwrite(self, existing_files, path_index=-1):
        """
        Ask user if they want to overwrite existing files.
        
        Args:
            existing_files: List of files that would be overwritten
            path_index: Index of the path in each item tuple
            
        Returns:
            Boolean indicating whether to overwrite files
        """
        if not existing_files:
            return False
            
        print("\nThe following files already exist and would be overwritten:")
        for item in existing_files:
            print(f"  {item[path_index]}")
        
        overwrite_input = input("Do you want to overwrite these existing files? (y/n): ")
        return overwrite_input.lower() in ('y', 'yes')
        
    def read_file_content(self, file_path, file_type="text", encoding='utf-8', errors='replace'):
        """
        Read content from a file.
        
        Args:
            file_path: Path to the file to read
            file_type: Type of file (text, json, etc.)
            encoding: File encoding
            errors: How to handle encoding errors
            
        Returns:
            Content of the file
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
            
        try:
            with open(file_path, 'r', encoding=encoding, errors=errors) as file:
                if file_type == "json":
                    import json
                    return json.load(file)
                else:  # Default to text
                    content = file.read().strip()
                    return content
        except Exception as e:
            raise IOError(f"Error reading file {file_path}: {e}")
            
    def write_to_file(self, content, file_path, file_type="text", encoding='utf-8'):
        """
        Write content to a file.
        
        Args:
            content: Content to write
            file_path: Path where to write the file
            file_type: Type of file (text, json, etc.)
            encoding: File encoding
        """
        try:
            with open(file_path, 'w', encoding=encoding) as file:
                if file_type == "json":
                    import json
                    json.dump(content, file, indent=4, ensure_ascii=False)
                else:  # Default to text
                    file.write(content)
            return True
        except Exception as e:
            print(f"Error writing to file {file_path}: {e}")
            return False
