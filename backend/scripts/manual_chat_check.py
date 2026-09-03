"""One-off manual validation script for Sprint 5 (chat assistant).

Imports a fixture suite, inserts a bare test row, sends one real message
through the configured LLM provider (per backend/.env — currently gemini),
and prints exactly what happened. Not part of the automated test suite;
run manually with:

    .venv/Scripts/python scripts/manual_chat_check.py
"""

import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.test import Test
from app.services import chat_service
from app.services.import_service import import_from_upload


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async with factory() as db:
        content = (Path(__file__).parent.parent / "tests" / "fixtures" / "petstore_v3.json").read_bytes()
        suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
        login_endpoint = next(ep for ep in suite.endpoints if ep.path == "/user/login")

        test = Test(
            suite_id=suite.id,
            endpoint_id=login_endpoint.id,
            name="login test",
            category="POSITIVE",
            method=login_endpoint.method,
            path=login_endpoint.path,
            validations=[],
        )
        db.add(test)
        await db.commit()
        print(f"Created suite={suite.id} test={test.id} ({test.method} {test.path})")

        result = await chat_service.send_message(
            db=db,
            workspace_id=DEFAULT_WORKSPACE_ID,
            suite_id=suite.id,
            user_message="add a status code check to my login test",
        )

        print("\n--- Agent reply ---")
        print(result.reply)
        print("\n--- Tool calls ---")
        for tc in result.tool_calls:
            print(f"  {tc.tool}({tc.arguments}) -> error={tc.error!r} result={tc.result[:200]!r}")
        print("\n--- Changes (mutating, no error) ---")
        for tc in result.changes:
            print(f"  {tc.tool}({tc.arguments})")

        await db.refresh(test)
        print("\n--- Persisted validations on the test row ---")
        print(test.validations)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
