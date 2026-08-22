from ai_content_pipeline.llm.error_handlers.api_error_handler import parse_retry_after


def test_parse_retry_after_uses_header_when_present():
    assert parse_retry_after({"retry-after": "17"}, default_seconds=42) == 17


def test_parse_retry_after_falls_back_to_default_when_header_missing():
    assert parse_retry_after({}, default_seconds=42) == 42


def test_parse_retry_after_falls_back_to_default_when_header_unparseable():
    assert parse_retry_after({"retry-after": "not-a-number"}, default_seconds=42) == 42


def test_parse_retry_after_clamps_negative_values_to_zero():
    assert parse_retry_after({"retry-after": "-5"}, default_seconds=42) == 0
