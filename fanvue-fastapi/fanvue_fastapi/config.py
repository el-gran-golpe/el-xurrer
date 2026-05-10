from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProfileNotConfiguredError(RuntimeError):
    """Raised when a requested profile has no OAuth credentials configured."""


class Settings(BaseSettings):
    """Shared application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="FANVUE_WEBAPP_",
    )

    # OAuth Configuration (shared across profiles)
    oauth_redirect_uri: str = Field(...)
    oauth_scopes: str = Field(default="")
    oauth_issuer_base_url: str = Field(...)
    oauth_response_mode: str | None = Field(default=None)
    oauth_prompt: str | None = Field(default=None)

    # Session Configuration
    session_secret: str = Field(...)
    session_cookie_name: str = Field(default="fvsession")

    # API Configuration
    api_base_url: str = Field(...)
    base_url: str = Field(...)

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret_length(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("SESSION_SECRET must be at least 16 characters")
        return v


class ProfileOAuthSettings(BaseSettings):
    """Per-profile OAuth credentials, loaded via a dynamic env prefix."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    client_id: str
    client_secret: str


def get_settings() -> Settings:
    return Settings()


def get_profile_oauth_settings(profile_name: str) -> ProfileOAuthSettings:
    """Resolve OAuth credentials for a given profile.

    Reads ``FANVUE_WEBAPP_{PROFILE}_OAUTH_CLIENT_ID`` and
    ``FANVUE_WEBAPP_{PROFILE}_OAUTH_CLIENT_SECRET`` from the environment or .env file.
    """
    prefix = f"FANVUE_WEBAPP_{profile_name.upper()}_OAUTH_"
    try:
        return ProfileOAuthSettings(_env_prefix=prefix)
    except Exception:
        raise ProfileNotConfiguredError(
            f"OAuth credentials for profile '{profile_name}' not configured. "
            f"Set {prefix}CLIENT_ID and {prefix}CLIENT_SECRET in the environment."
        )
