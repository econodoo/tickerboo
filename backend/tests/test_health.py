"""Basic smoke test for the health endpoint."""
import pytest
from fastapi.testclient import TestClient

from tickerboo.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "env" in data


def test_root_redirects():
    r = client.get("/")
    assert r.status_code == 200
    assert "TickerBoo" in r.json()["message"]
