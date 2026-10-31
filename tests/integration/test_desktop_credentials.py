from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi import Request, WebSocket
from fastapi.testclient import TestClient
from httpx2 import Headers
from starlette.responses import JSONResponse
from starlette.testclient import WebSocketDenialResponse

from app.core.auth import dependencies as auth_dependencies
from app.core.clients.proxy import _build_upstream_headers, _build_upstream_transcribe_headers
from app.core.clients.proxy_websocket import _build_upstream_live_websocket_headers, _build_upstream_websocket_headers
from app.core.exceptions import ProxyAuthError
from app.core.middleware import desktop_credentials as boundary
from app.core.utils.time import utcnow
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy import api as proxy_api
from app.modules.proxy.service import ProxyService

pytestmark = pytest.mark.integration

DESKTOP_VOICE_PREFIX = "/backend-api/codex/desktop-voice"

DUAL_HEADERS = {
    "Authorization": "Bearer caller-oauth-secret",
    "X-Codex-LB-Key": "gateway-secret",
    "ChatGPT-Account-Id": "caller-workspace",
    "X-OAI-Attestation": "caller-attestation",
    "Cookie": "private-cookie",
    "originator": "codex_cli_rs",
}

ACCEPTED_ATTESTATIONS = [
    pytest.param("caller-attestation", id="opaque"),
    pytest.param('{"v":1,"s":0,"t":"v1.opaque-client-payload"}', id="native-success"),
    pytest.param('{"v":1,"s":0,"t":""}', id="native-empty-token"),
    pytest.param('{"t":"opaque,token","s":0,"v":1}', id="native-reordered-opaque-token"),
    *(pytest.param(f'{{"v":1,"s":{status}}}', id=f"native-failure-{status}") for status in range(1, 5)),
]


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize(
    "reason,header,values",
    [
        pytest.param("gateway_header", "X-Codex-LB-Key", [""], id="empty-gateway"),
        pytest.param("gateway_header", "X-Codex-LB-Key", ["gateway-secret", "duplicate"], id="duplicate-gateway"),
        pytest.param("gateway_header", "X-Codex-LB-Key", ["gateway,secret"], id="comma-gateway"),
        pytest.param("gateway_header", "X-Codex-LB-Key", ["gateway secret"], id="whitespace-gateway"),
        pytest.param("caller_header", "Authorization", [], id="missing-caller"),
        pytest.param("caller_header", "Authorization", [""], id="empty-caller"),
        pytest.param("caller_header", "Authorization", ["Bearer caller", "Bearer other"], id="duplicate-caller"),
        pytest.param("bearer_syntax", "Authorization", ["AgentAssertion private-assertion"], id="caller-scheme"),
        pytest.param("bearer_syntax", "Authorization", ["Bearer caller,other"], id="comma-bearer"),
        pytest.param("bearer_syntax", "Authorization", ["Bearer caller other"], id="whitespace-bearer"),
        pytest.param("account_context", "ChatGPT-Account-Id", ["first", "second"], id="duplicate-account"),
        pytest.param("account_context", "ChatGPT-Account-Id", [""], id="empty-account"),
        pytest.param("account_context", "ChatGPT-Account-Id", ["caller,workspace"], id="comma-account"),
        pytest.param("attestation_cardinality", "X-OAI-Attestation", ["first", "second"], id="duplicate-attestation"),
        pytest.param("attestation_empty", "X-OAI-Attestation", [""], id="empty-attestation"),
        pytest.param("attestation_whitespace", "X-OAI-Attestation", [" leading"], id="leading-attestation"),
        pytest.param("attestation_whitespace", "X-OAI-Attestation", ["trailing "], id="trailing-attestation"),
        pytest.param("attestation_size", "X-OAI-Attestation", ["a" * (16 * 1024 + 1)], id="oversize-attestation"),
        pytest.param("attestation_list", "X-OAI-Attestation", ["private,attestation"], id="list-attestation"),
        pytest.param("attestation_charset", "X-OAI-Attestation", ["private\x00attestation"], id="control-attestation"),
        pytest.param(
            "attestation_charset", "X-OAI-Attestation", ["private-\u00f1-attestation"], id="nonascii-attestation"
        ),
        pytest.param(
            "attestation_cardinality",
            "X-OAI-Attestation",
            ["a" * (16 * 1024 + 1), "second"],
            id="cardinality-before-size",
        ),
        pytest.param("attestation_size", "X-OAI-Attestation", ["a" * (16 * 1024) + ","], id="size-before-list"),
        pytest.param("attestation_list", "X-OAI-Attestation", ["private,\x00attestation"], id="list-before-charset"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1,"s":0}'], id="native-missing-token"),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['{"v":1,"s":1,"t":"private"}'], id="native-failure-token"
        ),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['{"v":1,"s":0,"t":"private","extra":1}'], id="native-extra-field"
        ),
        pytest.param(
            "attestation_list",
            "X-OAI-Attestation",
            ['{"v":1,"v":1,"s":0,"t":"private"}'],
            id="native-duplicate-version",
        ),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['{"v":1,"s":0,"s":0,"t":"private"}'], id="native-duplicate-status"
        ),
        pytest.param(
            "attestation_list",
            "X-OAI-Attestation",
            ['{"v":1,"s":0,"t":"private","t":"private"}'],
            id="native-duplicate-token",
        ),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['{"v":1,"s":1}{"v":1,"s":2}'], id="native-concatenated-objects"
        ),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['[{"v":1,"s":1},{"v":1,"s":2}]'], id="native-object-list"
        ),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1,"s":1},opaque'], id="native-ad-hoc-list"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":true,"s":1}'], id="native-boolean-version"),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['{"v":1,"s":false,"t":"private"}'], id="native-boolean-status"
        ),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":"1","s":1}'], id="native-string-version"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1.0,"s":1}'], id="native-float-version"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":2,"s":1}'], id="native-unsupported-version"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1,"s":"1"}'], id="native-string-status"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1,"s":1.0}'], id="native-float-status"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1,"s":-1}'], id="native-negative-status"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1,"s":5}'], id="native-unsupported-status"),
        pytest.param("attestation_list", "X-OAI-Attestation", ['{"v":1,"s":0,"t":null}'], id="native-null-token"),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['{"v":1,"s":0,"t":{"private":1}}'], id="native-object-token"
        ),
        pytest.param(
            "attestation_list", "X-OAI-Attestation", ['{"v":1,"s":0,"t":"private\x00token"}'], id="native-raw-control"
        ),
        pytest.param(
            "attestation_charset",
            "X-OAI-Attestation",
            ['{"v":1,"s":0,"t":"private-\u00f1-token"}'],
            id="native-nonascii-token",
        ),
        pytest.param("attestation_charset", "X-OAI-Attestation", ['{"v":1, "s":1}'], id="native-interior-whitespace"),
        pytest.param(
            "attestation_size",
            "X-OAI-Attestation",
            ['{"v":1,"s":0,"t":"' + "a" * (16 * 1024) + '"}'],
            id="native-size-before-shape",
        ),
        pytest.param(
            "attestation_list",
            "X-OAI-Attestation",
            ['{"v":1,"s":0,"t":' + "[" * 2000 + "0" + "]" * 2000 + "}"],
            id="native-excessive-depth",
        ),
        pytest.param("key_validation", "X-Codex-LB-Key", ["invalid-private-key"], id="invalid-gateway-key"),
    ],
)
def test_public_gateway_denials_emit_one_bounded_private_diagnostic(
    credential_app, caplog, transport, reason, header, values
):
    client, calls = credential_app
    caplog.set_level(logging.WARNING, logger=boundary.__name__)
    headers = Headers(
        [(name, value) for name, value in DUAL_HEADERS.items() if name != header]
        + [(header, value) for value in values],
        encoding="latin-1",
    )
    private_headers = [*headers.keys(), *headers.values()]
    lane = "ordinary"
    path = "/backend-api/codex/responses?private_query=secret"
    if transport == "http":
        response = client.post(path, headers=headers, content=b"private-request-body")
    else:
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(path, headers=headers):
                pytest.fail("invalid credentials must deny before an upstream connection")
        response = denied.value
    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "message": "Invalid Desktop gateway credentials",
            "type": "server_error",
            "code": "desktop_gateway_auth_invalid",
        }
    }
    assert calls == (["Bearer invalid-private-key"] if reason == "key_validation" else [])
    records = [record for record in caplog.records if record.name == boundary.__name__]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == f"Desktop gateway rejected reason={reason} transport={transport} lane={lane}"
    assert record.args == (reason, transport, lane)
    assert record.exc_info is None and record.exc_text is None and record.stack_info is None
    for private in (
        *private_headers,
        "raw secret detail must not escape",
        "rtc_private_call",
        "private_query",
        "private-request-body",
        path,
    ):
        if private:
            assert private not in repr(record.__dict__)


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("path,reason", [("/health/live", "route_support")])
def test_unsupported_gateway_route_denial_is_bounded(credential_app, caplog, transport, path, reason):
    client, calls = credential_app
    caplog.set_level(logging.WARNING, logger=boundary.__name__)
    headers = DUAL_HEADERS if reason == "route_support" else {"Authorization": "Bearer caller-oauth-secret"}
    if transport == "http":
        response = client.get(path, headers=headers)
    else:
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(path, headers=headers):
                pytest.fail("the rejected route must never establish a websocket")
        response = denied.value
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "desktop_gateway_auth_invalid"
    assert not calls
    records = [record for record in caplog.records if record.name == boundary.__name__]
    assert len(records) == 1
    assert records[0].args == (reason, transport, "ordinary" if reason == "route_support" else "voice")
    assert path not in repr(records[0].__dict__) and "caller-oauth-secret" not in repr(records[0].__dict__)
    assert records[0].exc_info is None


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("attestation", ACCEPTED_ATTESTATIONS)
def test_native_envelope_does_not_bypass_gateway_key_validation(credential_app, caplog, transport, attestation):
    client, calls = credential_app
    caplog.set_level(logging.WARNING, logger=boundary.__name__)
    headers = {**DUAL_HEADERS, "X-OAI-Attestation": attestation, "X-Codex-LB-Key": "invalid-private-key"}
    path = "/backend-api/codex/responses"
    if transport == "http":
        response = client.post(path, headers=headers, json={"model": "gpt-6.1-sol", "input": "private-input"})
    else:
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(path, headers=headers):
                pytest.fail("a native envelope must not authorize an invalid gateway key")
        response = denied.value
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "desktop_gateway_auth_invalid"
    assert calls == ["Bearer invalid-private-key"]
    records = [record for record in caplog.records if record.name == boundary.__name__]
    assert len(records) == 1 and records[0].args == ("key_validation", transport, "ordinary")
    for private in (attestation, "invalid-private-key", "raw secret detail must not escape"):
        assert private not in repr(records[0].__dict__)
    assert records[0].exc_info is None


@pytest.fixture
def credential_app(app_instance, monkeypatch):
    calls = []

    async def validate(authorization):
        calls.append(authorization)
        if authorization != "Bearer gateway-secret":
            raise ProxyAuthError("raw secret detail must not escape")
        return ApiKeyData(
            id="scoped-key",
            name="test",
            key_prefix="test",
            allowed_models=["gpt-6.1-sol"],
            enforced_model=None,
            enforced_reasoning_effort=None,
            enforced_service_tier=None,
            expires_at=None,
            is_active=True,
            created_at=utcnow(),
            last_used_at=None,
            assigned_account_ids=["owner"],
            account_assignment_scope_enabled=True,
        )

    monkeypatch.setattr(boundary, "validate_required_proxy_api_key_authorization", validate)

    @app_instance.get("/backend-api/codex/_credential_probe")
    async def http_probe(request: Request):
        inbound = dict(request.headers)
        return {
            "inbound": inbound,
            "upstream": _build_upstream_headers(inbound, "pooled-token", "pooled-workspace"),
            "has_voice_credentials": getattr(request.state, "desktop_voice_credentials", None) is not None,
        }

    @app_instance.websocket("/backend-api/codex/_credential_probe")
    async def ws_probe(websocket: WebSocket):
        await websocket.accept()
        inbound = dict(websocket.headers)
        await websocket.send_json(
            {
                "inbound": inbound,
                "upstream": _build_upstream_websocket_headers(inbound, "pooled-token", "pooled-workspace"),
            }
        )
        await websocket.close()

    # The real app ends with its dashboard catch-all; keep probes before it.
    app_instance.router.routes[:] = app_instance.router.routes[-2:] + app_instance.router.routes[:-2]
    return TestClient(app_instance, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)), calls


@pytest.mark.parametrize("transport", ["http", "websocket"])
def test_real_middleware_replaces_pool_credentials_without_touching_key_scope(credential_app, transport):
    client, calls = credential_app
    if transport == "http":
        response = client.get("/backend-api/codex/_credential_probe", headers=DUAL_HEADERS)
        assert response.status_code == 200
        result = response.json()
        assert result["has_voice_credentials"] is False
    else:
        with client.websocket_connect("/backend-api/codex/_credential_probe", headers=DUAL_HEADERS) as websocket:
            result = websocket.receive_json()
    assert calls == ["Bearer gateway-secret"]
    assert result["inbound"]["authorization"] == "Bearer gateway-secret"
    upstream = {k.lower(): v for k, v in result["upstream"].items()}
    assert upstream["authorization"] == "Bearer pooled-token"
    assert upstream["chatgpt-account-id"] == "pooled-workspace"
    for private in (
        "caller-oauth-secret",
        "caller-workspace",
        "caller-attestation",
        "gateway-secret",
        "private-cookie",
    ):
        assert private not in str(upstream)


@pytest.mark.parametrize(
    "attestation",
    [
        None,
        "a" * (16 * 1024),
        '{"v":1,"s":0,"t":"' + "a" * (16 * 1024 - len('{"v":1,"s":0,"t":""}')) + '"}',
        '{"v":99}',
    ],
)
def test_gateway_attestation_is_optional_and_bounded(credential_app, attestation):
    client, _calls = credential_app
    headers = {name: value for name, value in DUAL_HEADERS.items() if name != "X-OAI-Attestation"}
    if attestation is not None:
        headers["X-OAI-Attestation"] = attestation
    response = client.get("/backend-api/codex/_credential_probe", headers=headers)
    assert response.status_code == 200
    assert "x-oai-attestation" not in response.json()["inbound"]


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("Authorization", "Bearer caller")],
        [("X-Codex-LB-Key", "gateway-secret")],
        [("X-Codex-LB-Key", ""), ("Authorization", "Bearer caller")],
        [("X-Codex-LB-Key", "gateway-secret"), ("Authorization", "Basic caller")],
        [("X-Codex-LB-Key", "gateway-secret"), ("Authorization", "Bearer caller, Bearer other")],
        [("X-Codex-LB-Key", "gateway-secret"), ("x-codex-lb-key", "other"), ("Authorization", "Bearer caller")],
        [("X-Codex-LB-Key", "gateway-secret"), ("Authorization", "Bearer caller"), ("authorization", "Bearer other")],
        [
            ("X-Codex-LB-Key", "gateway-secret"),
            ("Authorization", "Bearer caller"),
            ("chatgpt-account-id", "a"),
            ("ChatGPT-Account-ID", "b"),
        ],
    ],
)
def test_retired_voice_denies_before_key_or_upstream(credential_app, transport, headers):
    client, calls = credential_app
    path = DESKTOP_VOICE_PREFIX + "/live/rtc_private_call?private_query=secret"
    if transport == "http":
        response = client.get(path, headers=headers)
    else:
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(path, headers=Headers(headers)):
                pytest.fail("invalid credentials must never establish a websocket")
        response = denied.value
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "desktop_voice_retired"
    assert not calls
    assert "rtc_private_call" not in response.text


def test_invalid_gateway_is_always_denied_even_with_optional_auth(credential_app):
    client, calls = credential_app
    headers = {**DUAL_HEADERS, "X-Codex-LB-Key": "invalid-key"}
    response = client.get("/backend-api/codex/_credential_probe", headers=headers)
    assert response.status_code == 401
    assert calls == ["Bearer invalid-key"]
    assert "raw secret" not in response.text


def test_normal_request_without_dual_header_is_unchanged(credential_app):
    client, calls = credential_app
    headers = {"Authorization": "Bearer legacy-key", "ChatGPT-Account-Id": "legacy-context"}
    response = client.get("/backend-api/codex/_credential_probe", headers=headers)
    assert response.status_code == 200
    assert response.json()["inbound"]["authorization"] == "Bearer legacy-key"
    assert response.json()["inbound"]["chatgpt-account-id"] == "legacy-context"
    assert not calls


@pytest.mark.parametrize("attestation", ACCEPTED_ATTESTATIONS)
def test_public_models_and_responses_keep_key_policy_when_ordinary_auth_disabled(
    credential_app, monkeypatch, caplog, attestation
):
    client, _calls = credential_app
    caplog.set_level(logging.WARNING, logger=boundary.__name__)

    async def settings():
        return SimpleNamespace(api_key_auth_enabled=False)

    monkeypatch.setattr(auth_dependencies, "get_settings_cache", lambda: SimpleNamespace(get=settings))
    observed = []
    forwarded = []

    async def catalog(api_key):
        assert isinstance(api_key, ApiKeyData)
        assert api_key.account_assignment_scope_enabled and api_key.assigned_account_ids == ["owner"]
        observed.append(api_key.allowed_models)
        return JSONResponse({"models": []})

    async def no_source(*args, **kwargs):
        return None, False

    async def no_source_denial(*args, **kwargs):
        return None

    async def stream(request, payload, context, api_key, **kwargs):
        assert isinstance(api_key, ApiKeyData)
        assert api_key.allowed_models == ["gpt-6.1-sol"]
        assert api_key.assigned_account_ids == ["owner"] and api_key.account_assignment_scope_enabled
        assert payload.model == "gpt-6.1-sol"
        headers = dict(request.headers)
        assert "x-oai-attestation" not in headers and "chatgpt-account-id" not in headers
        upstream = _build_upstream_headers(headers, "pooled-token", "pooled-workspace")
        for private in (attestation, "caller-oauth-secret", "caller-workspace", "gateway-secret", "private-cookie"):
            if private:
                assert private not in str(upstream)
        forwarded.append(api_key.id)
        return JSONResponse({"id": "resp_gateway_admitted"})

    monkeypatch.setattr(proxy_api, "_build_codex_models_response", catalog)
    monkeypatch.setattr(proxy_api, "_select_responses_model_source_with_continuity", no_source)
    monkeypatch.setattr(proxy_api, "_disabled_model_source_denial", no_source_denial)
    monkeypatch.setattr(proxy_api, "_stream_responses", stream)
    headers = {**DUAL_HEADERS, "X-OAI-Attestation": attestation}
    assert client.get("/backend-api/codex/models", headers=headers).status_code == 200
    denied = client.post(
        "/backend-api/codex/responses",
        headers=headers,
        json={"model": "disallowed-model", "input": "test", "stream": True},
    )
    assert denied.status_code == 403
    assert not forwarded
    accepted = client.post(
        "/backend-api/codex/responses",
        headers=headers,
        json={"model": "gpt-6.1-sol", "input": "test", "stream": True},
    )
    assert accepted.status_code == 200 and accepted.json() == {"id": "resp_gateway_admitted"}
    assert forwarded == ["scoped-key"]
    assert observed == [["gpt-6.1-sol"]]
    assert not [record for record in caplog.records if record.name == boundary.__name__]


@pytest.mark.parametrize("attestation", [pytest.param(None, id="legacy"), *ACCEPTED_ATTESTATIONS])
def test_public_responses_websocket_retains_key_policy_when_ordinary_auth_disabled(
    credential_app, monkeypatch, caplog, attestation
):
    client, _calls = credential_app
    caplog.set_level(logging.WARNING, logger=boundary.__name__)
    legacy = attestation is None

    async def settings():
        return SimpleNamespace(api_key_auth_enabled=False)

    async def allow(*args):
        return None

    async def capture(self, websocket, headers, *, api_key, **kwargs):
        if legacy:
            assert api_key is None
            assert headers["authorization"] == "Bearer legacy-key"
        else:
            assert isinstance(api_key, ApiKeyData)
            assert api_key.assigned_account_ids == ["owner"]
            assert api_key.account_assignment_scope_enabled
            assert api_key.allowed_models == ["gpt-6.1-sol"]
        assert "caller-oauth-secret" not in str(headers)
        assert "x-oai-attestation" not in headers and "x-codex-lb-key" not in headers
        upstream = _build_upstream_websocket_headers(headers, "pooled-token", "pooled-workspace")
        for private in (attestation, "caller-workspace", "gateway-secret", "private-cookie"):
            if private:
                assert private not in str(upstream)
        await websocket.send_json({"key_policy_preserved": True})
        await websocket.close()

    monkeypatch.setattr(auth_dependencies, "get_settings_cache", lambda: SimpleNamespace(get=settings))
    monkeypatch.setattr(proxy_api, "_websocket_firewall_denial_response", allow)
    monkeypatch.setattr(proxy_api, "_websocket_upstream_transport_denial", allow)
    monkeypatch.setattr(ProxyService, "proxy_responses_websocket", capture)
    headers = {"Authorization": "Bearer legacy-key"} if legacy else {**DUAL_HEADERS, "X-OAI-Attestation": attestation}
    with client.websocket_connect("ws://127.0.0.1/backend-api/codex/responses", headers=headers) as websocket:
        assert websocket.receive_json() == {"key_policy_preserved": True}
    assert not [record for record in caplog.records if record.name == boundary.__name__]


def test_public_legacy_models_still_pass_without_gateway_diagnostics(credential_app, monkeypatch, caplog):
    client, calls = credential_app
    caplog.set_level(logging.WARNING, logger=boundary.__name__)

    async def settings():
        return SimpleNamespace(api_key_auth_enabled=False)

    async def catalog(api_key):
        assert api_key is None
        return JSONResponse({"models": []})

    monkeypatch.setattr(auth_dependencies, "get_settings_cache", lambda: SimpleNamespace(get=settings))
    monkeypatch.setattr(proxy_api, "_build_codex_models_response", catalog)
    response = client.get("/backend-api/codex/models", headers={"Authorization": "Bearer legacy-key"})
    assert response.status_code == 200 and response.json() == {"models": []}
    assert not calls
    assert not [record for record in caplog.records if record.name == boundary.__name__]


@pytest.mark.parametrize(
    "builder",
    [
        _build_upstream_headers,
        _build_upstream_transcribe_headers,
        _build_upstream_websocket_headers,
        _build_upstream_live_websocket_headers,
    ],
)
def test_all_header_builders_strip_gateway_case_insensitively(builder):
    result = builder({"X-CoDeX-Lb-KeY": "must-not-leave", "originator": "codex_cli_rs"}, "stored", "owner")
    assert "must-not-leave" not in str(result)


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("prefix", [DESKTOP_VOICE_PREFIX, "/backend-api/codex/v1/desktop-voice"])
def test_auth_denial_redacts_server_owned_voice_scope_before_reply(app_instance, transport, prefix):
    observed = []

    async def observe(scope, receive, send):
        async def capture(message):
            observed.append((scope.get("path"), scope.get("raw_path"), scope.get("query_string"), scope.get("headers")))
            await send(message)

        await app_instance(scope, receive, capture)

    client = TestClient(observe)
    path = prefix + "/live/rtc_raw_private_call?query_private=hidden"
    headers = {"Authorization": "Bearer caller-private-value"}
    if transport == "http":
        assert client.get(path, headers=headers).status_code == 404
    else:
        with pytest.raises(WebSocketDenialResponse):
            with client.websocket_connect(path, headers=headers):
                pytest.fail("missing gateway key must deny before upstream")
    assert observed
    for private in ("rtc_raw_private_call", "query_private", "caller-private-value"):
        assert private not in str(observed)
