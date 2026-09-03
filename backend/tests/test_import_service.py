"""Integration tests for the spec import service.

These tests require a live PostgreSQL instance.  If the DB is unreachable
every test is automatically skipped (same pattern as test_db_integration.py).

The default workspace (DEFAULT_WORKSPACE_ID) is already seeded in the DB by
the Sprint 1a migration, so we don't need to create workspaces in tests.

Cleanup strategy
----------------
After every test the ``db`` fixture deletes all Spec rows for
DEFAULT_WORKSPACE_ID.  Because both suites and endpoints carry CASCADE foreign
keys, the single DELETE is sufficient to remove all test data.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.endpoint import Endpoint
from app.models.environment import Environment
from app.models.spec import Spec
from app.models.suite import Suite
from app.parsers.models import ParsedEndpoint
from app.services import SpecImportError
from app.services.import_service import import_from_curl, import_from_upload, import_from_url

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession connected to local PostgreSQL.

    Skips the test if the database is unreachable.
    Deletes all Spec rows for DEFAULT_WORKSPACE_ID after each test
    (cascade removes suites + endpoints automatically).
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

            # Teardown — roll back any uncommitted state from the test, then
            # delete committed records created during the test.
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            try:
                await session.execute(
                    delete(Spec).where(Spec.workspace_id == DEFAULT_WORKSPACE_ID)
                )
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


# ---------------------------------------------------------------------------
# Test 1 — petstore v3 full import
# ---------------------------------------------------------------------------


async def test_import_from_upload_petstore_v3_creates_suite_and_endpoints(
    db: AsyncSession,
) -> None:
    """Importing petstore_v3.json creates the expected suite with 19 endpoints."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()

    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")

    assert suite.name == "Swagger Petstore - OpenAPI 3.0"
    assert len(suite.endpoints) == 19
    assert suite.generation_status == "parsed"

    # Verify Spec row fields
    spec_result = await db.execute(select(Spec).where(Spec.id == suite.spec_id))
    spec = spec_result.scalar_one()
    assert spec.parsed_at is not None, "parsed_at must be set after successful import"
    assert spec.original_filename == "petstore_v3.json"
    assert spec.source_url is None


# ---------------------------------------------------------------------------
# Test 2 — petstore v2 full import
# ---------------------------------------------------------------------------


async def test_import_from_upload_petstore_v2_works(db: AsyncSession) -> None:
    """Importing petstore_v2.json creates a suite with at least one endpoint."""
    content = (FIXTURES / "petstore_v2.json").read_bytes()

    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v2.json")

    assert suite.generation_status == "parsed"
    assert len(suite.endpoints) > 0
    assert suite.name  # non-empty title

    spec_result = await db.execute(select(Spec).where(Spec.id == suite.spec_id))
    spec = spec_result.scalar_one()
    assert spec.parsed_at is not None
    assert spec.original_filename == "petstore_v2.json"
    assert spec.source_url is None


# ---------------------------------------------------------------------------
# Test 3 — storage round-trip
# ---------------------------------------------------------------------------


async def test_import_from_upload_writes_file_to_storage(db: AsyncSession) -> None:
    """The raw content must be readable back from storage using the spec's key."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()

    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")

    spec_result = await db.execute(select(Spec).where(Spec.id == suite.spec_id))
    spec = spec_result.scalar_one()

    from app.storage.factory import get_storage

    stored = await get_storage().read(spec.storage_key)
    assert stored == content, "Round-tripped bytes must match original content"


# ---------------------------------------------------------------------------
# Test 4 — invalid spec rolls back DB
# ---------------------------------------------------------------------------


async def test_import_invalid_spec_rolls_back_db(db: AsyncSession) -> None:
    """A bad spec raises SpecImportError and leaves the DB unchanged."""
    # Count rows before
    before_specs = (
        await db.execute(
            select(func.count()).select_from(Spec).where(
                Spec.workspace_id == DEFAULT_WORKSPACE_ID
            )
        )
    ).scalar_one()
    before_suites = (
        await db.execute(
            select(func.count()).select_from(Suite).where(
                Suite.workspace_id == DEFAULT_WORKSPACE_ID
            )
        )
    ).scalar_one()

    with pytest.raises(SpecImportError):
        await import_from_upload(
            db,
            DEFAULT_WORKSPACE_ID,
            b"this is not a swagger spec at all",
            "bad.json",
        )

    # Roll back the incomplete transaction so we can query cleanly
    await db.rollback()

    after_specs = (
        await db.execute(
            select(func.count()).select_from(Spec).where(
                Spec.workspace_id == DEFAULT_WORKSPACE_ID
            )
        )
    ).scalar_one()
    after_suites = (
        await db.execute(
            select(func.count()).select_from(Suite).where(
                Suite.workspace_id == DEFAULT_WORKSPACE_ID
            )
        )
    ).scalar_one()

    assert after_specs == before_specs, "No new Spec row should have been committed"
    assert after_suites == before_suites, "No new Suite row should have been committed"


# ---------------------------------------------------------------------------
# Test 5 — failed import orphans the storage file (V1 known behaviour)
# ---------------------------------------------------------------------------


async def test_import_invalid_spec_leaves_file_orphaned(db: AsyncSession) -> None:
    """After a failed parse, the raw file remains on disk (V1 expected behaviour).

    The service writes the file to storage before attempting to parse.
    If parsing fails the DB transaction is rolled back, but the file stays.
    This is a documented V1 limitation; a cleanup job is planned for V1.5.
    """
    ws_specs_dir = Path("storage") / str(DEFAULT_WORKSPACE_ID) / "specs"

    # Snapshot the directory before the import attempt
    files_before = set(ws_specs_dir.glob("*")) if ws_specs_dir.exists() else set()

    with pytest.raises(SpecImportError):
        await import_from_upload(
            db,
            DEFAULT_WORKSPACE_ID,
            b"not a valid spec",
            "orphan.json",
        )
    await db.rollback()

    files_after = set(ws_specs_dir.glob("*")) if ws_specs_dir.exists() else set()
    new_files = files_after - files_before

    assert len(new_files) == 1, (
        f"Expected exactly 1 orphaned storage file, found: {new_files}"
    )

    # Clean up the orphaned file so storage doesn't accumulate across test runs
    for f in new_files:
        f.unlink()


# ---------------------------------------------------------------------------
# Test 6 — URL import (monkeypatched fetcher)
# ---------------------------------------------------------------------------


async def test_import_from_url_works(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """import_from_url sets source_url and leaves original_filename None."""
    petstore_bytes = (FIXTURES / "petstore_v3.json").read_bytes()
    fake_url = "https://example.com/openapi.json"

    async def _mock_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
        return petstore_bytes, "openapi.json"

    monkeypatch.setattr("app.services.import_service.fetch_spec_from_url", _mock_fetch)

    suite = await import_from_url(db, DEFAULT_WORKSPACE_ID, fake_url)

    spec_result = await db.execute(select(Spec).where(Spec.id == suite.spec_id))
    spec = spec_result.scalar_one()

    assert spec.source_url == fake_url
    assert spec.original_filename is None
    assert len(suite.endpoints) > 0


# ---------------------------------------------------------------------------
# Test 7 — unknown workspace raises
# ---------------------------------------------------------------------------


async def test_import_unknown_workspace_raises(db: AsyncSession) -> None:
    """Passing a workspace UUID that doesn't exist raises SpecImportError."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    nonexistent_workspace = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")

    with pytest.raises(SpecImportError, match="Workspace not found"):
        await import_from_upload(db, nonexistent_workspace, content, "petstore_v3.json")


# ---------------------------------------------------------------------------
# Test 8 — JSONB endpoint schema round-trips
# ---------------------------------------------------------------------------


async def test_endpoint_schema_round_trips(db: AsyncSession) -> None:
    """The JSONB endpoint_schema column must faithfully round-trip through Postgres.

    After import, read one Endpoint row directly from DB, deserialise the
    JSONB column back into a ParsedEndpoint model, and verify that method,
    path and name are consistent between the typed columns and the JSON blob.
    """
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")

    # Fetch a single endpoint directly from the DB (bypasses ORM identity map)
    ep_result = await db.execute(
        select(Endpoint)
        .where(Endpoint.suite_id == suite.id)
        .limit(1)
    )
    db_ep = ep_result.scalar_one()

    # Deserialise the JSONB blob back into a ParsedEndpoint
    parsed = ParsedEndpoint.model_validate(db_ep.endpoint_schema)

    assert parsed.method.value == db_ep.method, (
        f"Method mismatch: schema has {parsed.method.value!r}, "
        f"column has {db_ep.method!r}"
    )
    assert parsed.path == db_ep.path, (
        f"Path mismatch: schema has {parsed.path!r}, column has {db_ep.path!r}"
    )
    assert parsed.name == db_ep.name, (
        f"Name mismatch: schema has {parsed.name!r}, column has {db_ep.name!r}"
    )


# ---------------------------------------------------------------------------
# Test 9 — cURL import auto-creates an Environment
# ---------------------------------------------------------------------------


async def test_import_from_curl_auto_creates_environment_with_auth(
    db: AsyncSession,
) -> None:
    """A cURL import with an Authorization header creates a matching,
    complete Environment and links it to the suite."""
    curl_text = (
        "curl https://api.example.com/users "
        "-H 'Authorization: Bearer secret-token-123' "
        "-H 'X-Client: test'"
    )

    suite = await import_from_curl(db, DEFAULT_WORKSPACE_ID, curl_text)

    assert suite.environment_id is not None

    env_result = await db.execute(
        select(Environment).where(Environment.id == suite.environment_id)
    )
    env = env_result.scalar_one()
    assert env.base_url == "https://api.example.com"
    assert env.auth_type == "bearer"
    assert env.auth_config == {"token": "secret-token-123"}
    assert env.default_headers == {"X-Client": "test"}


async def test_import_from_curl_without_auth_creates_incomplete_environment(
    db: AsyncSession,
) -> None:
    """No Authorization header at all -> Environment is still created, with
    auth_type 'none' (surfaced to the frontend as EnvironmentOut.is_incomplete)."""
    suite = await import_from_curl(db, DEFAULT_WORKSPACE_ID, "curl https://api.example.com/users")

    assert suite.environment_id is not None
    env_result = await db.execute(
        select(Environment).where(Environment.id == suite.environment_id)
    )
    env = env_result.scalar_one()
    assert env.auth_type == "none"
    assert env.auth_config == {}


async def test_import_from_curl_reuses_environment_with_matching_base_url(
    db: AsyncSession,
) -> None:
    """Importing a second cURL command against the same base URL reuses the
    existing Environment rather than creating a duplicate."""
    first = await import_from_curl(
        db, DEFAULT_WORKSPACE_ID, "curl https://api.example.com/users"
    )
    second = await import_from_curl(
        db, DEFAULT_WORKSPACE_ID, "curl https://api.example.com/orders"
    )

    assert first.environment_id is not None
    assert first.environment_id == second.environment_id

    count_result = await db.execute(
        select(func.count(Environment.id)).where(
            Environment.workspace_id == DEFAULT_WORKSPACE_ID,
            Environment.base_url == "https://api.example.com",
        )
    )
    assert count_result.scalar_one() == 1
