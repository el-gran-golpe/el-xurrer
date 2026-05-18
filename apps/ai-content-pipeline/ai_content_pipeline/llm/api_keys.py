"""
This module provides a centralized access point to API keys.

It has been refactored to use the main `Settings` object from `ai_content_pipeline.config`.
The `api_keys` variable is now an alias for the global `settings` object
to maintain backward compatibility with other modules that might import it.
"""

from ai_content_pipeline.config import settings

# The `api_keys` variable is now an alias for the singleton `settings` object.
# Any module importing `api_keys` will get the centralized configuration.
api_keys = settings
