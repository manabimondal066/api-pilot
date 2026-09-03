"""End-to-end smoke test: parse a real Swagger endpoint, generate tests with NIM.

Usage:
    cd backend
    .\\.venv\\Scripts\\Activate.ps1
    $env:NVIDIA_API_KEY = "nvapi-..."
    python scripts/smoke_test_generate.py
"""
import asyncio
import os
from pathlib import Path

from app.ai.service import AIOrchestrationService
from app.parsers.swagger_parser import parse_swagger


async def main():
    fixture = Path(__file__).parent.parent / "tests" / "fixtures" / "petstore_v3.json"
    content = fixture.read_bytes()
    spec = await parse_swagger(content, raw_spec_ref="smoke/petstore.json")

    # Pick an interesting endpoint — POST /pet is a good test (has body schema)
    target = next(
        (e for e in spec.endpoints if e.method.value == "POST" and e.path == "/pet"),
        None,
    )
    if target is None:
        target = spec.endpoints[0]
        print(f"WARNING: POST /pet not found, falling back to {target.method.value} {target.path}")

    print(f"Generating tests for: {target.method.value} {target.path}")
    print(f"  Body schema present: {target.body_schema is not None}")
    print(f"  Response status codes: {list(target.response_schemas.keys())}")
    print()

    service = AIOrchestrationService()
    tests = await service.generate_tests(target)

    print(f"Generated {len(tests)} tests:\n")
    for i, t in enumerate(tests, 1):
        print(f"  [{i}] {t.category.value}: {t.name}")
        print(f"      method={t.method.value} path={t.path}")
        print(f"      validations={len(t.validations)} confidence={t.confidence:.2f}")
        for v in t.validations[:3]:
            target_str = f" target={v.target}" if v.target else ""
            expected_str = f" expected={v.expected!r}" if v.expected is not None else ""
            print(f"        - {v.type.value}: {v.description}{target_str}{expected_str}")
        if len(t.validations) > 3:
            print(f"        ... and {len(t.validations) - 3} more")
        print()


if __name__ == "__main__":
    if not os.environ.get("NVIDIA_API_KEY"):
        print("ERROR: NVIDIA_API_KEY not set.")
        exit(1)
    asyncio.run(main())
