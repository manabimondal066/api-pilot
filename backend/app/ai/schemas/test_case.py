from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.parsers.enums import HttpMethod


class ValidationType(str, Enum):
    STATUS_CODE = "STATUS_CODE"
    FIELD_EXISTS = "FIELD_EXISTS"
    FIELD_EQUALS = "FIELD_EQUALS"
    FIELD_TYPE = "FIELD_TYPE"
    FIELD_REGEX = "FIELD_REGEX"
    FIELD_RANGE = "FIELD_RANGE"
    SCHEMA_MATCH = "SCHEMA_MATCH"
    RESPONSE_TIME = "RESPONSE_TIME"
    CUSTOM_JSONPATH = "CUSTOM_JSONPATH"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"


class TestCategory(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    EDGE = "EDGE"


class Validation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: ValidationType
    description: str = Field(..., description="Human-readable: 'Status code is 201'")
    target: str | None = Field(default=None, description="JSONPath like '$.user.id'")
    expected: Any | None = None
    severity: Severity = Severity.CRITICAL


class Extraction(BaseModel):
    name: str = Field(..., description="Variable name, e.g. 'userId'")
    source: str = Field(..., description="JSONPath in response, e.g. '$.id'")


class TestCase(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    endpoint_id: str | None = None  # populated by orchestration service, not AI
    name: str = Field(..., description="Short, descriptive: 'Create user with invalid email returns 400'")
    category: TestCategory
    description: str
    method: HttpMethod
    path: str = Field(..., description="Path with {placeholders} or {{variables}}")
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None
    validations: list[Validation] = Field(default_factory=list)
    extractions: list[Extraction] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="AI self-rated confidence 0-1",
    )
    ai_notes: str | None = None


class TestCaseList(BaseModel):
    """Wrapper for the AI's output. Instructor needs a single root model."""
    tests: list[TestCase] = Field(default_factory=list)
