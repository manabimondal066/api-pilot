"""Pydantic models for the normalised parser output.

These models are the contract between the parser layer and the rest of the
application.  Callers receive a ParsedSpec and never need to deal with raw
Swagger / OpenAPI dicts directly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.parsers.enums import AuthType, HttpMethod, ParamLocation, SpecSource


class Param(BaseModel):
    """A single operation parameter (path, query, header, or body)."""

    name: str
    location: ParamLocation
    required: bool = False
    # Aliased as "schema" in JSON serialisation to match the spec field name.
    # The attribute is schema_ to avoid shadowing Pydantic internals.
    schema_: dict | None = Field(default=None, alias="schema")
    description: str | None = None
    example: Any | None = None

    model_config = ConfigDict(populate_by_name=True)


class AuthSpec(BaseModel):
    """Describes the authentication scheme required by an endpoint."""

    type: AuthType
    # Header / query-param name for API_KEY; scheme name for others
    name: str | None = None
    # Where the credential is sent (relevant for API_KEY)
    location: ParamLocation | None = None
    # HTTP auth scheme string, e.g. "bearer", "basic"
    scheme: str | None = None
    description: str | None = None


class ParsedEndpoint(BaseModel):
    """A single, normalised API operation extracted from a spec."""

    method: HttpMethod
    path: str                           # e.g. /users/{userId}
    name: str                           # operationId or auto-generated slug
    description: str | None = None
    path_params: list[Param] = Field(default_factory=list)
    query_params: list[Param] = Field(default_factory=list)
    headers: list[Param] = Field(default_factory=list)
    body_schema: dict | None = None     # JSON Schema fragment for request body
    # Keys are HTTP status codes as integers (200, 404, …)
    response_schemas: dict[int, dict] = Field(default_factory=dict)
    auth: AuthSpec | None = None
    tags: list[str] = Field(default_factory=list)


class ParsedSpec(BaseModel):
    """The complete, normalised representation of a parsed API specification."""

    source: SpecSource
    title: str
    version: str | None = None
    base_url: str | None = None
    endpoints: list[ParsedEndpoint] = Field(default_factory=list)
    raw_spec_ref: str                   # storage key where the original file lives
