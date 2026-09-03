"""Enumerations used across the parsers domain."""

from enum import Enum


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class SpecSource(str, Enum):
    SWAGGER = "SWAGGER"
    POSTMAN = "POSTMAN"
    CURL = "CURL"


class ParamLocation(str, Enum):
    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"
    BODY = "body"


class AuthType(str, Enum):
    NONE = "NONE"
    BEARER = "BEARER"
    BASIC = "BASIC"
    API_KEY = "API_KEY"
    OAUTH2 = "OAUTH2"
    CUSTOM = "CUSTOM"
