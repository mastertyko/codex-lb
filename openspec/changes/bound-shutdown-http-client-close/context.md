The shutdown sequence in `app/main.py` is deliberate about never letting one
stage pin the process. `_release_leader_lease_within(10)` documents why it
abandons rather than cancels: the release shields its own database teardown, so
cancelling the waiter would not unwind a wedged call. The metrics server gets
`asyncio.wait_for(..., timeout=5)`. The managed HTTP client close sat between
them with no bound at all.

The same abandon-don't-cancel reasoning applies. `close_http_client()` first
force-closes every managed client, which spawns one `_close_managed_client`
task each, and then gathers their `closed` events. Those tasks are the owners
of the teardown; cancelling the gather would only unwind the waiter and would
not make a stalled TLS or TCP close finish any sooner. So the fix reuses the
lease-release shape rather than `wait_for`.

The blast radius is what makes it worth bounding. The close sits directly above
the `finally` chain carrying `mark_process_dead()` and `close_db()`. A stall
there leaves the replica advertised as live in the bridge ring while it is
already draining, and leaves its connection pool undisposed.

Example: a replica is terminated while an upstream Codex WebSocket is stuck in
TLS close_notify. Its `closed` event is never set. Shutdown previously waited
on that event indefinitely; it now gives up after 10s, logs the abandonment,
and proceeds to mark the process dead and dispose the pool while the transport
finishes unwinding in the background.
