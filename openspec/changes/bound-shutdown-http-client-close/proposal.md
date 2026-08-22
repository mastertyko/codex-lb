## Why

Shutdown bounds every step around the managed HTTP client close but not the
close itself. The leader lease release is abandoned after 10s and the metrics
server after 5s, while `await close_http_client()` waits with no deadline on
one `closed` event per managed client.

Those events are set by each client's own close task. An upstream WebSocket or
streaming session stalled in TLS or TCP teardown never sets its event, so the
wait never returns. It sits directly above the `finally` chain that runs
`mark_process_dead()` and `close_db()`, so a stall there strands both — the
replica stays marked live in the ring and its pool is never disposed. That
contradicts the surrounding comment, which states shutdown always proceeds.

## What Changes

- Wait for the managed HTTP client close under a 10s deadline, matching the
  leader lease release budget alongside it.
- Abandon the wait rather than cancel it when the deadline passes, and log the
  eventual outcome from a done callback.

## Capabilities

### Modified Capabilities

- `graceful-shutdown`: post-drain teardown must stay bounded so process-death
  marking and database disposal always run.

## Impact

Limited to the shutdown path in `app/main.py` and its unit tests. Drain
deadlines, the preStop contract, and client-close semantics are unchanged: the
clients are still force-closed first, and their teardown keeps running after an
abandoned wait. No setting, migration, or dependency is added.
