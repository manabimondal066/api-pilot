"""Unit tests for the Stage 1 heuristic dependency detector — pure Python,
no DB (app/services/dependency_detector.py).
"""

from __future__ import annotations

import pytest

from app.services import DependencyCycleError
from app.services.dependency_detector import DetectableTest, DetectedEdge, detect


def _edge_set(edges: list[DetectedEdge]) -> set[tuple[str, str]]:
    return {(e.test_id, e.depends_on_test_id) for e in edges}


def test_simple_create_then_get_chain_detected_via_variable_reference() -> None:
    create_user = DetectableTest(
        id="create-user",
        method="POST",
        path="/users",
        body={"name": "Alice"},
        extractions=[{"name": "userId", "source": "$.id"}],
    )
    get_user = DetectableTest(
        id="get-user",
        method="GET",
        path="/users/{{userId}}",
    )

    edges = detect([create_user, get_user])

    assert ("get-user", "create-user") in _edge_set(edges)
    assert all(e.reason == "variable_reference" or e.reason == "resource_path_semantics" for e in edges)


def test_simple_create_then_get_chain_detected_via_resource_path_semantics() -> None:
    """Even without an explicit {{var}}, a GET nested under a POST's path
    should be flagged as a likely dependency (literal example IDs)."""
    create_user = DetectableTest(id="create-user", method="POST", path="/users")
    get_user = DetectableTest(id="get-user", method="GET", path="/users/42")

    edges = detect([create_user, get_user])

    assert ("get-user", "create-user") in _edge_set(edges)


def test_full_crud_chain_detected() -> None:
    create_user = DetectableTest(
        id="create",
        method="POST",
        path="/users",
        extractions=[{"name": "userId", "source": "$.id"}],
    )
    get_user = DetectableTest(id="get", method="GET", path="/users/{{userId}}")
    update_user = DetectableTest(
        id="update", method="PUT", path="/users/{{userId}}", body={"name": "Bob"}
    )
    delete_user = DetectableTest(id="delete", method="DELETE", path="/users/{{userId}}")

    edges = _edge_set(detect([create_user, get_user, update_user, delete_user]))

    assert ("get", "create") in edges
    assert ("update", "create") in edges
    assert ("delete", "create") in edges


def test_no_false_positive_for_unrelated_tests() -> None:
    create_user = DetectableTest(
        id="create-user",
        method="POST",
        path="/users",
        extractions=[{"name": "userId", "source": "$.id"}],
    )
    list_orders = DetectableTest(id="list-orders", method="GET", path="/orders")

    edges = detect([create_user, list_orders])

    assert edges == []


def test_no_false_positive_for_same_resource_collection_get() -> None:
    """A GET on the exact same collection path as a POST (not nested)
    should not be treated as a dependent."""
    create_user = DetectableTest(id="create-user", method="POST", path="/users")
    list_users = DetectableTest(id="list-users", method="GET", path="/users")

    edges = detect([create_user, list_users])

    assert edges == []


def test_cycle_detected_and_rejected_with_clear_error() -> None:
    # a extracts itemId and references b's extraction (otherId);
    # b extracts otherId and references a's extraction (itemId) -> a cycle.
    test_a = DetectableTest(
        id="a",
        method="PUT",
        path="/items/{{otherId}}",
        extractions=[{"name": "itemId", "source": "$.id"}],
    )
    test_b = DetectableTest(
        id="b",
        method="PUT",
        path="/items/{{itemId}}",
        extractions=[{"name": "otherId", "source": "$.id"}],
    )

    with pytest.raises(DependencyCycleError) as excinfo:
        detect([test_a, test_b])

    assert set(excinfo.value.test_ids) == {"a", "b"}


def test_multiple_variable_references_produce_multiple_edges() -> None:
    login = DetectableTest(
        id="login",
        method="POST",
        path="/login",
        extractions=[{"name": "token", "source": "$.token"}],
    )
    create_order = DetectableTest(
        id="create-order",
        method="POST",
        path="/orders",
        headers={"Authorization": "Bearer {{token}}"},
    )
    get_order = DetectableTest(
        id="get-order",
        method="GET",
        path="/orders/{{orderId}}",
        headers={"Authorization": "Bearer {{token}}"},
    )

    edges = _edge_set(detect([login, create_order, get_order]))

    assert ("create-order", "login") in edges
    assert ("get-order", "login") in edges
