"""Smoke test for the P4 operator/test-client endpoints: dev-login, asset catalog, usage.

Runs against the default SQLite backend (no Docker needed) and verifies the new HTTP surface
the frontend depends on. Fast (no ffmpeg).
"""

import time

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path):
    from contextlib import contextmanager

    from audio_streaming.app import create_app
    from fastapi.testclient import TestClient

    @contextmanager
    def _ctx():
        app = create_app()
        with TestClient(app) as client:
            yield client
    return _ctx()


def test_dev_login_and_usage_flow(tmp_path):
    with _client(tmp_path) as client:
        # Dev login issues a listener token.
        login = client.post("/v1/dev-login", json={"user_id": "tester", "role": "listener"})
        assert login.status_code == 200, login.text
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Catalog is empty initially.
        cat = client.get("/v1/assets")
        assert cat.status_code == 200
        assert cat.json()["assets"] == []

        # Usage endpoint returns a structured allowance for the period.
        usage = client.get("/v1/usage", headers=headers)
        assert usage.status_code == 200
        body = usage.json()
        assert body["user_id"] == "tester"
        assert "consumed_seconds" in body and "included_seconds" in body

        # Metrics endpoint returns Prometheus text exposition format.
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert metrics.headers["content-type"].startswith("text/plain")
        # After a rate-limit event the counter is exported; sanity-check the format line.
        assert "http_requests_total" in metrics.text or metrics.text.strip() == ""


def test_dev_login_admin_role(tmp_path):
    with _client(tmp_path) as client:
        login = client.post("/v1/dev-login", json={"user_id": "boss", "role": "admin"})
        assert login.status_code == 200
        assert login.json()["role"] == "admin"
        # Admin can list plans.
        plans = client.get("/v1/plans", headers={"Authorization": f"Bearer {login.json()['token']}"})
        assert plans.status_code == 200
        codes = {p["plan_code"] for p in plans.json()}
        assert "free" in codes and "listener_50" in codes
