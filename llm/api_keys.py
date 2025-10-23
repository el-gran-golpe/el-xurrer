from pathlib import Path

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator, ValidationError


ENV_FILE = Path(__file__).parent / "api_key.env"


class LLMApiKeysLoader(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="allow",
    )

    @model_validator(mode="before")
    def check_env_file_not_empty(cls, values) -> dict[str, str]:
        if not ENV_FILE.exists():
            raise ValueError(f"Env file '{ENV_FILE}' does not exist.")
        content = ENV_FILE.read_text().strip()
        if not content:
            raise ValueError(f"Env file '{ENV_FILE}' is empty.")
        return values

    @model_validator(mode="after")
    def ensure_key_groups_exist(self):
        raw = self.model_dump()

        # Validate DeepSeek keys
        deepseek_keys = {
            k: v for k, v in raw.items() if k.upper().startswith("DEEPSEEK") and v != ""
        }
        if len(deepseek_keys) != 1:
            raise ValueError(
                f"Expected exactly one DEEPSEEK key, found {len(deepseek_keys)}."
            )

        # Validate GitHub keys
        github_keys = {
            k: v for k, v in raw.items() if k.upper().startswith("GITHUB") and v != ""
        }
        if not github_keys:
            raise ValueError("No GITHUB keys found in env file.")

        return self

    @property
    def deepseek_key(self) -> str:
        raw = self.model_dump()
        keys = {
            k: v for k, v in raw.items() if k.upper().startswith("DEEPSEEK") and v != ""
        }
        return list(keys.values())[0]

    @property
    def github_keys(self) -> dict[str, str]:
        raw = self.model_dump()
        return {
            k: v for k, v in raw.items() if k.upper().startswith("GITHUB") and v != ""
        }

    def extract_github_keys(self) -> list[str]:
        return list(self.github_keys.values())

    def extract_deepseek_key(self) -> str:
        return self.deepseek_key


# TODO: Ask Moi what does he think about this approach
# Instantiate once (singleton)
try:
    api_keys = LLMApiKeysLoader()
except ValidationError as e:
    logger.info("Validation failed:", e)
    raise
