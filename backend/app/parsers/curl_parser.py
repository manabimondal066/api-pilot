"""cURL command parser.

Public entry point::

    spec = parse_curl(text, raw_spec_ref)

Accepts one or more ``curl ...`` commands (as copied from a browser's
DevTools "Copy as cURL", Postman, or typed by hand) and normalises them into
the same :class:`~app.parsers.models.ParsedSpec` shape the Swagger parser
produces, so the rest of the import pipeline (suite/endpoint creation) does
not need to know or care where the data came from.

Scope (Phase 1): bash/POSIX-style quoting via :mod:`shlex`. Windows
cmd.exe (``^`` continuations) and PowerShell (`` ` `` continuations, backtick
escaping) quoting styles are out of scope for this phase.
"""

from __future__ import annotations

import json
import re
import shlex
from urllib.parse import parse_qsl, urlsplit

from app.parsers.enums import AuthType, HttpMethod, ParamLocation, SpecSource
from app.parsers.errors import ParserError
from app.parsers.models import AuthSpec, Param, ParsedEndpoint, ParsedSpec

# Flags that take no argument — safe to skip over during tokenisation.
_NO_ARG_FLAGS: frozenset[str] = frozenset(
    {
        "-s", "--silent",
        "-v", "--verbose",
        "-i", "--include",
        "-k", "--insecure",
        "-L", "--location",
        "-f", "--fail",
        "-c", "--continue-at",
        "-#", "--progress-bar",
        "--compressed",
        "-N", "--no-buffer",
        "-g", "--globoff",
        "-4", "--ipv4",
        "-6", "--ipv6",
        "--http1.1", "--http2",
        "--insecure",
    }
)

# Flags that take one argument but we intentionally don't need for the
# normalised model (still must be consumed so we don't mis-parse the URL).
_IGNORED_VALUE_FLAGS: frozenset[str] = frozenset(
    {
        "-o", "--output",
        "-A", "--user-agent",
        "-e", "--referer",
        "--connect-timeout",
        "-m", "--max-time",
        "--retry",
        "-w", "--write-out",
        "--cacert",
        "--cert",
        "--key",
    }
)

_DATA_FLAGS: frozenset[str] = frozenset(
    {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}
)

_PATH_PARAM_RE = re.compile(r"\{([^{}]+)\}")

_SUPPORTED_METHODS: frozenset[str] = frozenset(m.value for m in HttpMethod)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_") or "request"


def _split_commands(text: str) -> list[str]:
    """Split *text* into individual ``curl ...`` command strings.

    Joins line-continuations first (``\\`` for bash, ``^`` for Windows
    cmd.exe), then splits wherever a (trimmed) line begins a new ``curl``
    invocation.
    """
    # Join "...\" / "...^" + newline -> single logical line.
    joined = re.sub(r"[\\^]\s*\r?\n\s*", " ", text)

    lines = joined.splitlines()
    commands: list[str] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()
        if re.match(r"^curl(\s|$)", stripped):
            if current:
                commands.append(" ".join(current))
            current = [stripped]
        elif stripped:
            current.append(stripped)
    if current:
        commands.append(" ".join(current))

    return [c for c in commands if c.strip()]


def _parse_header(raw: str) -> tuple[str, str] | None:
    if ":" not in raw:
        return None
    name, _, value = raw.partition(":")
    return name.strip(), value.strip()


def _auth_from_headers(headers: list[tuple[str, str]]) -> AuthSpec | None:
    for name, value in headers:
        if name.lower() == "authorization":
            if value.lower().startswith("bearer "):
                return AuthSpec(type=AuthType.BEARER, scheme="bearer", name="Authorization")
            if value.lower().startswith("basic "):
                return AuthSpec(type=AuthType.BASIC, name="Authorization")
            return AuthSpec(type=AuthType.CUSTOM, name="Authorization")
    return None


def _body_schema_from_data(data_parts: list[str]) -> dict | None:
    if not data_parts:
        return None
    raw = "&".join(data_parts)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"raw": parsed}


def _tokenize(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError as exc:
        raise ParserError(
            f"Could not tokenize cURL command ({exc}). "
            "Only bash/POSIX-style quoting (single or double quotes, "
            "'\\' line continuation) is supported — if this was copied from "
            "a Windows cmd.exe prompt, use your browser's 'Copy as cURL "
            "(bash)' option instead."
        ) from exc


def _parse_one(command: str) -> ParsedEndpoint:
    tokens = _tokenize(command)
    if not tokens or tokens[0] != "curl":
        raise ParserError("Expected command to start with 'curl'")

    method: str | None = None
    url: str | None = None
    headers: list[tuple[str, str]] = []
    data_parts: list[str] = []
    user_pass: str | None = None
    cookie: str | None = None
    force_get = False

    i = 1
    n = len(tokens)
    while i < n:
        tok = tokens[i]

        if tok in ("-G", "--get"):
            force_get = True
            i += 1
            continue

        if tok in _NO_ARG_FLAGS:
            i += 1
            continue

        if tok in ("-X", "--request"):
            i += 1
            if i >= n:
                raise ParserError(f"Flag {tok!r} expects a value")
            method = tokens[i].upper()
            i += 1
            continue

        if tok in ("-H", "--header"):
            i += 1
            if i >= n:
                raise ParserError(f"Flag {tok!r} expects a value")
            parsed = _parse_header(tokens[i])
            if parsed is not None:
                headers.append(parsed)
            i += 1
            continue

        if tok in _DATA_FLAGS:
            i += 1
            if i >= n:
                raise ParserError(f"Flag {tok!r} expects a value")
            data_parts.append(tokens[i])
            i += 1
            continue

        if tok in ("-u", "--user"):
            i += 1
            if i >= n:
                raise ParserError(f"Flag {tok!r} expects a value")
            user_pass = tokens[i]
            i += 1
            continue

        if tok in ("-b", "--cookie"):
            i += 1
            if i >= n:
                raise ParserError(f"Flag {tok!r} expects a value")
            cookie = tokens[i]
            i += 1
            continue

        if tok == "--url":
            i += 1
            if i >= n:
                raise ParserError("Flag '--url' expects a value")
            url = tokens[i]
            i += 1
            continue

        if tok in _IGNORED_VALUE_FLAGS:
            i += 2
            continue

        if tok.startswith("-"):
            # Unknown flag — skip it; assume no argument to stay conservative.
            i += 1
            continue

        # Positional argument: the URL.
        if url is None:
            url = tok
        i += 1

    if url is None:
        raise ParserError("Could not find a URL in cURL command")

    if user_pass is not None:
        auth: AuthSpec | None = AuthSpec(type=AuthType.BASIC, name="Authorization")
    else:
        auth = _auth_from_headers(headers)

    if cookie is not None:
        headers.append(("Cookie", cookie))

    # -G/--get: curl moves any -d/--data payload into the URL's query string
    # instead of sending it as a body, and defaults to GET.
    extra_query_raw = ""
    if force_get:
        extra_query_raw = "&".join(data_parts)
        data_parts = []

    if method is None:
        method = "GET" if force_get else ("POST" if data_parts else "GET")
    if method not in _SUPPORTED_METHODS:
        raise ParserError(f"Unsupported HTTP method: {method}")

    parts = urlsplit(url)
    path = parts.path or "/"

    combined_query = parts.query
    if extra_query_raw:
        combined_query = f"{combined_query}&{extra_query_raw}" if combined_query else extra_query_raw

    query_params = [
        Param(name=k, location=ParamLocation.QUERY, required=True, example=v)
        for k, v in parse_qsl(combined_query, keep_blank_values=True)
    ]

    path_params = [
        Param(name=m, location=ParamLocation.PATH, required=True)
        for m in _PATH_PARAM_RE.findall(path)
    ]

    header_params = [
        Param(name=name, location=ParamLocation.HEADER, required=False, example=value)
        for name, value in headers
    ]

    return ParsedEndpoint(
        method=HttpMethod(method),
        path=path,
        name=_slug(f"{method.lower()}_{path}"),
        description=None,
        path_params=path_params,
        query_params=query_params,
        headers=header_params,
        body_schema=_body_schema_from_data(data_parts),
        response_schemas={},
        auth=auth,
        tags=[],
    )


def parse_curl(text: str, raw_spec_ref: str) -> ParsedSpec:
    """Parse one or more ``curl`` commands in *text* into a :class:`ParsedSpec`.

    Args:
        text:          Raw text containing one or more ``curl ...`` invocations.
        raw_spec_ref:  Storage key where the original text is persisted.

    Returns:
        A :class:`ParsedSpec` with ``source=SpecSource.CURL``.

    Raises:
        ParserError: if no valid ``curl`` command can be found/parsed.
    """
    commands = _split_commands(text)
    if not commands:
        raise ParserError("No 'curl' command found in input")

    endpoints = [_parse_one(cmd) for cmd in commands]

    base_url: str | None = None
    first_url = urlsplit(_first_url(commands[0]))
    if first_url.scheme and first_url.netloc:
        base_url = f"{first_url.scheme}://{first_url.netloc}"

    title = base_url or "Imported from cURL"

    return ParsedSpec(
        source=SpecSource.CURL,
        title=title,
        version=None,
        base_url=base_url,
        endpoints=endpoints,
        raw_spec_ref=raw_spec_ref,
    )


def _first_url(command: str) -> str:
    """Best-effort extraction of the URL from a single command, for base_url."""
    tokens = _tokenize(command)
    i = 1
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in ("--url",):
            return tokens[i + 1] if i + 1 < n else ""
        if tok in ("-X", "--request", "-H", "--header", *(_DATA_FLAGS), "-u", "--user", "-b", "--cookie", *(_IGNORED_VALUE_FLAGS)):
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok
    return ""
