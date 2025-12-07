from typing import List

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from main_components.common.types import FanvueCredentials


class Settings(BaseSettings):
    # BaseLLM Keys
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    deepseek_api_key: str = Field(..., env="DEEPSEEK_API_KEY")

    # Note: Github keys are loaded dynamically due to their naming convention
    # GITHUB_API_KEY_HARU, GITHUB_API_KEY_CHARLY, etc.

    # Google Drive OAuth
    client_id: str = Field(..., env="client_id")
    client_secret: str = Field(..., env="client_secret")
    folder_id: str = Field(..., env="folder_id")

    # Meta API
    instagram_account_id: str = Field(..., env="INSTAGRAM_ACCOUNT_ID")
    user_access_token: str = Field(..., env="USER_ACCESS_TOKEN")
    app_scoped_user_id: str = Field(..., env="APP_SCOPED_USER_ID")

    # Fanvue credentials are loaded dynamically.
    # LAURA_VIGNE_FANVUE_USERNAME, MARIA_LARSEN_FANVUE_PASSWORD, etc.

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",  # Allow dynamic keys like GITHUB_API_KEY_* and *_FANVUE_*
    )

    @property
    def openai_keys(self) -> dict[str, str]:
        """Returns a dictionary of all non-empty OpenAI keys."""
        raw = self.model_dump()
        return {k: v for k, v in raw.items() if k.upper().startswith("OPENAI") and v}

    @property
    def github_keys(self) -> dict[str, str]:
        """Returns a dictionary of all non-empty GitHub keys."""
        raw = self.model_dump()
        return {k: v for k, v in raw.items() if k.upper().startswith("GITHUB") and v}

    @property
    def deepseek_keys(self) -> dict[str, str]:
        """Returns a dictionary of all non-empty Deepseek keys."""
        raw = self.model_dump()
        return {k: v for k, v in raw.items() if k.upper().startswith("DEEPSEEK") and v}

    def get_fanvue_credentials(self, alias: str) -> FanvueCredentials:
        """
        Dynamically retrieves Fanvue credentials for a given profile alias.
        """
        alias_norm = alias.strip().replace(" ", "_").upper()
        # Access extra fields via model_extra
        username = self.model_extra.get(f"{alias_norm}_FANVUE_USERNAME")
        password = self.model_extra.get(f"{alias_norm}_FANVUE_PASSWORD")

        if not username or not password:
            raise EnvironmentError(
                f"Missing Fanvue credentials for alias '{alias}'. "
                f"Ensure {alias_norm}_FANVUE_USERNAME and {alias_norm}_FANVUE_PASSWORD are in your .env file."
            )

        try:
            return FanvueCredentials(username=username, password=password)
        except ValidationError as e:
            raise EnvironmentError(
                f"Invalid Fanvue credentials for alias '{alias}': {e}"
            )

    def extract_github_keys(self) -> List[str]:
        """Extracts all GitHub API key values."""
        return list(self.github_keys.values())

    def extract_openai_keys(self) -> List[str]:
        """Extracts all OpenAI API key values."""
        return list(self.openai_keys.values())


# Instantiate once (singleton) for the entire application
settings = Settings()
