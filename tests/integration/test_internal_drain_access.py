from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import shutdown as shutdown_state
from app.core.shutdown import DRAIN_DEADLINE_HEADER
from app.modules.health.api import router as health_router

pytestmark = pytest.mark.integration

_REMOTE_PEER = ("203.0.113.24", 50000)
_LOOPBACK_PEER = ("127.0.0.1", 50000)
_SPOOFED_LOOPBACK_HEADERS = {"X-Forwarded-For": "127.0.0.1"}


def _trust_every_forwarding_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")


def _client(app: FastAPI, peer: tuple[str, int]) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=peer),
        base_url="http://lb.example",
    )


@pytest.mark.asyncio
async def test_drain_start_rejects_spoofed_loopback_from_remote_peer(app_instance, monkeypatch):
    _trust_every_forwarding_peer(monkeypatch)

    async with _client(app_instance, _REMOTE_PEER) as client:
        response = await client.post(
            "/internal/drain/start",
            headers={**_SPOOFED_LOOPBACK_HEADERS, DRAIN_DEADLINE_HEADER: "1.0"},
        )

    assert response.status_code == 403
    assert shutdown_state.is_draining() is False
    assert shutdown_state.is_shutdown_committed() is False


@pytest.mark.asyncio
async def test_drain_stop_and_status_reject_spoofed_loopback_from_remote_peer(app_instance, monkeypatch):
    _trust_every_forwarding_peer(monkeypatch)

    async with _client(app_instance, _REMOTE_PEER) as client:
        stop_response = await client.post("/internal/drain/stop", headers=_SPOOFED_LOOPBACK_HEADERS)
        status_response = await client.get("/internal/drain/status", headers=_SPOOFED_LOOPBACK_HEADERS)

    assert (stop_response.status_code, status_response.status_code) == (403, 403)


@pytest.mark.asyncio
async def test_drain_status_allows_loopback_transport_peer(app_instance, monkeypatch):
    _trust_every_forwarding_peer(monkeypatch)

    async with _client(app_instance, _LOOPBACK_PEER) as client:
        response = await client.get(
            "/internal/drain/status",
            headers={"X-Forwarded-For": "203.0.113.24"},
        )

    assert response.status_code == 200
    assert response.json()["checks"]["draining"] == "false"


@pytest.mark.asyncio
async def test_drain_control_fails_closed_without_raw_peer_capture():
    app = FastAPI()
    app.include_router(health_router)

    async with _client(app, _LOOPBACK_PEER) as client:
        response = await client.get("/internal/drain/status")

    assert response.status_code == 403
