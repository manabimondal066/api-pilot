"""Unit tests for the cURL parser."""

import pytest

from app.parsers.curl_parser import parse_curl
from app.parsers.enums import AuthType, HttpMethod, ParamLocation, SpecSource
from app.parsers.errors import ParserError


def test_parses_simple_get() -> None:
    spec = parse_curl("curl https://api.example.com/users", "test/1.txt")

    assert spec.source == SpecSource.CURL
    assert spec.base_url == "https://api.example.com"
    assert len(spec.endpoints) == 1

    ep = spec.endpoints[0]
    assert ep.method == HttpMethod.GET
    assert ep.path == "/users"
    assert ep.body_schema is None


def test_parses_get_with_query_params() -> None:
    spec = parse_curl(
        "curl 'https://api.example.com/users?page=2&limit=10'", "test/2.txt"
    )
    ep = spec.endpoints[0]
    assert ep.path == "/users"
    names = {p.name: p.example for p in ep.query_params}
    assert names == {"page": "2", "limit": "10"}


def test_infers_post_method_from_data_flag() -> None:
    spec = parse_curl(
        'curl https://api.example.com/users -d \'{"name": "Alice"}\'', "test/3.txt"
    )
    ep = spec.endpoints[0]
    assert ep.method == HttpMethod.POST
    assert ep.body_schema == {"name": "Alice"}


def test_explicit_method_flag_overrides_inference() -> None:
    spec = parse_curl(
        "curl -X PUT https://api.example.com/users/1 -d '{}'", "test/4.txt"
    )
    assert spec.endpoints[0].method == HttpMethod.PUT


def test_headers_are_captured() -> None:
    spec = parse_curl(
        "curl https://api.example.com/users "
        "-H 'Content-Type: application/json' "
        "-H 'X-Api-Key: abc123'",
        "test/5.txt",
    )
    ep = spec.endpoints[0]
    headers = {h.name: h.example for h in ep.headers}
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Api-Key"] == "abc123"


def test_bearer_auth_detected_from_authorization_header() -> None:
    spec = parse_curl(
        "curl https://api.example.com/me -H 'Authorization: Bearer secrettoken'",
        "test/6.txt",
    )
    ep = spec.endpoints[0]
    assert ep.auth is not None
    assert ep.auth.type == AuthType.BEARER


def test_basic_auth_from_user_flag() -> None:
    spec = parse_curl(
        "curl -u alice:hunter2 https://api.example.com/me", "test/7.txt"
    )
    ep = spec.endpoints[0]
    assert ep.auth is not None
    assert ep.auth.type == AuthType.BASIC


def test_path_params_detected_from_braces() -> None:
    spec = parse_curl(
        "curl https://api.example.com/users/{userId}/orders/{orderId}",
        "test/8.txt",
    )
    ep = spec.endpoints[0]
    names = {p.name for p in ep.path_params}
    assert names == {"userId", "orderId"}


def test_multiline_backslash_continuation() -> None:
    text = (
        "curl https://api.example.com/users \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -d '{\"name\": \"Bob\"}'"
    )
    spec = parse_curl(text, "test/9.txt")
    assert len(spec.endpoints) == 1
    ep = spec.endpoints[0]
    assert ep.method == HttpMethod.POST
    assert ep.body_schema == {"name": "Bob"}


def test_multiple_curl_commands_produce_multiple_endpoints() -> None:
    text = (
        "curl https://api.example.com/users\n"
        "curl -X DELETE https://api.example.com/users/1\n"
    )
    spec = parse_curl(text, "test/10.txt")
    assert len(spec.endpoints) == 2
    assert spec.endpoints[0].method == HttpMethod.GET
    assert spec.endpoints[1].method == HttpMethod.DELETE
    assert spec.endpoints[1].path == "/users/1"


def test_ignored_flags_do_not_break_parsing() -> None:
    spec = parse_curl(
        "curl -s -v -k --compressed -A 'MyAgent/1.0' https://api.example.com/ping",
        "test/11.txt",
    )
    ep = spec.endpoints[0]
    assert ep.method == HttpMethod.GET
    assert ep.path == "/ping"


def test_non_json_body_wrapped_as_raw() -> None:
    spec = parse_curl(
        "curl https://api.example.com/form -d 'a=1&b=2'", "test/12.txt"
    )
    ep = spec.endpoints[0]
    assert ep.body_schema == {"raw": "a=1&b=2"}


def test_raises_on_empty_input() -> None:
    with pytest.raises(ParserError):
        parse_curl("", "test/13.txt")


def test_raises_on_non_curl_input() -> None:
    with pytest.raises(ParserError):
        parse_curl("wget https://api.example.com/", "test/14.txt")


def test_raises_when_no_url_present() -> None:
    with pytest.raises(ParserError):
        parse_curl("curl -H 'Accept: application/json'", "test/15.txt")


def test_caret_line_continuation_windows_cmd_style() -> None:
    """Windows cmd.exe uses '^' for line continuation instead of '\\'."""
    text = (
        "curl https://api.example.com/users ^\n"
        "  -H \"Content-Type: application/json\" ^\n"
        "  -d \"{'name': 'Bob'}\""
    )
    spec = parse_curl(text, "test/16.txt")
    assert len(spec.endpoints) == 1
    assert spec.endpoints[0].method == HttpMethod.POST


def test_get_flag_moves_data_into_query_params() -> None:
    """-G/--get sends -d payload as query params instead of a body (curl semantics)."""
    spec = parse_curl(
        "curl -G https://api.example.com/search -d 'q=hello' -d 'page=2'",
        "test/17.txt",
    )
    ep = spec.endpoints[0]
    assert ep.method == HttpMethod.GET
    assert ep.body_schema is None
    names = {p.name: p.example for p in ep.query_params}
    assert names == {"q": "hello", "page": "2"}


def test_get_flag_merges_with_existing_query_string() -> None:
    spec = parse_curl(
        "curl -G 'https://api.example.com/search?sort=asc' -d 'q=hello'",
        "test/18.txt",
    )
    ep = spec.endpoints[0]
    names = {p.name: p.example for p in ep.query_params}
    assert names == {"sort": "asc", "q": "hello"}


def test_tokenize_error_includes_helpful_hint() -> None:
    with pytest.raises(ParserError, match="Copy as cURL"):
        parse_curl("curl https://api.example.com/x -d 'unterminated", "test/19.txt")
