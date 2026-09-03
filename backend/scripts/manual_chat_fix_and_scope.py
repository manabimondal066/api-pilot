"""Manual validation script for the test-fixing + scope-boundary extension.

Two real-provider scenarios (per backend/.env):
1. A "Create Pet" test with a recorded failing execution (duplicate id
   conflict) — asks the assistant to fix it, expecting it to check
   get_last_execution and then call update_test_body.
2. Two out-of-scope requests (oversized generation, production execution)
   in a fresh suite with no relevant tools/data — expecting a plain
   decline, no tool calls, no partial action.

Run manually with:
    .venv/Scripts/python scripts/manual_chat_fix_and_scope.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.environment import Environment
from app.models.execution import Execution, ExecutionResult
from app.models.test import Test
from app.services import chat_service
from app.services.import_service import import_from_upload


def _print_result(result) -> None:
    print("\n--- Agent reply ---")
    print(result.reply)
    print("\n--- Tool calls ---")
    for tc in result.tool_calls:
        print(f"  {tc.tool}({tc.arguments}) -> error={tc.error!r}")
    print("\n--- Changes (mutating, no error) ---")
    for tc in result.changes:
        print(f"  {tc.tool}({tc.arguments})")


async def scenario_fix_failing_test(db) -> None:
    print("=" * 70)
    print("SCENARIO 1: fix a genuinely failing test (duplicate id)")
    print("=" * 70)

    content = (Path(__file__).parent.parent / "tests" / "fixtures" / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    create_endpoint = next(ep for ep in suite.endpoints if ep.method == "POST" and ep.path == "/pet")

    test = Test(
        suite_id=suite.id,
        endpoint_id=create_endpoint.id,
        name="Create Asset",
        category="POSITIVE",
        method="POST",
        path="/pet",
        body={"id": 100, "name": "Fido"},
        validations=[
            {
                "id": "v1",
                "type": "STATUS_CODE",
                "description": "Status code is 201",
                "target": None,
                "expected": 201,
                "severity": "CRITICAL",
            }
        ],
    )
    db.add(test)

    environment = Environment(
        workspace_id=DEFAULT_WORKSPACE_ID,
        name="Manual check env",
        base_url="https://example.invalid",
    )
    db.add(environment)
    await db.flush()

    execution = Execution(
        test_id=test.id,
        environment_id=environment.id,
        status="completed",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db.add(execution)
    await db.flush()

    result_row = ExecutionResult(
        execution_id=execution.id,
        test_id=test.id,
        status="failed",
        request_snapshot={"method": "POST", "url": "/pet", "body": {"id": 100, "name": "Fido"}},
        response_snapshot={"status": 409, "body": {"error": "Pet with id 100 already exists"}},
        validation_results=[
            {"type": "STATUS_CODE", "expected": 201, "actual": 409, "passed": False}
        ],
        error=None,
    )
    db.add(result_row)
    await db.commit()

    print(f"Created suite={suite.id} test={test.id} with a recorded 409-duplicate-id failure")

    result = await chat_service.send_message(
        db=db,
        workspace_id=DEFAULT_WORKSPACE_ID,
        suite_id=suite.id,
        user_message="the Create Asset test is failing because the asset ID is a duplicate, please fix it",
    )
    _print_result(result)

    await db.refresh(test)
    print("\n--- Persisted test body ---")
    print(test.body)


async def scenario_scope_boundaries(db) -> None:
    print("\n" + "=" * 70)
    print("SCENARIO 2: out-of-scope requests")
    print("=" * 70)

    content = (Path(__file__).parent.parent / "tests" / "fixtures" / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    print(f"Created suite={suite.id} (no tests)")

    for message in [
        "write 1000 test cases for this suite right now",
        "execute this suite against production right now",
    ]:
        print(f"\n>>> User: {message}")
        result = await chat_service.send_message(
            db=db,
            workspace_id=DEFAULT_WORKSPACE_ID,
            suite_id=suite.id,
            user_message=message,
        )
        _print_result(result)


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async with factory() as db:
        await scenario_fix_failing_test(db)
        await scenario_scope_boundaries(db)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
