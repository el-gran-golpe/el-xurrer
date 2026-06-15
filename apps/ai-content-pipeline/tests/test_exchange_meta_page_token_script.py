import importlib.util
import inspect
import io
import sys
import urllib.error
import warnings
from getpass import GetPassWarning
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "exchange_meta_page_token.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "exchange_meta_page_token", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_exchange_for_page_token_uses_expected_meta_flow(monkeypatch):
    script = _load_script()
    calls = []
    logs = []

    class FakeLogger:
        def info(self, message, *args):
            logs.append(message.format(*args))

    monkeypatch.setattr(script, "logger", FakeLogger())

    def fake_request_json(path_or_url, params):
        calls.append((path_or_url, params))
        if path_or_url == "/oauth/access_token":
            assert params == {
                "grant_type": "fb_exchange_token",
                "client_id": "app-id",
                "client_secret": "app-secret",
                "fb_exchange_token": "short-user-token",
            }
            return {"access_token": "long-user-token"}
        if path_or_url == "/me/accounts":
            assert params == {
                "fields": "name,id,access_token,instagram_business_account",
                "limit": "100",
                "access_token": "long-user-token",
            }
            return {
                "data": [
                    {"name": "Other Page", "id": "999"},
                    {
                        "name": "Maria Larsen",
                        "id": "1055513434323345",
                        "access_token": "page-token-secret",
                        "instagram_business_account": {"id": "17841400000000001"},
                    },
                ]
            }
        if path_or_url == "/1055513434323345":
            assert params == {
                "fields": "instagram_business_account",
                "access_token": "page-token-secret",
            }
            return {"instagram_business_account": {"id": "17841400000000001"}}
        if path_or_url == "/debug_token":
            assert params == {
                "input_token": "page-token-secret",
                "access_token": "app-id|app-secret",
            }
            return {
                "data": {
                    "is_valid": True,
                    "expires_at": 0,
                    "data_access_expires_at": 1893456000,
                }
            }
        raise AssertionError(f"Unexpected Meta request: {path_or_url}")

    result = script.exchange_for_page_token(
        app_id="app-id",
        app_secret="app-secret",
        short_lived_user_token="short-user-token",
        page_id="1055513434323345",
        profile_alias="maria_larsen",
        request_json=fake_request_json,
    )

    assert result.env_prefix == "MARIA_LARSEN"
    assert result.page_name == "Maria Larsen"
    assert result.page_id == "1055513434323345"
    assert result.instagram_account_id == "17841400000000001"
    assert result.page_access_token == "page-token-secret"
    assert result.expires_at == 0
    assert calls[0][0] == "/oauth/access_token"
    assert calls[-1][0] == "/debug_token"

    assert logs == [
        "Starting Meta Page token exchange for profile maria_larsen and Page 1055513434323345.",
        "Requesting long-lived user token from Meta.",
        "Fetching Facebook Pages visible to the long-lived user token.",
        "Looking for Facebook Page ID 1055513434323345 in 2 visible page(s).",
        "Validating Page token against linked Instagram business account.",
        "Checking Page token validity with Meta debug_token.",
        "Meta Page token exchange completed for Maria Larsen (1055513434323345).",
    ]
    joined_logs = "\n".join(logs)
    assert "app-secret" not in joined_logs
    assert "short-user-token" not in joined_logs
    assert "long-user-token" not in joined_logs
    assert "page-token-secret" not in joined_logs


def test_exchange_for_page_token_falls_back_to_direct_page_lookup(monkeypatch):
    script = _load_script()
    calls = []
    logs = []

    class FakeLogger:
        def info(self, message, *args):
            logs.append(message.format(*args))

    monkeypatch.setattr(script, "logger", FakeLogger())

    def fake_request_json(path_or_url, params):
        calls.append((path_or_url, params))
        if path_or_url == "/oauth/access_token":
            return {"access_token": "long-user-token"}
        if path_or_url == "/me/accounts":
            assert params == {
                "fields": "name,id,access_token,instagram_business_account",
                "limit": "100",
                "access_token": "long-user-token",
            }
            return {"data": []}
        if path_or_url == "/1055513434323345" and params == {
            "fields": "name,id,access_token,instagram_business_account",
            "access_token": "long-user-token",
        }:
            return {
                "name": "Maria Larsen",
                "id": "1055513434323345",
                "access_token": "page-token-secret",
                "instagram_business_account": {"id": "17841400000000001"},
            }
        if path_or_url == "/1055513434323345" and params == {
            "fields": "instagram_business_account",
            "access_token": "page-token-secret",
        }:
            return {"instagram_business_account": {"id": "17841400000000001"}}
        if path_or_url == "/debug_token":
            return {
                "data": {
                    "is_valid": True,
                    "expires_at": 0,
                    "data_access_expires_at": 1893456000,
                }
            }
        raise AssertionError(f"Unexpected Meta request: {path_or_url} {params}")

    result = script.exchange_for_page_token(
        app_id="app-id",
        app_secret="app-secret",
        short_lived_user_token="short-user-token",
        page_id="1055513434323345",
        profile_alias="maria_larsen",
        request_json=fake_request_json,
    )

    assert result.page_name == "Maria Larsen"
    assert result.page_access_token == "page-token-secret"
    assert result.instagram_account_id == "17841400000000001"
    assert [call[0] for call in calls] == [
        "/oauth/access_token",
        "/me/accounts",
        "/1055513434323345",
        "/1055513434323345",
        "/debug_token",
    ]
    assert (
        "Page 1055513434323345 was not returned by /me/accounts; trying direct Page lookup."
        in logs
    )
    joined_logs = "\n".join(logs)
    assert "app-secret" not in joined_logs
    assert "short-user-token" not in joined_logs
    assert "long-user-token" not in joined_logs
    assert "page-token-secret" not in joined_logs


def test_main_is_not_cli_argument_driven():
    script = _load_script()

    signature = inspect.signature(script.main)
    assert "argv" not in signature.parameters
    assert list(signature.parameters) == [
        "graph_api_base_url",
        "profile_alias",
        "page_id",
        "app_id",
        "env_file",
        "print_page_token",
    ]
    assert not hasattr(script, "_parse_args")


def test_main_reports_inline_constants_when_not_configured(monkeypatch):
    script = _load_script()
    errors = []

    class FakeLogger:
        def error(self, message, *args):
            errors.append(message.format(*args))

    monkeypatch.setattr(script, "logger", FakeLogger())

    assert (
        script.main(
            graph_api_base_url="",
            profile_alias="",
            page_id="",
            app_id="",
        )
        == 1
    )

    assert len(errors) == 1
    assert "Fill in these constants" in errors[0]
    assert "GRAPH_API_BASE_URL" in errors[0]
    assert "DEFAULT_PROFILE_ALIAS" in errors[0]
    assert "DEFAULT_PAGE_ID" in errors[0]
    assert "META_APP_ID" in errors[0]


def test_main_logs_prompt_progress_without_secrets(monkeypatch, tmp_path):
    script = _load_script()
    logs = []

    class FakeLogger:
        def info(self, message, *args):
            logs.append(message.format(*args))

        def warning(self, message, *args):
            logs.append(message.format(*args))

        def success(self, message, *args):
            logs.append(message.format(*args))

    prompted_values = iter(["app-secret", "short-user-token"])

    monkeypatch.setattr(script, "logger", FakeLogger())
    monkeypatch.setattr(script, "getpass", lambda _prompt: next(prompted_values))
    monkeypatch.setattr(script, "update_env_file", lambda _env_file, _result: None)

    def fake_exchange_for_page_token(**kwargs):
        assert kwargs["app_id"] == "app-id"
        assert kwargs["app_secret"] == "app-secret"
        assert kwargs["short_lived_user_token"] == "short-user-token"
        assert kwargs["page_id"] == "1055513434323345"
        assert kwargs["profile_alias"] == "maria_larsen"
        return script.TokenExchangeResult(
            profile_alias="maria_larsen",
            env_prefix="MARIA_LARSEN",
            page_id="1055513434323345",
            page_name="Maria Larsen",
            instagram_account_id="17841400000000001",
            page_access_token="page-token-secret",
            expires_at=0,
            data_access_expires_at=None,
        )

    monkeypatch.setattr(script, "exchange_for_page_token", fake_exchange_for_page_token)

    assert (
        script.main(
            graph_api_base_url="https://graph.facebook.com/v25.0",
            profile_alias="maria_larsen",
            page_id="1055513434323345",
            app_id="app-id",
            env_file=tmp_path / ".env",
        )
        == 0
    )

    assert logs[:6] == [
        "Meta Page token exchange helper started for profile maria_larsen and Page 1055513434323345.",
        "PyCharm Debug can mishandle hidden getpass input. If the token prompt appears stuck, press Enter; if no progress log appears after that, use PyCharm Run, enable 'Emulate terminal in output console', or run this script from a terminal.",
        "Prompting for Meta app secret.",
        "Meta app secret prompt completed.",
        "Prompting for short-lived Graph API Explorer user token.",
        "Short-lived user token prompt completed; starting Meta API exchange.",
    ]
    joined_logs = "\n".join(logs)
    assert "app-secret" not in joined_logs
    assert "short-user-token" not in joined_logs
    assert "page-token-secret" not in joined_logs


def test_main_uses_visible_prompt_fallback_without_emitting_getpass_warning(
    monkeypatch, tmp_path
):
    script = _load_script()
    logs = []
    getpass_prompts = []
    input_prompts = []
    input_values = iter(["app-secret", "short-user-token"])

    class FakeLogger:
        def info(self, message, *args):
            logs.append(message.format(*args))

        def warning(self, message, *args):
            logs.append(message.format(*args))

        def success(self, message, *args):
            logs.append(message.format(*args))

    def fake_getpass(prompt):
        getpass_prompts.append(prompt)
        warnings.warn(
            "Can not control echo on the terminal.",
            GetPassWarning,
            stacklevel=2,
        )
        return next(input_values)

    def fake_input(prompt):
        input_prompts.append(prompt)
        return next(input_values)

    def fake_exchange_for_page_token(**kwargs):
        assert kwargs["app_secret"] == "app-secret"
        assert kwargs["short_lived_user_token"] == "short-user-token"
        return script.TokenExchangeResult(
            profile_alias="maria_larsen",
            env_prefix="MARIA_LARSEN",
            page_id="1055513434323345",
            page_name="Maria Larsen",
            instagram_account_id="17841400000000001",
            page_access_token="page-token-secret",
            expires_at=0,
            data_access_expires_at=None,
        )

    monkeypatch.setattr(script, "logger", FakeLogger())
    monkeypatch.setattr(script, "getpass", fake_getpass)
    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(script, "exchange_for_page_token", fake_exchange_for_page_token)
    monkeypatch.setattr(script, "update_env_file", lambda _env_file, _result: None)

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        assert (
            script.main(
                graph_api_base_url="https://graph.facebook.com/v25.0",
                profile_alias="maria_larsen",
                page_id="1055513434323345",
                app_id="app-id",
                env_file=tmp_path / ".env",
            )
            == 0
        )

    assert not [
        caught_warning
        for caught_warning in caught_warnings
        if issubclass(caught_warning.category, GetPassWarning)
    ]
    assert getpass_prompts == [
        "Meta App Secret: ",
        "Short-lived Graph API Explorer user token: ",
    ]
    assert input_prompts == [
        "Meta App Secret: ",
        "Short-lived Graph API Explorer user token: ",
    ]
    assert (
        "Meta App Secret will be entered visibly because this console cannot disable echo."
        in logs
    )
    assert (
        "Short-lived Graph API Explorer user token will be entered visibly because this console cannot disable echo."
        in logs
    )


def test_main_defaults_to_repository_root_env_file(monkeypatch):
    script = _load_script()
    updated_env_files = []

    class FakeLogger:
        def info(self, message, *args):
            pass

        def warning(self, message, *args):
            pass

        def success(self, message, *args):
            pass

    prompted_values = iter(["app-secret", "short-user-token"])

    monkeypatch.setattr(script, "logger", FakeLogger())
    monkeypatch.setattr(script, "getpass", lambda _prompt: next(prompted_values))

    def fake_exchange_for_page_token(**_kwargs):
        return script.TokenExchangeResult(
            profile_alias="maria_larsen",
            env_prefix="MARIA_LARSEN",
            page_id="1055513434323345",
            page_name="Maria Larsen",
            instagram_account_id="17841400000000001",
            page_access_token="page-token-secret",
            expires_at=0,
            data_access_expires_at=None,
        )

    def fake_update_env_file(env_file, _result):
        updated_env_files.append(env_file)
        return None

    monkeypatch.setattr(script, "exchange_for_page_token", fake_exchange_for_page_token)
    monkeypatch.setattr(script, "update_env_file", fake_update_env_file)

    assert (
        script.main(
            graph_api_base_url="https://graph.facebook.com/v25.0",
            profile_alias="maria_larsen",
            page_id="1055513434323345",
            app_id="app-id",
        )
        == 0
    )

    assert updated_env_files == [SCRIPT_PATH.parents[3] / ".env"]


def test_main_definition_is_last_function_before_script_entrypoint():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    main_index = source.rfind("\ndef main(")
    entrypoint_index = source.rfind('\nif __name__ == "__main__":')

    assert main_index != -1
    assert entrypoint_index != -1
    assert main_index < entrypoint_index
    assert "\ndef " not in source[main_index + 1 : entrypoint_index]


def test_runtime_configuration_constants_live_in_script_entrypoint():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    main_index = source.rfind("\ndef main(")
    entrypoint_index = source.rfind('\nif __name__ == "__main__":')
    main_block = source[main_index:entrypoint_index]
    entrypoint_block = source[entrypoint_index:]

    for variable_name in [
        "GRAPH_API_BASE_URL",
        "DEFAULT_PROFILE_ALIAS",
        "DEFAULT_PAGE_ID",
        "META_APP_ID",
    ]:
        assignment_prefix = f"    {variable_name} = "
        assert assignment_prefix not in main_block
        assert assignment_prefix in entrypoint_block


def test_script_uses_loguru_instead_of_print():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "from loguru import logger" in source
    assert "print(" not in source


def test_script_does_not_use_future_annotations():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "from __future__ import annotations" not in source


def test_update_env_file_replaces_profile_keys_and_keeps_unrelated_values(tmp_path):
    script = _load_script()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "LAURA_VIGNE_FACEBOOK_PAGE_ID=keep-this\n"
        "MARIA_LARSEN_FACEBOOK_PAGE_ACCESS_TOKEN=old-token\n",
        encoding="utf-8",
    )
    result = script.TokenExchangeResult(
        profile_alias="maria_larsen",
        env_prefix="MARIA_LARSEN",
        page_id="1055513434323345",
        page_name="Maria Larsen",
        instagram_account_id="17841400000000001",
        page_access_token="page-token-secret",
        expires_at=0,
        data_access_expires_at=1893456000,
    )

    backup_path = script.update_env_file(env_path, result)

    text = env_path.read_text(encoding="utf-8")
    assert backup_path is not None
    assert backup_path.exists()
    assert "LAURA_VIGNE_FACEBOOK_PAGE_ID=keep-this" in text
    assert "MARIA_LARSEN_FACEBOOK_PAGE_ID=1055513434323345" in text
    assert "MARIA_LARSEN_INSTAGRAM_ACCOUNT_ID=17841400000000001" in text
    assert "MARIA_LARSEN_FACEBOOK_PAGE_ACCESS_TOKEN=page-token-secret" in text
    assert "old-token" not in text
    assert text.count("MARIA_LARSEN_FACEBOOK_PAGE_ACCESS_TOKEN=") == 1
    assert backup_path.stat().st_mode & 0o777 == 0o600


def test_request_json_redacts_sensitive_values_from_meta_errors(monkeypatch):
    script = _load_script()

    def fake_urlopen(url, timeout):
        raise urllib.error.HTTPError(
            url,
            400,
            "Bad Request",
            {},
            io.BytesIO(
                b'{"error":{"message":"bad app-secret short-token page-token"}}'
            ),
        )

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(script.TokenExchangeError) as error:
        script.request_json(
            "/test",
            {
                "client_secret": "app-secret",
                "fb_exchange_token": "short-token",
                "access_token": "page-token",
            },
            graph_api_base_url="https://graph.facebook.com/v25.0",
        )

    message = str(error.value)
    assert "app-secret" not in message
    assert "short-token" not in message
    assert "page-token" not in message
    assert message.count("<redacted>") == 3


def test_request_json_redacts_sensitive_values_from_absolute_url_errors(monkeypatch):
    script = _load_script()
    next_token = "next-page-token"

    def fake_urlopen(url, timeout):
        raise urllib.error.HTTPError(
            url,
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error":{"message":"bad next-page-token"}}'),
        )

    monkeypatch.setattr(script.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(script.TokenExchangeError) as error:
        script.request_json(
            f"https://graph.facebook.com/v21.0/me/accounts?access_token={next_token}",
            {},
            graph_api_base_url="https://graph.facebook.com/v25.0",
        )

    message = str(error.value)
    assert next_token not in message
    assert "<redacted>" in message


def test_exchange_rejects_debug_token_without_explicit_valid_true():
    script = _load_script()

    def fake_request_json(path_or_url, params):
        if path_or_url == "/oauth/access_token":
            return {"access_token": "long-user-token"}
        if path_or_url == "/me/accounts":
            return {
                "data": [
                    {
                        "name": "Maria Larsen",
                        "id": "1055513434323345",
                        "access_token": "page-token-secret",
                        "instagram_business_account": {"id": "17841400000000001"},
                    },
                ]
            }
        if path_or_url == "/1055513434323345":
            return {"instagram_business_account": {"id": "17841400000000001"}}
        if path_or_url == "/debug_token":
            return {"data": {"expires_at": 0}}
        raise AssertionError(f"Unexpected Meta request: {path_or_url}")

    with pytest.raises(script.TokenExchangeError, match="invalid"):
        script.exchange_for_page_token(
            app_id="app-id",
            app_secret="app-secret",
            short_lived_user_token="short-user-token",
            page_id="1055513434323345",
            profile_alias="maria_larsen",
            request_json=fake_request_json,
        )


def test_format_success_message_redacts_page_token_by_default():
    script = _load_script()
    result = script.TokenExchangeResult(
        profile_alias="maria_larsen",
        env_prefix="MARIA_LARSEN",
        page_id="1055513434323345",
        page_name="Maria Larsen",
        instagram_account_id="17841400000000001",
        page_access_token="page-token-secret",
        expires_at=0,
        data_access_expires_at=None,
    )

    message = script.format_success_message(
        result,
        env_path=Path(".env"),
        backup_path=None,
        print_token=False,
    )

    assert "Maria Larsen" in message
    assert "17841400000000001" in message
    assert "expires_at: 0" in message
    assert "page-token-secret" not in message
    assert "non-expiring" in message


def test_format_success_message_never_prints_token_even_when_requested():
    script = _load_script()
    result = script.TokenExchangeResult(
        profile_alias="maria_larsen",
        env_prefix="MARIA_LARSEN",
        page_id="1055513434323345",
        page_name="Maria Larsen",
        instagram_account_id="17841400000000001",
        page_access_token="page-token-secret",
        expires_at=0,
        data_access_expires_at=None,
    )

    message = script.format_success_message(
        result,
        env_path=Path(".env"),
        backup_path=None,
        print_token=True,
    )

    assert "page-token-secret" not in message
    assert "FACEBOOK_PAGE_ACCESS_TOKEN" not in message
    assert "Page token printing is disabled" in message
