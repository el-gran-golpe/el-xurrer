from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_content_pipeline.domain.types import (
    FanvueOAuthCredentials,
    FacebookMediaStagingCredentials,
    MetaCredentials,
)


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

    # Profile-specific Meta and Fanvue OAuth credentials are loaded dynamically.

    # Shared Fanvue OAuth/API settings used by CLI auth and publishing.
    fanvue_oauth_issuer_base_url: str = Field(
        default="https://auth.fanvue.com",
        validation_alias="FANVUE_WEBAPP_OAUTH_ISSUER_BASE_URL",
    )
    fanvue_api_base_url: str = Field(
        default="https://api.fanvue.com",
        validation_alias="FANVUE_WEBAPP_API_BASE_URL",
    )

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

    def get_fanvue_oauth_credentials(self, alias: str) -> FanvueOAuthCredentials:
        """Dynamically retrieves Fanvue OAuth credentials for a profile alias."""
        alias_norm = alias.strip().replace(" ", "_").lower()
        alias_env_prefix = alias_norm.upper()
        extras = self.model_extra or {}
        client_id = extras.get(f"fanvue_webapp_{alias_norm}_oauth_client_id")
        client_secret = extras.get(f"fanvue_webapp_{alias_norm}_oauth_client_secret")

        missing_keys = [
            key
            for key, value in {
                f"FANVUE_WEBAPP_{alias_env_prefix}_OAUTH_CLIENT_ID": client_id,
                f"FANVUE_WEBAPP_{alias_env_prefix}_OAUTH_CLIENT_SECRET": client_secret,
            }.items()
            if not value
        ]
        if missing_keys:
            raise EnvironmentError(
                f"Missing Fanvue OAuth credentials for alias '{alias}'. "
                f"Ensure these variables exist in .env: {', '.join(missing_keys)}"
            )

        assert client_id is not None
        assert client_secret is not None

        try:
            return FanvueOAuthCredentials(
                client_id=client_id,
                client_secret=client_secret,
            )
        except ValidationError as e:
            raise EnvironmentError(
                f"Invalid Fanvue OAuth credentials for alias '{alias}': {e}"
            )

    def get_meta_credentials(self, alias: str) -> MetaCredentials:
        """
        Dynamically retrieves Meta credentials for a given profile alias.
        """
        alias_norm = alias.strip().replace(" ", "_").lower()  # lowercase
        alias_env_prefix = alias_norm.upper()
        extras = self.model_extra or {}
        instagram_account_id = extras.get(f"{alias_norm}_instagram_account_id")
        instagram_user_access_token = extras.get(
            f"{alias_norm}_instagram_user_access_token"
        )

        missing_keys = [
            key
            for key, value in {
                f"{alias_env_prefix}_INSTAGRAM_ACCOUNT_ID": instagram_account_id,
                f"{alias_env_prefix}_INSTAGRAM_USER_ACCESS_TOKEN": instagram_user_access_token,
            }.items()
            if not value
        ]
        if missing_keys:
            raise EnvironmentError(
                f"Missing Meta credentials for alias '{alias}'. "
                f"Ensure these variables exist in .env: {', '.join(missing_keys)}"
            )

        # This is just to satisfy the type checker below
        # since we already check for missing keys above
        assert instagram_account_id is not None
        assert instagram_user_access_token is not None

        try:
            return MetaCredentials(
                instagram_account_id=instagram_account_id,
                instagram_user_access_token=instagram_user_access_token,
            )
        except ValidationError as e:
            raise EnvironmentError(f"Invalid Meta credentials for alias '{alias}': {e}")

    def get_facebook_media_staging_credentials(
        self,
    ) -> FacebookMediaStagingCredentials:
        """
        Retrieves the shared Facebook staging credentials used to generate public
        media URLs for Instagram publishing.
        """
        extras = self.model_extra or {}
        page_id = extras.get("facebook_staging_page_id")
        page_access_token = extras.get("facebook_staging_page_access_token")

        missing_keys = [
            key
            for key, value in {
                "FACEBOOK_STAGING_PAGE_ID": page_id,
                "FACEBOOK_STAGING_PAGE_ACCESS_TOKEN": page_access_token,
            }.items()
            if not value
        ]
        if missing_keys:
            raise EnvironmentError(
                "Missing Facebook staging credentials. Ensure these variables "
                f"exist in .env: {', '.join(missing_keys)}"
            )

        assert isinstance(page_id, str)
        assert isinstance(page_access_token, str)

        try:
            return FacebookMediaStagingCredentials(
                page_id=page_id,
                page_access_token=page_access_token,
            )
        except ValidationError as e:
            raise EnvironmentError(f"Invalid Facebook staging credentials: {e}")

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
