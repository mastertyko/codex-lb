The outermost application middleware preserves the transport peer and then
applies Uvicorn's forwarding projection exactly once, so two different client
identities are available downstream. `request.client` is the projected one and
exists for logging, rate accounting, and request attribution. Authorization of
the peer itself belongs to `raw_socket_peer_host`, which
`_is_proxy_unauthenticated_socket_peer_allowed` already uses and which
`app/core/request_locality.py` uses for locality.

The internal drain guard was written against `request.client.host`. That is
sound only while no projection occurs, which is the case at the default
`FORWARDED_ALLOW_IPS=127.0.0.1` with an off-host reverse proxy. Once an
operator widens that variable — `*` is explicitly supported — the projected
value becomes attacker-controlled, and these endpoints have no second gate:
the API firewall covers only `/v1` and `/backend-api/codex`, the SPA catch-all
does not shadow `/internal/`, and the health router carries no dependencies.

The same projection also breaks the legitimate caller. With
`FORWARDED_ALLOW_IPS=*`, the in-pod preStop helper connects over loopback but
is projected to whatever client the forwarded chain names, so its own drain is
refused. Binding to the raw peer fixes the bypass and that denial together.

Example: with `FORWARDED_ALLOW_IPS=*`, a request from 203.0.113.24 carrying
`X-Forwarded-For: 127.0.0.1` and `x-codex-lb-drain-deadline-monotonic: 1.0`
previously committed the one-way shutdown barrier. `stop_drain()` then answers
409, so the replica served 503 until it was restarted. It is now rejected with
403 before any shutdown state is touched.
