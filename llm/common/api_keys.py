from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import model_validator, ValidationError


ENV_FILE = Path(__file__).parent / "api_key.env"


class LLMApiKeysLoader(BaseSettings):
    # These are the values being validated and extracted from the env file by Pydantic
    openai_keys: dict[str, str] = {}
    github_keys: dict[str, str] = {}

    # This method runs before model instance is created
    @model_validator(mode="before")
    def check_env_file_not_empty(cls, values) -> dict[str, str]:
        if not ENV_FILE.exists():
            raise ValueError(f"Env file '{ENV_FILE}' does not exist.")
        content = ENV_FILE.read_text().strip()
        if not content:
            raise ValueError(f"Env file '{ENV_FILE}' is empty.")
        return values

    @model_validator(mode="after")
    def extract_and_validate_keys(self):
        openai = {}
        github = {}
        extras = self.model_extra or {}
        for key, value in extras.items():
            if key.upper().startswith("OPENAI"):
                openai[key] = value
            elif key.upper().startswith("GITHUB"):
                github[key] = value

        if not openai:
            raise ValueError("No OPENAI keys found in env file.")
        if not github:
            raise ValueError("No GITHUB keys found in env file.")

        self.openai_keys = openai
        self.github_keys = github
        return self

    def extract_github_keys(self) -> dict[str, str]:
        return self.github_keys

    def extract_openai_keys(self) -> dict[str, str]:
        return self.openai_keys


# Instantiate once (singleton)
try:
    api_keys = LLMApiKeysLoader()
except ValidationError as e:
    print("Validation failed:", e)
    raise
