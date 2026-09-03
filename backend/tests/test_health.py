"""
Smoke test for the /api/healthz endpoint.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/api/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api-pilot-backend"
    assert body["version"] == "0.0.1"
    assert "env" in body
