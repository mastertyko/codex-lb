from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.core.auth.dashboard_mode import DashboardAuthMode, get_dashboard_request_auth

pytestmark = pytest.mark.unit


def test_trusted_header_auth_fails_closed_without_raw_peer_capture(monkeypatch) -> None:
    settings = SimpleNamespace(
        dashboard_auth_mode=DashboardAuthMode.TRUSTED_HEADER,
        firewall_trust_proxy_headers=True,
        firewall_trusted_proxy_cidrs=["10.0.0.0/8"],
        dashboard_auth_proxy_header="Remote-User",
    )
    monkeypatch.setattr("app.core.config.settings.get_settings", lambda: settings)
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/settings",
            "raw_path": b"/api/settings",
            "query_string": b"",
            "headers": [(b"remote-user", b"attacker@example.com")],
            "client": ("10.0.0.2", 50000),
        }
    )

    assert get_dashboard_request_auth(request) is None
