from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from main_components.common.types import FanvueCredentials


class Settings(BaseSettings):
    # ComfyUI server (defaults to local; set COMFY_HOST to a ZeroTier IP for a remote machine)
    comfy_host: str = Field(default="127.0.0.1", validation_alias="COMFY_HOST")
    comfy_port: int = Field(default=8188, validation_alias="COMFY_PORT")

    # BaseLLM Keys
    openai_api_key: str = Field(validation_alias="OPENAI_API_KEY")
    deepseek_api_key: str = Field(validation_alias="DEEPSEEK_API_KEY")

    # Note: GitHub keys are loaded dynamically due to their naming convention
    # GITHUB_API_KEY_HARU, GITHUB_API_KEY_CHARLY, etc.

    # Google Drive OAuth
    client_id: str = Field(validation_alias="client_id")
    client_secret: str = Field(validation_alias="client_secret")
    folder_id: str = Field(validation_alias="folder_id")

    # Meta API
    instagram_account_id: str = Field(validation_alias="INSTAGRAM_ACCOUNT_ID")
    user_access_token: str = Field(validation_alias="USER_ACCESS_TOKEN")
    app_scoped_user_id: str = Field(validation_alias="APP_SCOPED_USER_ID")

    # Fanvue credentials are loaded dynamically.
    # LAURA_VIGNE_FANVUE_USERNAME, MARIA_LARSEN_FANVUE_PASSWORD, etc.

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",  # Allow dynamic keys like GITHUB_API_KEY_* and *_FANVUE_*
    )

    @property
    def github_keys(self) -> dict[str, str]:
        """Returns a dictionary of all non-empty GitHub keys."""
        raw = self.model_dump()
        return {k: v for k, v in raw.items() if k.upper().startswith("GITHUB") and v}

    def get_fanvue_credentials(self, alias: str) -> FanvueCredentials:
        """
        Dynamically retrieves Fanvue credentials for a given profile alias.
        """
        alias_norm = alias.strip().replace(" ", "_").upper()
        # Access extra fields via model_extra
        extras = self.model_extra or {}
        username = extras.get(f"{alias_norm}_FANVUE_USERNAME")
        password = extras.get(f"{alias_norm}_FANVUE_PASSWORD")

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

    # ---------------- Extraction Methods ----------------

    def extract_github_keys(self) -> list[str]:
        """Extracts all GitHub API key values."""
        return list(self.github_keys.values())

    # This key is not being used currently
    def extract_openai_key(self) -> str:
        """Returns the single OpenAI API key."""
        return self.openai_api_key

    def extract_deepseek_key(self) -> str:
        """Returns the single DeepSeek API key."""
        return self.deepseek_api_key


# Instantiate once (singleton) for the entire application
settings = Settings()  # type: ignore[call-arg]
