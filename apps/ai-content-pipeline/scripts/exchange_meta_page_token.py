"""Exchange a Meta short-lived user token for a profile Page token.

Fill in the constants in the ``if __name__ == "__main__"`` block and run this
file directly, for example from a PyCharm run configuration. The script prompts
for secrets, validates that the selected Facebook Page is linked to an Instagram
business account, and updates `.env` with the profile-specific keys used by the
AI content pipeline.
"""

import datetime as dt
import json
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from getpass import GetPassWarning, getpass
from pathlib import Path
from typing import Any

from loguru import logger


JsonObject = dict[str, Any]
RequestJson = Callable[[str, Mapping[str, str]], JsonObject]


class TokenExchangeError(RuntimeError):
    """Raised when Meta does not return the expected token payload."""


@dataclass(frozen=True)
class TokenExchangeResult:
    profile_alias: str
    env_prefix: str
    page_id: str
    page_name: str
    instagram_account_id: str
    page_access_token: str
    expires_at: int | None
    data_access_expires_at: int | None


def env_prefix_from_alias(profile_alias: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", profile_alias.strip()).strip("_")
    if not prefix:
        raise ValueError("Profile alias cannot be empty.")
    return prefix.upper()


def request_json(
    path_or_url: str,
    params: Mapping[str, str],
    *,
    graph_api_base_url: str,
) -> JsonObject:
    url = _build_graph_url(path_or_url, params, graph_api_base_url)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _redact_sensitive_values(
            _read_error_detail(exc),
            _sensitive_values(path_or_url, params),
        )
        raise TokenExchangeError(
            f"Meta API request failed for {_safe_request_label(path_or_url)}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        detail = _redact_sensitive_values(
            str(exc),
            _sensitive_values(path_or_url, params),
        )
        raise TokenExchangeError(
            f"Meta API request failed for {_safe_request_label(path_or_url)}: {detail}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise TokenExchangeError(
            f"Meta API returned invalid JSON for {_safe_request_label(path_or_url)}."
        ) from exc

    if not isinstance(payload, dict):
        raise TokenExchangeError(
            f"Meta API returned a non-object payload for {_safe_request_label(path_or_url)}."
        )
    return payload


def exchange_for_page_token(
    *,
    app_id: str,
    app_secret: str,
    short_lived_user_token: str,
    page_id: str,
    profile_alias: str,
    request_json: RequestJson,
) -> TokenExchangeResult:
    logger.info(
        "Starting Meta Page token exchange for profile {} and Page {}.",
        profile_alias,
        page_id,
    )
    logger.info("Requesting long-lived user token from Meta.")
    long_token_payload = request_json(
        "/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_lived_user_token,
        },
    )
    long_user_token = _required_str(
        long_token_payload.get("access_token"),
        "long-lived user token",
    )

    logger.info("Fetching Facebook Pages visible to the long-lived user token.")
    pages = _fetch_pages(long_user_token, request_json)
    logger.info(
        "Looking for Facebook Page ID {} in {} visible page(s).",
        page_id,
        len(pages),
    )
    page = _find_page(pages, page_id)
    if page is None:
        logger.info(
            "Page {} was not returned by /me/accounts; trying direct Page lookup.",
            page_id,
        )
        page = _fetch_page_direct(page_id, long_user_token, request_json)
        returned_page_id = page.get("id")
        if returned_page_id is not None and str(returned_page_id) != page_id:
            raise TokenExchangeError(
                f"Direct Page lookup returned Page {returned_page_id}, expected {page_id}."
            )

    page_token = _required_str(page.get("access_token"), "Page access token")
    instagram_account_id = _instagram_business_account_id(page)
    if not instagram_account_id:
        raise TokenExchangeError(
            f"Page {page_id} did not return instagram_business_account. Confirm the "
            "Instagram account is professional and linked to this Facebook Page."
        )

    logger.info("Validating Page token against linked Instagram business account.")
    validation_payload = request_json(
        f"/{page_id}",
        {
            "fields": "instagram_business_account",
            "access_token": page_token,
        },
    )
    returned_instagram_id = _instagram_business_account_id(validation_payload)
    if returned_instagram_id != instagram_account_id:
        raise TokenExchangeError(
            "Page token Instagram validation mismatch. "
            f"Expected {instagram_account_id}, got {returned_instagram_id or 'missing'}."
        )

    logger.info("Checking Page token validity with Meta debug_token.")
    debug_payload = request_json(
        "/debug_token",
        {
            "input_token": page_token,
            "access_token": f"{app_id}|{app_secret}",
        },
    )
    debug_data = debug_payload.get("data")
    if not isinstance(debug_data, dict):
        raise TokenExchangeError("Meta debug_token returned no data object.")
    if debug_data.get("is_valid") is not True:
        raise TokenExchangeError("Meta debug_token says the Page token is invalid.")

    page_name = str(page.get("name") or "unknown")
    logger.info(
        "Meta Page token exchange completed for {} ({}).",
        page_name,
        page_id,
    )
    return TokenExchangeResult(
        profile_alias=profile_alias,
        env_prefix=env_prefix_from_alias(profile_alias),
        page_id=page_id,
        page_name=page_name,
        instagram_account_id=instagram_account_id,
        page_access_token=page_token,
        expires_at=_optional_int(debug_data.get("expires_at")),
        data_access_expires_at=_optional_int(debug_data.get("data_access_expires_at")),
    )


def update_env_file(env_path: Path, result: TokenExchangeResult) -> Path | None:
    updates = {
        f"{result.env_prefix}_FACEBOOK_PAGE_ID": result.page_id,
        f"{result.env_prefix}_INSTAGRAM_ACCOUNT_ID": result.instagram_account_id,
        f"{result.env_prefix}_FACEBOOK_PAGE_ACCESS_TOKEN": result.page_access_token,
    }
    for key, value in updates.items():
        _validate_env_assignment(key, value)

    backup_path: Path | None = None
    lines: list[str] = []
    if env_path.exists():
        backup_path = env_path.with_name(
            f"{env_path.name}.bak.{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        backup_path.write_bytes(env_path.read_bytes())
        _chmod_owner_read_write(backup_path)
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)

    key_pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        match = key_pattern.match(line)
        key = match.group(1) if match else None
        if key in updates:
            output.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            output.append(line)

    missing_keys = [key for key in updates if key not in seen]
    if missing_keys:
        if output and not output[-1].endswith("\n"):
            output[-1] += "\n"
        if output:
            output.append("\n")
        output.append(f"# Meta credentials for {result.profile_alias}\n")
        for key in missing_keys:
            output.append(f"{key}={updates[key]}\n")

    env_path.write_text("".join(output), encoding="utf-8")
    _chmod_owner_read_write(env_path)
    return backup_path


def format_success_message(
    result: TokenExchangeResult,
    *,
    env_path: Path,
    backup_path: Path | None,
    print_token: bool,
) -> str:
    lines = [
        f"Updated {env_path} with Meta credentials for {result.profile_alias}.",
    ]
    if backup_path is not None:
        lines.append(f"Backup created: {backup_path}")
    lines.extend(
        [
            f"Facebook Page: {result.page_name} ({result.page_id})",
            f"Instagram business account ID: {result.instagram_account_id}",
            f"Page token expires_at: {_format_expires_at(result.expires_at)}",
        ]
    )
    if result.data_access_expires_at:
        lines.append(
            "Data access expires_at: "
            f"{_format_expires_at(result.data_access_expires_at)}"
        )
    if print_token:
        lines.append(
            "Page token printing is disabled for safety; it was written to .env."
        )
    else:
        lines.append("Page token was written to .env and was not printed.")
    return "\n".join(lines)


def _configured_request_json(graph_api_base_url: str) -> RequestJson:
    def configured_request_json(
        path_or_url: str,
        params: Mapping[str, str],
    ) -> JsonObject:
        return request_json(
            path_or_url,
            params,
            graph_api_base_url=graph_api_base_url,
        )

    return configured_request_json


def _missing_inline_config(config: Mapping[str, str]) -> list[str]:
    return [name for name, value in config.items() if not value.strip()]


def _prompt_secret(label: str) -> str:
    prompt = f"{label}: "
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            return getpass(prompt).strip()
        except GetPassWarning:
            logger.warning(
                "{} will be entered visibly because this console cannot disable echo.",
                label,
            )
            return input(prompt).strip()


def _fetch_pages(long_user_token: str, request_json: RequestJson) -> list[JsonObject]:
    pages: list[JsonObject] = []
    payload = request_json(
        "/me/accounts",
        {
            "fields": "name,id,access_token,instagram_business_account",
            "limit": "100",
            "access_token": long_user_token,
        },
    )
    while True:
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise TokenExchangeError(
                "Meta /me/accounts returned a non-list data field."
            )
        pages.extend(page for page in data if isinstance(page, dict))

        paging = payload.get("paging")
        next_url = paging.get("next") if isinstance(paging, dict) else None
        if not isinstance(next_url, str) or not next_url:
            return pages
        payload = request_json(next_url, {})


def _fetch_page_direct(
    page_id: str,
    long_user_token: str,
    request_json: RequestJson,
) -> JsonObject:
    return request_json(
        f"/{page_id}",
        {
            "fields": "name,id,access_token,instagram_business_account",
            "access_token": long_user_token,
        },
    )


def _find_page(pages: list[JsonObject], page_id: str) -> JsonObject | None:
    return next((page for page in pages if str(page.get("id")) == page_id), None)


def _instagram_business_account_id(payload: JsonObject) -> str:
    account = payload.get("instagram_business_account")
    if not isinstance(account, dict):
        return ""
    return str(account.get("id") or "")


def _required_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TokenExchangeError(f"Meta response did not include {label}.")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_graph_url(
    path_or_url: str,
    params: Mapping[str, str],
    graph_api_base_url: str,
) -> str:
    if path_or_url.startswith(("http://", "https://")):
        if not params:
            return path_or_url
        separator = "&" if "?" in path_or_url else "?"
        return f"{path_or_url}{separator}{urllib.parse.urlencode(params)}"

    path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
    return f"{graph_api_base_url.rstrip('/')}{path}?{urllib.parse.urlencode(params)}"


def _read_error_detail(exc: urllib.error.HTTPError) -> str:
    body = exc.read().decode("utf-8", errors="replace")
    if not body:
        return str(exc)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
    return body


def _sensitive_values(path_or_url: str, params: Mapping[str, str]) -> list[str]:
    values: list[str] = []
    query_params = urllib.parse.parse_qsl(
        urllib.parse.urlparse(path_or_url).query,
        keep_blank_values=False,
    )
    for key, value in [*params.items(), *query_params]:
        if not value or not re.search(r"token|secret", key, re.IGNORECASE):
            continue
        values.append(value)
        values.extend(part for part in value.split("|") if part)
    return values


def _redact_sensitive_values(message: str, sensitive_values: Sequence[str]) -> str:
    redacted = message
    for value in sorted(set(sensitive_values), key=len, reverse=True):
        redacted = redacted.replace(value, "<redacted>")
    return redacted


def _safe_request_label(path_or_url: str) -> str:
    parsed = urllib.parse.urlparse(path_or_url)
    if parsed.scheme and parsed.netloc:
        return parsed.path or parsed.netloc
    return path_or_url


def _validate_env_assignment(key: str, value: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError(f"Invalid environment key: {key}")
    if "\n" in value or "\r" in value:
        raise ValueError(f"Environment value for {key} cannot contain newlines.")


def _chmod_owner_read_write(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _format_expires_at(value: int | None) -> str:
    if value == 0:
        return "0 (non-expiring)"
    if value is None:
        return "unknown"
    try:
        timestamp = dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return str(value)
    return f"{value} ({timestamp})"


def main(
    *,
    graph_api_base_url: str,
    profile_alias: str,
    page_id: str,
    app_id: str,
    env_file: Path | None = None,
    print_page_token: bool = False,
) -> int:
    missing_config = _missing_inline_config(
        {
            "GRAPH_API_BASE_URL": graph_api_base_url,
            "DEFAULT_PROFILE_ALIAS": profile_alias,
            "DEFAULT_PAGE_ID": page_id,
            "META_APP_ID": app_id,
        }
    )
    if missing_config:
        logger.error(
            "Fill in these constants inside the __main__ block before running this script:\n{}",
            "\n".join(f"- {name}" for name in missing_config),
        )
        return 1

    logger.info(
        "Meta Page token exchange helper started for profile {} and Page {}.",
        profile_alias,
        page_id,
    )
    logger.warning(
        "PyCharm Debug can mishandle hidden getpass input. If the token prompt "
        "appears stuck, press Enter; if no progress log appears after that, use "
        "PyCharm Run, enable 'Emulate terminal in output console', or run this "
        "script from a terminal."
    )
    logger.info("Prompting for Meta app secret.")
    app_secret = _prompt_secret("Meta App Secret")
    logger.info("Meta app secret prompt completed.")
    logger.info("Prompting for short-lived Graph API Explorer user token.")
    short_user_token = _prompt_secret("Short-lived Graph API Explorer user token")
    logger.info("Short-lived user token prompt completed; starting Meta API exchange.")

    try:
        if not app_secret:
            raise ValueError("Meta App Secret cannot be empty.")
        if not short_user_token:
            raise ValueError(
                "Short-lived Graph API Explorer user token cannot be empty."
            )

        result = exchange_for_page_token(
            app_id=app_id.strip(),
            app_secret=app_secret,
            short_lived_user_token=short_user_token,
            page_id=page_id.strip(),
            profile_alias=profile_alias.strip(),
            request_json=_configured_request_json(graph_api_base_url.strip()),
        )
        target_env_file = env_file or Path(__file__).resolve().parents[3] / ".env"
        backup_path = update_env_file(target_env_file, result)
    except (TokenExchangeError, ValueError) as exc:
        logger.error("Error: {}", exc)
        return 1

    logger.success(
        "{}",
        format_success_message(
            result,
            env_path=target_env_file,
            backup_path=backup_path,
            print_token=print_page_token,
        ),
    )
    return 0


if __name__ == "__main__":
    # Fill in these constants before running this file from PyCharm.
    # Graph API version/base URL used for the token exchange and validation calls.
    GRAPH_API_BASE_URL = "https://graph.facebook.com/v25.0"
    # Repo profile alias; this becomes the .env prefix, e.g. maria_larsen -> MARIA_LARSEN.
    DEFAULT_PROFILE_ALIAS = "johngalli_a"
    # Facebook Page ID whose Page token should be extracted from /me/accounts.
    DEFAULT_PAGE_ID = "123456789"
    # Meta Developer app ID used with the prompted app secret to exchange/debug tokens.
    META_APP_ID = "123456777888999"

    try:
        raise SystemExit(
            main(
                graph_api_base_url=GRAPH_API_BASE_URL,
                profile_alias=DEFAULT_PROFILE_ALIAS,
                page_id=DEFAULT_PAGE_ID,
                app_id=META_APP_ID,
            )
        )
    except KeyboardInterrupt:
        logger.warning("Cancelled.")
        raise SystemExit(130)
