from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator, ValidationError


ENV_FILE = Path(__file__).parent / "api_key.env"


class LLMApiKeysLoader(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="allow",
    )  # This SettingsConfigDict is new in pydantic v2.x

    # This method runs before model instance is created
    @model_validator(mode="before")
    def check_env_file_not_empty(cls, values) -> dict[str, str]:
        if not ENV_FILE.exists():
            raise ValueError(f"Env file '{ENV_FILE}' does not exist.")
        content = ENV_FILE.read_text().strip()
        if not content:
            raise ValueError(f"Env file '{ENV_FILE}' is empty.")
        return values

    @property
    def openai_keys(self) -> dict[str, str]:
        raw = self.model_dump()
        return {
            k: v for k, v in raw.items() if k.upper().startswith("OPENAI") and v != ""
        }

    @property
    def github_keys(self) -> dict[str, str]:
        raw = self.model_dump()
        return {
            k: v for k, v in raw.items() if k.upper().startswith("GITHUB") and v != ""
        }

    @model_validator(mode="after")
    def ensure_key_groups_exist(self):
        if not self.openai_keys:
            raise ValueError("No OPENAI keys found in env file.")
        if not self.github_keys:
            raise ValueError("No GITHUB keys found in env file.")
        return self

    def extract_github_keys(self) -> list[str]:
        return list(self.github_keys.values())

    def extract_openai_keys(self) -> list[str]:
        return list(self.openai_keys.values())


# TODO: Ask Moi what does he think about this approach
# Instantiate once (singleton)
try:
    api_keys = LLMApiKeysLoader()
except ValidationError as e:
    print("Validation failed:", e)
    raise
