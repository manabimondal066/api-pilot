"""Service-layer tests for test_service.add_validation / remove_validation
(Implementation Plan Module 9 — the write path shared by PATCH
/api/tests/{id}/validations and the chat agent's tools).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.test import Test
from app.services import TestNotFoundError, ValidationNotFoundError
from app.services import test_service
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"

OTHER_WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")


async def _create_test(db: AsyncSession) -> tuple[UUID, UUID]:
    """Import a suite and insert one bare Test row. Returns (suite_id, test_id)."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    endpoint_id = suite.endpoints[0].id

    test = Test(
        suite_id=suite.id,
        endpoint_id=endpoint_id,
        name="Get pet by id",
        category="POSITIVE",
        method="GET",
        path="/pet/{petId}",
        validations=[
            {
                "id": "v1",
                "type": "STATUS_CODE",
                "description": "Status code is 200",
                "target": None,
                "expected": 200,
                "severity": "CRITICAL",
            }
        ],
    )
    db.add(test)
    await db.commit()
    return suite.id, test.id


async def test_add_validation_appends_and_bumps_version(db: AsyncSession):
    _, test_id = await _create_test(db)

    updated = await test_service.add_validation(
        db,
        test_id,
        DEFAULT_WORKSPACE_ID,
        {"type": "FIELD_EXISTS", "description": "Response has id", "target": "$.id"},
    )

    assert len(updated.validations) == 2
    assert updated.validations[1]["type"] == "FIELD_EXISTS"
    assert updated.version == 2


async def test_add_validation_rejects_malformed_shape(db: AsyncSession):
    _, test_id = await _create_test(db)

    with pytest.raises(Exception):
        await test_service.add_validation(
            db, test_id, DEFAULT_WORKSPACE_ID, {"description": "missing type"}
        )


async def test_add_validation_rejects_test_from_other_workspace(db: AsyncSession):
    _, test_id = await _create_test(db)

    with pytest.raises(TestNotFoundError):
        await test_service.add_validation(
            db,
            test_id,
            OTHER_WORKSPACE_ID,
            {"type": "STATUS_CODE", "description": "x", "expected": 200},
        )


async def test_remove_validation_removes_matching_entry(db: AsyncSession):
    _, test_id = await _create_test(db)

    updated = await test_service.remove_validation(db, test_id, DEFAULT_WORKSPACE_ID, "v1")

    assert updated.validations == []
    assert updated.version == 2


async def test_remove_validation_raises_when_id_not_found(db: AsyncSession):
    _, test_id = await _create_test(db)

    with pytest.raises(ValidationNotFoundError):
        await test_service.remove_validation(db, test_id, DEFAULT_WORKSPACE_ID, "does-not-exist")


async def test_remove_validation_rejects_test_from_other_workspace(db: AsyncSession):
    _, test_id = await _create_test(db)

    with pytest.raises(TestNotFoundError):
        await test_service.remove_validation(db, test_id, OTHER_WORKSPACE_ID, "v1")


async def test_add_validation_unknown_test_id_raises(db: AsyncSession):
    with pytest.raises(TestNotFoundError):
        await test_service.add_validation(
            db,
            uuid4(),
            DEFAULT_WORKSPACE_ID,
            {"type": "STATUS_CODE", "description": "x", "expected": 200},
        )
