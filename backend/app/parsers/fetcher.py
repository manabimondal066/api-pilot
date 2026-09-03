"""HTTP helper for fetching a Swagger / OpenAPI spec from a URL.

Usage::

    content, filename = await fetch_spec_from_url("https://example.com/openapi.json")

The filename is derived (in priority order) from:
1. ``Content-Disposition`` response header
2. The last path segment of the URL (if it contains a dot)
3. A content-sniffed default: ``"spec.json"`` or ``"spec.yaml"``
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from app.parsers.errors import ParserError

# Maximum accepted response body size (10 MB).  Real-world specs are <1 MB;
# this guards against accidentally fetching gigantic files.
_MAX_BYTES = 10 * 1024 * 1024


def _filename_from_response(url: str, response: httpx.Response) -> str:
    """Derive a suggested filename from the response metadata."""
    # 1. Content-Disposition header
    cd = response.headers.get("content-disposition", "")
    if cd:
        m = re.search(r'filename="([^"]+)"', cd) or re.search(r"filename=([^\s;]+)", cd)
        if m:
            name = m.group(1).strip('"').strip()
            if name:
                return name

    # 2. URL path — last segment that looks like a filename
    path = urlparse(url).path
    if path:
        segment = path.rstrip("/").split("/")[-1]
        if segment and "." in segment:
            return segment

    # 3. Content-sniff default
    try:
        import json

        json.loads(response.content.decode("utf-8", errors="replace"))
        return "spec.json"
    except (ValueError, UnicodeDecodeError):
        return "spec.yaml"


async def fetch_spec_from_url(
    url: str,
    timeout: float = 30.0,
) -> tuple[bytes, str]:
    """Fetch a Swagger / OpenAPI spec from *url*.

    Args:
        url:     Full HTTP(S) URL of the spec file.
        timeout: Request timeout in seconds (default 30 s).

    Returns:
        ``(content_bytes, suggested_filename)`` — filename is derived from
        the ``Content-Disposition`` header, the URL path, or a default.

    Raises:
        ParserError: On HTTP errors, timeouts, empty responses, or if the
                     response body exceeds 10 MB.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise ParserError(f"Timeout fetching spec from {url!r}") from exc
    except httpx.RequestError as exc:
        raise ParserError(f"Request error fetching spec from {url!r}: {exc}") from exc

    if not response.is_success:
        raise ParserError(
            f"HTTP {response.status_code} fetching spec from {url!r}"
        )

    content = response.content
    if not content:
        raise ParserError(f"Empty response body from {url!r}")

    if len(content) > _MAX_BYTES:
        raise ParserError(
            f"Response body too large ({len(content):,} bytes, limit {_MAX_BYTES:,}) "
            f"from {url!r}"
        )

    filename = _filename_from_response(url, response)
    return content, filename
