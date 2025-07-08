import os
import importlib


class BaseMain:
    """Base class with common functionality for content generation tools."""

    def __init__(self, platform_name=None):
        """Initialize base parameters."""
        self.platform_name = platform_name

    def load_dynamic_class(
        self, module_path, class_name, create_instance=True, **kwargs
    ):
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
            raise ImportError(
                f"Failed to import {class_name} from {module_path}: {str(e)}"
            )

    def read_file_content(
        self, file_path, file_type="text", encoding="utf-8", errors="replace"
    ):
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
            with open(file_path, "r", encoding=encoding, errors=errors) as file:
                if file_type == "json":
                    import json

                    return json.load(file)
                else:  # Default to text
                    content = file.read().strip()
                    return content
        except Exception as e:
            raise IOError(f"Error reading file {file_path}: {e}")

    def write_to_file(self, content, file_path, file_type="text", encoding="utf-8"):
        """
        Write content to a file.

        Args:
            content: Content to write
            file_path: Path where to write the file
            file_type: Type of file (text, json, etc.)
            encoding: File encoding
        """
        try:
            with open(file_path, "w", encoding=encoding) as file:
                if file_type == "json":
                    import json

                    json.dump(content, file, indent=4, ensure_ascii=False)
                else:  # Default to text
                    file.write(content)
            return True
        except Exception as e:
            print(f"Error writing to file {file_path}: {e}")
            return False
