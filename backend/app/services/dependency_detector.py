"""Stage 1 dependency detector — heuristic, pure Python, no AI, no DB
(PRD §12, Implementation Plan Module 5, Sprint 4).

Public API
----------
DetectableTest
    Minimal, ORM-independent view of a test used as detector input.
DetectedEdge
    One inferred edge: *test_id* depends on *depends_on_test_id*.
DependencyCycleError
    Raised by detect() if the inferred edges form a cycle.
detect(tests) -> list[DetectedEdge]
    Run both heuristics and return the deduplicated edge list.

Heuristics
----------
1. Variable reference matching — a test's extraction (e.g. name="userId")
   is considered "consumed" by any other test whose path, headers, query
   params, or body contains a ``{{userId}}`` placeholder.
2. HTTP method/path semantics — a POST on a collection path (e.g. `/users`)
   is treated as a resource-creating call; any GET/PUT/PATCH/DELETE on a
   path nested under it (e.g. `/users/{id}`) is assumed to depend on it,
   even without an explicit variable reference (covers cases where the
   AI generated a literal example ID instead of a `{{var}}` placeholder).

Kept independent of SQLAlchemy models so it is trivially unit-testable
with plain fixtures (see tests/test_dependency_detector.py) and reusable
outside a request/DB context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services import DependencyCycleError

def _variable_pattern(name: str) -> re.Pattern[str]:
    return re.compile(r"\{\{\s*" + re.escape(name) + r"\s*\}\}")

_CREATE_METHODS = {"POST"}
_DEPENDENT_METHODS = {"GET", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class DetectableTest:
    """ORM-independent view of a Test, used as detector input."""

    id: str
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, Any] = field(default_factory=dict)
    body: Any = None
    extractions: list[dict[str, str]] = field(default_factory=list)  # [{"name": "userId", ...}]


@dataclass(frozen=True)
class DetectedEdge:
    """test_id depends on depends_on_test_id."""

    test_id: str
    depends_on_test_id: str
    reason: str  # 'variable_reference' | 'resource_path_semantics'


# ---------------------------------------------------------------------------
# Heuristic 1: variable reference matching
# ---------------------------------------------------------------------------


def _contains_variable_reference(value: Any, pattern: re.Pattern[str]) -> bool:
    """Recursively search path/headers/query_params/body for a {{name}} ref."""
    if isinstance(value, str):
        return bool(pattern.search(value))
    if isinstance(value, dict):
        return any(_contains_variable_reference(v, pattern) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_variable_reference(v, pattern) for v in value)
    return False


def _references_variable(test: DetectableTest, name: str) -> bool:
    pattern = _variable_pattern(name)
    return (
        _contains_variable_reference(test.path, pattern)
        or _contains_variable_reference(test.headers, pattern)
        or _contains_variable_reference(test.query_params, pattern)
        or _contains_variable_reference(test.body, pattern)
    )


def _detect_variable_reference_edges(tests: list[DetectableTest]) -> list[DetectedEdge]:
    edges: list[DetectedEdge] = []
    for source_test in tests:
        for extraction in source_test.extractions:
            name = extraction.get("name")
            if not name:
                continue
            for consumer in tests:
                if consumer.id == source_test.id:
                    continue
                if _references_variable(consumer, name):
                    edges.append(
                        DetectedEdge(
                            test_id=consumer.id,
                            depends_on_test_id=source_test.id,
                            reason="variable_reference",
                        )
                    )
    return edges


# ---------------------------------------------------------------------------
# Heuristic 2: HTTP method / path semantics
# ---------------------------------------------------------------------------


def _normalize_path(path: str) -> str:
    return path.strip("/")


def _is_nested_under(child_path: str, parent_path: str) -> bool:
    """True if child_path is parent_path plus at least one more segment.

    e.g. parent="/users", child="/users/{id}" -> True
         parent="/users", child="/users"      -> False (same resource, not nested)
         parent="/users", child="/orders"     -> False
    """
    parent = _normalize_path(parent_path)
    child = _normalize_path(child_path)
    if not parent or parent == child:
        return False
    return child.startswith(parent + "/")


def _detect_resource_path_edges(tests: list[DetectableTest]) -> list[DetectedEdge]:
    edges: list[DetectedEdge] = []
    creators = [t for t in tests if t.method.upper() in _CREATE_METHODS]
    for creator in creators:
        for candidate in tests:
            if candidate.id == creator.id:
                continue
            if candidate.method.upper() not in _DEPENDENT_METHODS:
                continue
            if _is_nested_under(candidate.path, creator.path):
                edges.append(
                    DetectedEdge(
                        test_id=candidate.id,
                        depends_on_test_id=creator.id,
                        reason="resource_path_semantics",
                    )
                )
    return edges


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


def _build_graph(edges: list[DetectedEdge]) -> dict[str, set[str]]:
    """test_id -> set of test_ids it depends on."""
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(edge.test_id, set()).add(edge.depends_on_test_id)
        graph.setdefault(edge.depends_on_test_id, set())
    return graph


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """DFS-based cycle detection. Returns the cycle (node ids) if found."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in graph}
    path_stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GRAY
        path_stack.append(node)
        for neighbor in graph.get(node, ()):
            if color.get(neighbor, WHITE) == GRAY:
                cycle_start = path_stack.index(neighbor)
                return path_stack[cycle_start:] + [neighbor]
            if color.get(neighbor, WHITE) == WHITE:
                found = visit(neighbor)
                if found:
                    return found
        path_stack.pop()
        color[node] = BLACK
        return None

    for node in graph:
        if color[node] == WHITE:
            cycle = visit(node)
            if cycle:
                return cycle
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def detect(tests: list[DetectableTest]) -> list[DetectedEdge]:
    """Run all Stage 1 heuristics and return the deduplicated edge list.

    Raises DependencyCycleError if the resulting edges form a cycle —
    the caller must not silently pick a subset to break it.
    """
    edges = _detect_variable_reference_edges(tests) + _detect_resource_path_edges(tests)

    deduped: dict[tuple[str, str], DetectedEdge] = {}
    for edge in edges:
        key = (edge.test_id, edge.depends_on_test_id)
        if key not in deduped:
            deduped[key] = edge
    unique_edges = list(deduped.values())

    graph = _build_graph(unique_edges)
    cycle = _find_cycle(graph)
    if cycle:
        raise DependencyCycleError(cycle)

    return unique_edges
