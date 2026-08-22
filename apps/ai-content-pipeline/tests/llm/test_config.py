from pathlib import Path

from ai_content_pipeline.config import Settings

REQUIRED_ENV = """\
OPENAI_API_KEY=x
DEEPSEEK_API_KEY=x
client_id=x
client_secret=x
folder_id=x
"""


def _settings_from_env(tmp_path: Path, extra_env: str = "") -> Settings:
    env_file = tmp_path / ".env"
    env_file.write_text(REQUIRED_ENV + extra_env)
    return Settings(_env_file=str(env_file))


def test_provider_keys_filters_by_prefix_case_insensitively(tmp_path):
    settings = _settings_from_env(
        tmp_path,
        "OPENROUTER_API_KEY_HARU=key-haru\n"
        "OPENROUTER_API_KEY_CHARLY=key-charly\n"
        "SOME_OTHER_KEY=unrelated\n",
    )

    assert settings.provider_keys("OPENROUTER_API_KEY") == {
        "openrouter_api_key_haru": "key-haru",
        "openrouter_api_key_charly": "key-charly",
    }


def test_extract_openrouter_keys_returns_values_only(tmp_path):
    settings = _settings_from_env(
        tmp_path,
        "OPENROUTER_API_KEY_HARU=key-haru\nOPENROUTER_API_KEY_CHARLY=key-charly\n",
    )

    assert sorted(settings.extract_openrouter_keys()) == ["key-charly", "key-haru"]


def test_extract_openrouter_keys_empty_when_none_set(tmp_path):
    settings = _settings_from_env(tmp_path)

    assert settings.extract_openrouter_keys() == []


def test_extract_deepseek_key_unaffected_by_provider_keys(tmp_path):
    settings = _settings_from_env(tmp_path, "OPENROUTER_API_KEY_HARU=key-haru\n")

    assert settings.extract_deepseek_key() == "x"
