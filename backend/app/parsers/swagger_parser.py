"""Swagger 2.0 / OpenAPI 3.x parser.

Public entry point::

    spec = await parse_swagger(content, raw_spec_ref, filename)

The function is ``async`` so it fits naturally into FastAPI route handlers and
can be awaited after, e.g., reading the uploaded file from storage.  The heavy
lifting (JSON/YAML parsing, prance $ref resolution) is synchronous but fast
enough to run on the event loop for typical spec sizes; move to an executor if
profiling shows it blocking.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import yaml

from app.parsers.enums import AuthType, HttpMethod, ParamLocation, SpecSource
from app.parsers.errors import ParserError
from app.parsers.models import AuthSpec, Param, ParsedEndpoint, ParsedSpec

logger = logging.getLogger(__name__)

# HTTP methods we surface in the unified model.  Others (OPTIONS, HEAD,
# TRACE, …) are silently skipped per Implementation Plan §6.1.
_SUPPORTED_METHODS: frozenset[str] = frozenset(m.value for m in HttpMethod)

# Regex used to turn arbitrary strings into safe Python identifier slugs.
_NON_IDENT = re.compile(r"[^a-zA-Z0-9]+")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Convert *text* to a safe slug (underscores, no leading/trailing)."""
    return _NON_IDENT.sub("_", text).strip("_")


def _parse_raw(content: bytes) -> dict:
    """Decode *content* bytes and parse as JSON or YAML.

    Raises:
        ParserError: if neither format succeeds or the result is not a dict.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")

    # Try JSON first — faster and unambiguous for .json files.
    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ParserError(
                f"Spec must be a JSON object, got {type(result).__name__}"
            )
        return result
    except json.JSONDecodeError:
        pass

    # Fall back to YAML.
    try:
        result = yaml.safe_load(text)
        if result is None:
            raise ParserError("Spec content is empty")
        if not isinstance(result, dict):
            raise ParserError(
                f"Spec must be a YAML mapping, got {type(result).__name__}"
            )
        return result
    except yaml.YAMLError as exc:
        raise ParserError(f"Could not parse as JSON or YAML: {exc}") from exc


def _resolve_refs(raw_dict: dict) -> dict:
    """Use prance to inline all ``$ref`` pointers in *raw_dict*.

    Falls back to the unresolved dict if prance fails (e.g. external refs
    that cannot be fetched in unit tests, or minor spec violations).
    """
    try:
        import prance  # local import — optional heavy dependency

        spec_str = json.dumps(raw_dict)
        parser = prance.ResolvingParser(
            spec_string=spec_str,
            backend="openapi-spec-validator",
            strict=False,
        )
        return parser.specification  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "prance $ref resolution failed (%s); continuing with unresolved spec",
            exc,
        )
        return raw_dict


# ---------------------------------------------------------------------------
# Base URL extraction
# ---------------------------------------------------------------------------


def _base_url_v2(spec: dict) -> str | None:
    host = spec.get("host", "")
    base_path = spec.get("basePath", "")
    schemes = spec.get("schemes") or ["https"]
    scheme = schemes[0] if schemes else "https"
    if host:
        return f"{scheme}://{host}{base_path}"
    return None


def _base_url_v3(spec: dict) -> str | None:
    servers = spec.get("servers") or []
    if servers and isinstance(servers[0], dict):
        return servers[0].get("url")
    return None


# ---------------------------------------------------------------------------
# Auth extraction
# ---------------------------------------------------------------------------


def _auth_from_scheme_def(scheme_name: str, scheme_def: dict) -> AuthSpec | None:
    """Convert a single security scheme definition to an :class:`AuthSpec`."""
    s_type = (scheme_def.get("type") or "").lower()

    if s_type == "oauth2":
        return AuthSpec(type=AuthType.OAUTH2, name=scheme_name)

    if s_type == "apikey":
        in_ = (scheme_def.get("in") or "header").lower()
        loc = ParamLocation.HEADER if in_ == "header" else ParamLocation.QUERY
        return AuthSpec(
            type=AuthType.API_KEY,
            name=scheme_def.get("name", scheme_name),
            location=loc,
        )

    if s_type in ("basic",):
        return AuthSpec(type=AuthType.BASIC, name=scheme_name)

    if s_type == "http":
        scheme = (scheme_def.get("scheme") or "bearer").lower()
        if scheme == "bearer":
            return AuthSpec(type=AuthType.BEARER, scheme="bearer", name=scheme_name)
        if scheme == "basic":
            return AuthSpec(type=AuthType.BASIC, name=scheme_name)

    return None


def _extract_auth_v2(spec: dict, operation: dict) -> AuthSpec | None:
    security = operation.get("security") or spec.get("security") or []
    defs = spec.get("securityDefinitions") or {}
    for req in security:
        if not isinstance(req, dict):
            continue
        for scheme_name in req:
            auth = _auth_from_scheme_def(scheme_name, defs.get(scheme_name) or {})
            if auth is not None:
                return auth
    return None


def _extract_auth_v3(spec: dict, operation: dict) -> AuthSpec | None:
    security = operation.get("security") or spec.get("security") or []
    schemes = ((spec.get("components") or {}).get("securitySchemes")) or {}
    for req in security:
        if not isinstance(req, dict):
            continue
        for scheme_name in req:
            auth = _auth_from_scheme_def(scheme_name, schemes.get(scheme_name) or {})
            if auth is not None:
                return auth
    return None


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------


def _make_param(p: dict) -> Param | None:
    """Convert a raw parameter dict to a :class:`Param`, or return ``None``."""
    name = p.get("name")
    in_ = p.get("in")
    if not name or not in_:
        return None
    try:
        loc = ParamLocation(in_)
    except ValueError:
        return None  # unknown location — skip
    return Param(
        name=name,
        location=loc,
        required=bool(p.get("required", False)),
        **{"schema": p.get("schema")},  # use alias to set schema_
        description=p.get("description"),
        example=p.get("example"),
    )


def _merge_params(path_level: list, op_level: list) -> list[dict]:
    """Merge path-level and operation-level parameters.

    Operation parameters override path-level ones with the same (name, in)
    pair, as required by the OpenAPI spec.
    """
    merged: dict[tuple[str, str], dict] = {}
    for p in path_level:
        if isinstance(p, dict) and p.get("name") and p.get("in"):
            merged[(p["name"], p["in"])] = p
    for p in op_level:
        if isinstance(p, dict) and p.get("name") and p.get("in"):
            merged[(p["name"], p["in"])] = p
    return list(merged.values())


# ---------------------------------------------------------------------------
# Endpoint extraction — Swagger 2.0
# ---------------------------------------------------------------------------


def _extract_endpoints_v2(spec: dict) -> list[ParsedEndpoint]:
    endpoints: list[ParsedEndpoint] = []
    paths = spec.get("paths") or {}

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_params_raw = path_item.get("parameters") or []

        for method, operation in path_item.items():
            method_upper = method.upper()
            if method_upper not in _SUPPORTED_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            all_params = _merge_params(path_params_raw, operation.get("parameters") or [])

            path_p: list[Param] = []
            query_p: list[Param] = []
            header_p: list[Param] = []
            body_s: dict | None = None

            for raw_p in all_params:
                if raw_p.get("in") == "body":
                    # v2 body param carries its schema inline
                    body_s = raw_p.get("schema")
                    continue
                param = _make_param(raw_p)
                if param is None:
                    continue
                if param.location == ParamLocation.PATH:
                    path_p.append(param)
                elif param.location == ParamLocation.QUERY:
                    query_p.append(param)
                elif param.location == ParamLocation.HEADER:
                    header_p.append(param)

            # Response schemas
            response_schemas: dict[int, dict] = {}
            for code, resp in (operation.get("responses") or {}).items():
                try:
                    code_int = int(code)
                except (ValueError, TypeError):
                    continue
                if isinstance(resp, dict) and "schema" in resp:
                    response_schemas[code_int] = resp["schema"]

            op_id = operation.get("operationId")
            name = op_id if op_id else _slug(f"{method.lower()}_{path}")

            endpoints.append(
                ParsedEndpoint(
                    method=HttpMethod(method_upper),
                    path=path,
                    name=name,
                    description=operation.get("summary") or operation.get("description"),
                    path_params=path_p,
                    query_params=query_p,
                    headers=header_p,
                    body_schema=body_s,
                    response_schemas=response_schemas,
                    auth=_extract_auth_v2(spec, operation),
                    tags=operation.get("tags") or [],
                )
            )

    return endpoints


# ---------------------------------------------------------------------------
# Endpoint extraction — OpenAPI 3.x
# ---------------------------------------------------------------------------


def _extract_endpoints_v3(spec: dict) -> list[ParsedEndpoint]:
    endpoints: list[ParsedEndpoint] = []
    paths = spec.get("paths") or {}

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_params_raw = path_item.get("parameters") or []

        for method, operation in path_item.items():
            method_upper = method.upper()
            if method_upper not in _SUPPORTED_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            all_params = _merge_params(path_params_raw, operation.get("parameters") or [])

            path_p: list[Param] = []
            query_p: list[Param] = []
            header_p: list[Param] = []

            for raw_p in all_params:
                param = _make_param(raw_p)
                if param is None:
                    continue
                if param.location == ParamLocation.PATH:
                    path_p.append(param)
                elif param.location == ParamLocation.QUERY:
                    query_p.append(param)
                elif param.location == ParamLocation.HEADER:
                    header_p.append(param)

            # Body schema from requestBody
            body_s: dict | None = None
            req_body = operation.get("requestBody")
            if req_body and isinstance(req_body, dict):
                content_map = req_body.get("content") or {}
                for media_type in (
                    "application/json",
                    "application/x-www-form-urlencoded",
                    "multipart/form-data",
                ):
                    media = content_map.get(media_type)
                    if isinstance(media, dict) and "schema" in media:
                        body_s = media["schema"]
                        break

            # Response schemas — pick first schema per status code
            response_schemas: dict[int, dict] = {}
            for code, resp in (operation.get("responses") or {}).items():
                try:
                    code_int = int(code)
                except (ValueError, TypeError):
                    continue
                if not isinstance(resp, dict):
                    continue
                for media in (resp.get("content") or {}).values():
                    if isinstance(media, dict) and "schema" in media:
                        response_schemas[code_int] = media["schema"]
                        break

            op_id = operation.get("operationId")
            name = op_id if op_id else _slug(f"{method.lower()}_{path}")

            endpoints.append(
                ParsedEndpoint(
                    method=HttpMethod(method_upper),
                    path=path,
                    name=name,
                    description=operation.get("summary") or operation.get("description"),
                    path_params=path_p,
                    query_params=query_p,
                    headers=header_p,
                    body_schema=body_s,
                    response_schemas=response_schemas,
                    auth=_extract_auth_v3(spec, operation),
                    tags=operation.get("tags") or [],
                )
            )

    return endpoints


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def parse_swagger(
    content: bytes,
    raw_spec_ref: str,
    filename: str | None = None,
) -> ParsedSpec:
    """Parse Swagger 2.0 or OpenAPI 3.x *content* into a :class:`ParsedSpec`.

    Args:
        content:       Raw file bytes (JSON or YAML).
        raw_spec_ref:  Storage key where the original file is persisted.
        filename:      Optional original filename (unused today; reserved for
                       future format disambiguation hints).

    Returns:
        A fully populated :class:`ParsedSpec`.

    Raises:
        ParserError: If *content* cannot be parsed as JSON/YAML, or if the
                     parsed document is not recognisable as Swagger/OpenAPI.
    """
    # 1. Parse bytes → dict
    raw_dict = _parse_raw(content)

    # 2. Resolve $refs
    spec = _resolve_refs(raw_dict)

    # 3. Detect spec version
    swagger_field = str(spec.get("swagger") or "")
    openapi_field = str(spec.get("openapi") or "")
    is_v2 = swagger_field.startswith("2.")
    is_v3 = openapi_field.startswith("3.")

    if not is_v2 and not is_v3:
        raise ParserError(
            "Cannot determine spec version — document must contain "
            "'swagger: \"2.0\"' or 'openapi: \"3.x.x\"' at the root level.",
            location="root",
        )

    # 4. Extract metadata
    info: dict[str, Any] = spec.get("info") or {}
    title: str = info.get("title") or "Untitled"
    version_raw = info.get("version")
    version = str(version_raw) if version_raw is not None else None

    if is_v2:
        base_url = _base_url_v2(spec)
        endpoints = _extract_endpoints_v2(spec)
    else:
        base_url = _base_url_v3(spec)
        endpoints = _extract_endpoints_v3(spec)

    logger.info("Parsed %d endpoints from %r", len(endpoints), title)

    return ParsedSpec(
        source=SpecSource.SWAGGER,
        title=title,
        version=version,
        base_url=base_url,
        endpoints=endpoints,
        raw_spec_ref=raw_spec_ref,
    )
