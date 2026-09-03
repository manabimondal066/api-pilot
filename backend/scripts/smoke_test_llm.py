"""Manual smoke test for the configured LLM provider.

Usage (NVIDIA NIM, default):
    cd backend
    .\\.venv\\Scripts\\Activate.ps1
    $env:NVIDIA_API_KEY = "nvapi-..."
    python scripts/smoke_test_llm.py

Usage (Groq):
    $env:LLM_PROVIDER = "groq"
    $env:GROQ_API_KEY = "gsk_..."
    python scripts/smoke_test_llm.py
"""
import asyncio
import os

from pydantic import BaseModel

from app.ai.providers.base import Message
from app.ai.providers.factory import get_llm_provider, reset_provider_cache


class Greeting(BaseModel):
    language: str
    text: str


async def main():
    reset_provider_cache()
    provider = get_llm_provider()
    info = provider.get_model_info()
    print(f"Provider: {info.provider} | Model: {info.model}")

    print("\n[1/2] generate_structured...")
    result = await provider.generate_structured(
        prompt="Say hello in French. Respond as JSON with fields: language, text.",
        schema=Greeting,
        system="You return only valid JSON matching the requested schema.",
        max_tokens=200,
    )
    print(f"   Got: {result}")

    print("\n[2/2] chat (streaming)...")
    async for chunk in provider.chat(
        [Message(role="user", content="Count from 1 to 5, comma-separated.")],
        max_tokens=100,
    ):
        print(chunk, end="", flush=True)
    print("\n\nDone.")


if __name__ == "__main__":
    if not any(
        os.environ.get(k)
        for k in ("NVIDIA_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    ):
        print("ERROR: No API key set. Set one of NVIDIA_API_KEY, GROQ_API_KEY, etc.")
        exit(1)
    asyncio.run(main())
