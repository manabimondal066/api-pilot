"""Tests for the ask_user chat tool (Phase C) — registration, shape, and
input validation. No DB needed: ask_user never touches persistence.
"""

from __future__ import annotations

import pytest

from app.ai.tools.chat_tools import MUTATING_TOOLS, TOOL_IMPLS, TOOL_SPECS, ToolError, ask_user


def test_ask_user_registered_in_tool_impls():
    assert TOOL_IMPLS["ask_user"] is ask_user


def test_ask_user_not_a_mutating_tool():
    assert "ask_user" not in MUTATING_TOOLS


def test_ask_user_has_a_tool_spec():
    spec = next(s for s in TOOL_SPECS if s["function"]["name"] == "ask_user")
    props = spec["function"]["parameters"]["properties"]
    assert "question" in props
    assert "options" in props
    assert "allow_free_text" in props


async def test_ask_user_returns_expected_shape():
    result = await ask_user(
        ctx=None,
        question="Which field holds the user id?",
        options=["id", "userId", "user_id"],
        allow_free_text=True,
    )
    assert result == {
        "question": "Which field holds the user id?",
        "options": ["id", "userId", "user_id"],
        "allow_free_text": True,
    }


async def test_ask_user_defaults_allow_free_text_true():
    result = await ask_user(ctx=None, question="Pick one", options=["a", "b"])
    assert result["allow_free_text"] is True


@pytest.mark.parametrize("options", [[], ["only-one"], ["a", "b", "c", "d", "e"]])
async def test_ask_user_rejects_option_count_outside_2_to_4(options):
    with pytest.raises(ToolError):
        await ask_user(ctx=None, question="Pick one", options=options)
