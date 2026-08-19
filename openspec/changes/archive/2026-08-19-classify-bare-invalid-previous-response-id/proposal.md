# Classify bare invalid previous-response errors

## Summary

The ChatGPT Codex WebSocket backend can reject an expired continuation anchor with
`Invalid \`previous_response_id\`.` while omitting `code`, `param`, or both. codex-lb
currently requires a structured code before it recognizes that exact message, so the
frame bypasses stale-anchor recovery and long foreground tool, background-completion,
and long-running client continuations terminate the parent turn.

Recognize precise stale-anchor messages even when optional structured fields are
absent. Safe self-contained requests may use the existing full-context replay without
`previous_response_id`; delta-only requests must receive the canonical
`previous_response_not_found` classifier so clients that retain full history can retry.

The same recovery audit found that retry safety and cross-account portability are
currently conflated. A replay body containing encrypted reasoning or other
account-bound state may lose its hard owner requirement after the stale anchor is
removed. Cross-account movement must therefore require the repository's canonical
account-neutral replay proof on the exact outgoing body.

## Why

Two production parent turns failed after the continuation anchor idled while local
work completed. Session and request logs show the same bare upstream message and zero
output tokens. Compatible clients retain the complete conversation and clear their
continuation cache when codex-lb emits the canonical stale-anchor code, so server-side
synthesis of missing delta history is neither necessary nor safe.

## What Changes

- Extend stale-anchor classification for exact invalid-anchor and not-found messages
  when optional structured fields are absent.
- Add direct WebSocket coverage for proxy-owned full resends and client-owned
  delta-only continuations using the observed envelope.
- Keep server-side delta replay fail-closed and surface the canonical client recovery
  code without exposing response ids.
- Separate same-account retry safety from cross-account portability.
- Require canonical account-neutral proof before any account-changing replay or
  cross-transport fallback.
- Keep account-bound stale replays pinned to their original owner after anchor removal.
- Preserve generic invalid-request handling for unrelated parameters and messages.
