"""Callback postback tests — fire-and-forget POST of the job result to the FE.

These run WITHOUT network: `httpx.post` is monkeypatched. They pin the contract:
payload + header shape, the fire-and-forget guarantee (HTTP errors are swallowed,
never re-raised), and the "disabled when no URL" behaviour.

Run:  cd extractor-app && .venv/bin/python -m pytest test_callback.py -v
"""
from __future__ import annotations

import httpx

import callback

PAYLOAD = {
    "job_id": "749d223a-2c8b-45a1-8eb4-b40a62f4d917",
    "status": "finished",
    "original_filename": "SURAT TUGAS.pdf",
    "result": {"nomor_naskah": "000.5.6.2/X/2025"},
    "error": None,
    "completed_at": "2026-05-31T01:15:35.138523+00:00",
}


class _Resp:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


def test_posts_full_payload_with_token(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return _Resp(200)

    monkeypatch.setenv("CALLBACK_URL", "https://fe.example/api/callback/ai")
    monkeypatch.setenv("CALLBACK_TOKEN", "secret-123")
    monkeypatch.setattr(httpx, "post", fake_post)

    callback.post_result(PAYLOAD)

    assert captured["url"] == "https://fe.example/api/callback/ai"
    assert captured["json"] == PAYLOAD  # full result inline, mirrors GET /jobs/{id}
    assert captured["headers"]["X-Callback-Token"] == "secret-123"


def test_no_token_header_when_unset(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["headers"] = kwargs.get("headers") or {}
        return _Resp(200)

    monkeypatch.setenv("CALLBACK_URL", "https://fe.example/api/callback/ai")
    monkeypatch.delenv("CALLBACK_TOKEN", raising=False)
    monkeypatch.setattr(httpx, "post", fake_post)

    callback.post_result(PAYLOAD)

    assert "X-Callback-Token" not in captured["headers"]


def test_http_failure_is_swallowed(monkeypatch):
    # The whole point of fire-and-forget: a dead FE endpoint must NOT break the job.
    def boom(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setenv("CALLBACK_URL", "https://fe.example/api/callback/ai")
    monkeypatch.setattr(httpx, "post", boom)

    # Must return normally (no exception propagates to the worker).
    callback.post_result({**PAYLOAD, "status": "failed", "result": None, "error": "boom"})


def test_non_2xx_is_swallowed(monkeypatch):
    # FE endpoint still in-progress → 404/5xx. Logged, not raised.
    monkeypatch.setenv("CALLBACK_URL", "https://fe.example/api/callback/ai")
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp(503))

    callback.post_result(PAYLOAD)  # no exception


def test_disabled_when_no_url(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        return _Resp(200)

    monkeypatch.setenv("CALLBACK_URL", "")
    monkeypatch.setattr(httpx, "post", fake_post)

    callback.post_result(PAYLOAD)

    assert calls["n"] == 0  # empty URL = callback disabled, no HTTP call at all
