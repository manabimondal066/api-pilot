"""API-level tests for Environment CRUD.

POST   /api/environments
GET    /api/environments
GET    /api/environments/{id}
PATCH  /api/environments/{id}
DELETE /api/environments/{id}
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.environment import Environment


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Overrides the conftest `db` fixture to also purge Environment rows,
    which aren't reachable via the Spec-cascade teardown conftest uses.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        async with factory() as session:
            try:
                await session.execute(text("SELECT 1"))
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"PostgreSQL not available: {exc}")
                return

            yield session

            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            try:
                await session.execute(
                    delete(Environment).where(
                        Environment.workspace_id == DEFAULT_WORKSPACE_ID
                    )
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                pass
    finally:
        await engine.dispose()


def _payload(**overrides) -> dict:
    base = {
        "name": "QA",
        "base_url": "https://qa-api.example.com",
        "auth_type": "bearer",
        "auth_config": {"token": "secret-token"},
        "default_headers": {"X-Env": "qa"},
        "variables": {"tenantId": "acme"},
    }
    base.update(overrides)
    return base


async def test_create_environment(client: AsyncClient, db: AsyncSession) -> None:
    response = await client.post("/api/environments", json=_payload())

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "QA"
    assert data["base_url"] == "https://qa-api.example.com/"
    assert data["auth_type"] == "bearer"
    assert data["auth_config"] == {"token": "secret-token"}
    assert data["default_headers"] == {"X-Env": "qa"}
    assert data["variables"] == {"tenantId": "acme"}
    assert UUID(data["id"])
    assert UUID(data["workspace_id"]) == DEFAULT_WORKSPACE_ID


async def test_create_environment_requires_name(
    client: AsyncClient, db: AsyncSession
) -> None:
    response = await client.post("/api/environments", json=_payload(name=""))
    assert response.status_code == 422, response.text


async def test_create_environment_requires_valid_url(
    client: AsyncClient, db: AsyncSession
) -> None:
    response = await client.post(
        "/api/environments", json=_payload(base_url="not-a-url")
    )
    assert response.status_code == 422, response.text


async def test_list_environments(client: AsyncClient, db: AsyncSession) -> None:
    await client.post("/api/environments", json=_payload(name="QA"))
    await client.post("/api/environments", json=_payload(name="Staging"))

    response = await client.get("/api/environments")

    assert response.status_code == 200, response.text
    names = {e["name"] for e in response.json()}
    assert names == {"QA", "Staging"}


async def test_get_environment(client: AsyncClient, db: AsyncSession) -> None:
    created = (await client.post("/api/environments", json=_payload())).json()

    response = await client.get(f"/api/environments/{created['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == created["id"]


async def test_get_unknown_environment_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.get(f"/api/environments/{unknown_id}")
    assert response.status_code == 404, response.text


async def test_update_environment(client: AsyncClient, db: AsyncSession) -> None:
    created = (await client.post("/api/environments", json=_payload())).json()

    response = await client.patch(
        f"/api/environments/{created['id']}",
        json={"name": "QA-Renamed", "variables": {"tenantId": "beta"}},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["name"] == "QA-Renamed"
    assert data["variables"] == {"tenantId": "beta"}
    # Untouched fields remain as originally set.
    assert data["base_url"] == "https://qa-api.example.com/"
    assert data["auth_type"] == "bearer"


async def test_update_unknown_environment_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.patch(
        f"/api/environments/{unknown_id}", json={"name": "X"}
    )
    assert response.status_code == 404, response.text


async def test_delete_environment(client: AsyncClient, db: AsyncSession) -> None:
    created = (await client.post("/api/environments", json=_payload())).json()

    delete_response = await client.delete(f"/api/environments/{created['id']}")
    assert delete_response.status_code == 204, delete_response.text

    get_response = await client.get(f"/api/environments/{created['id']}")
    assert get_response.status_code == 404


async def test_delete_unknown_environment_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.delete(f"/api/environments/{unknown_id}")
    assert response.status_code == 404, response.text
