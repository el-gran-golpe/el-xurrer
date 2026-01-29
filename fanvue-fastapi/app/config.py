from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="FANVUE_WEBAPP_",
    )

    # OAuth Configuration
    oauth_client_id: str = Field(..., validation_alias="OAUTH_CLIENT_ID")
    oauth_client_secret: str = Field(..., validation_alias="OAUTH_CLIENT_SECRET")
    oauth_redirect_uri: str = Field(..., validation_alias="OAUTH_REDIRECT_URI")
    oauth_scopes: str = Field(default="", validation_alias="OAUTH_SCOPES")
    oauth_issuer_base_url: str = Field(..., validation_alias="OAUTH_ISSUER_BASE_URL")
    oauth_response_mode: str | None = Field(
        default=None, validation_alias="OAUTH_RESPONSE_MODE"
    )
    oauth_prompt: str | None = Field(default=None, validation_alias="OAUTH_PROMPT")

    # Session Configuration
    session_secret: str = Field(..., validation_alias="SESSION_SECRET")
    session_cookie_name: str = Field(
        default="fvsession", validation_alias="SESSION_COOKIE_NAME"
    )

    # API Configuration
    api_base_url: str = Field(..., validation_alias="API_BASE_URL")
    base_url: str = Field(..., validation_alias="BASE_URL")

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret_length(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("SESSION_SECRET must be at least 16 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
