"""Auth gate tests — API-key protection on the public job endpoints.

These run WITHOUT Redis/Docling: the auth dependency short-circuits before any
handler body, and `jobs.fetch_job` returns None when a job is absent, so a GET
on a random id naturally yields 404 once auth passes.

Run:  cd extractor-app && .venv/bin/python -m pytest test_auth.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Minimal valid multipart so body validation passes and the ONLY thing that can
# reject the request is the auth gate (not a 400/422 about a missing file).
DUMMY_FILE = {
    "file": (
        "naskah.docx",
        b"PK\x03\x04 dummy docx bytes",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
}
GOOD_KEY = "secret-test-key"


@pytest.fixture
def client(monkeypatch):
    # Enforce auth: dependency reads API_KEY at request time, so setting it here is enough.
    monkeypatch.setenv("API_KEY", GOOD_KEY)
    import main
    return TestClient(main.app)


def test_post_jobs_rejects_missing_key(client):
    r = client.post("/jobs", files=DUMMY_FILE)
    assert r.status_code == 401


def test_post_jobs_rejects_wrong_key(client):
    r = client.post("/jobs", files=DUMMY_FILE, headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_get_job_rejects_missing_key(client):
    r = client.get("/jobs/does-not-exist")
    assert r.status_code == 401


def test_get_job_accepts_correct_key(client):
    # Correct key → auth passes → handler runs → fetch_job(None) → 404 (not 401).
    r = client.get("/jobs/does-not-exist", headers={"X-API-Key": GOOD_KEY})
    assert r.status_code == 404


def test_health_stays_open_without_key(client):
    # Health must NOT require auth — RunPod/Cloudflare healthchecks hit it unauthenticated.
    r = client.get("/health")
    assert r.status_code != 401


def test_auth_disabled_when_no_key_configured(monkeypatch):
    # Intentional fail-open: unset API_KEY → gate is open (local dev / demo UI).
    monkeypatch.delenv("API_KEY", raising=False)
    import main
    c = TestClient(main.app)
    r = c.get("/jobs/does-not-exist")  # no key sent, yet not blocked
    assert r.status_code == 404
