"""Content-free native routing diagnostics, enabled by an operator log handler."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.core.types import JsonValue

LOGGER_NAME = "codex_lb.desktop_diagnostics"
logger = logging.getLogger(LOGGER_NAME)
Source = Literal["composer_predictions", "user", "other", "absent", "invalid"]
Event = Literal[
    "received",
    "auth_start",
    "auth_allowed",
    "auth_denied",
    "request_route",
    "auth_verification_started",
    "auth_egress_ready",
    "auth_upstream_status",
    "auth_verified",
    "auth_verification_failed",
    "auth_verification_cancelled",
    "frame",
    "classified",
    "owner_lookup",
    "owner_validated",
    "owner_ready",
    "policy_allowed",
    "upstream_connect",
    "upstream_start",
    "upstream_connected",
    "upstream_status",
    "completed",
    "incomplete",
    "upstream_failed",
    "denied",
    "failed",
    "cancelled",
    "disconnected",
    "closed",
]


def _source(value: JsonValue) -> Source:
    if value is None:
        return "absent"
    if value == "composer_predictions":
        return "composer_predictions"
    if value == "user":
        return "user"
    return "other" if isinstance(value, str) else "invalid"


@dataclass(slots=True)
class DesktopTrace:
    transport: Literal["http", "websocket"]
    method: Literal["GET", "POST", "OTHER"] | None = None
    stage: Event = "received"
    lane: Literal["unclassified", "pool", "caller"] = "unclassified"
    frame_number: int = 0
    source: Source = "absent"
    trigger: Source = "absent"
    generate: bool | None = None
    previous_response_present: bool = False
    text_deltas: int = 0
    output_items: int = 0

    def emit(self, event: Event, *, status: int | None = None, reason: str | None = None) -> None:
        # Never serialize exceptions, arbitrary strings, identities, headers or payloads.
        safe_reason = (
            reason
            if reason
            in {
                "auth",
                "validation",
                "unknown_continuity",
                "files",
                "policy_changed",
                "owner",
                "capacity",
                "lane",
                "protocol",
                "timeout",
                "transport",
                "other",
                "responses",
                "models",
                "compact",
                "image_generation",
                "image_edit",
                "search",
                "unsupported_route",
                "unsupported_token",
                "invalid_selector",
                "direct",
                "configured_egress",
                "route_failure",
                "negative_verification",
                "upstream_status",
                "response_type",
                "response_size",
                "response_schema",
                "cleanup",
            }
            else None
        )
        logger.info(
            json.dumps(
                {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "event": event,
                    "stage": self.stage,
                    "transport": self.transport,
                    "method": self.method,
                    "lane": self.lane,
                    "frame_number": self.frame_number,
                    "source": self.source,
                    "trigger": self.trigger,
                    "generate": self.generate,
                    "previous_response_present": self.previous_response_present,
                    "text_deltas": self.text_deltas,
                    "output_items": self.output_items,
                    "status": status,
                    "reason": safe_reason,
                },
                separators=(",", ":"),
            )
        )
        if event not in {
            "failed",
            "denied",
            "cancelled",
            "disconnected",
            "closed",
            "auth_denied",
            "auth_verification_failed",
            "auth_verification_cancelled",
        }:
            self.stage = event

    def frame(self, payload: Mapping[str, JsonValue]) -> None:
        self.frame_number += 1
        self.text_deltas = self.output_items = 0
        generate = payload.get("generate")
        self.generate = generate if isinstance(generate, bool) else None
        self.previous_response_present = payload.get("previous_response_id") is not None
        self.source = self.trigger = "absent"
        metadata = payload.get("client_metadata")
        raw = metadata.get("x-codex-turn-metadata") if isinstance(metadata, dict) else None
        if isinstance(raw, str) and len(raw) <= 64 * 1024:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    self.source = _source(parsed.get("thread_source"))
                    self.trigger = _source(parsed.get("turn_trigger"))
                else:
                    self.source = self.trigger = "invalid"
            except (ValueError, RecursionError):
                self.source = self.trigger = "invalid"
        elif raw is not None:
            self.source = self.trigger = "invalid"
        self.emit("frame")

    def classify(self, caller: bool) -> None:
        self.lane = "caller" if caller else "pool"
        self.emit("classified")

    def observe(self, event: Mapping[str, JsonValue]) -> None:
        kind = event.get("type")
        if kind == "response.output_text.delta":
            self.text_deltas += 1
        elif kind == "response.output_item.added":
            self.output_items += 1
        elif kind == "response.completed":
            self.emit("completed")
        elif kind == "response.incomplete":
            self.emit("incomplete")
        elif kind == "response.failed" or kind == "error":
            self.emit("upstream_failed")


_trace: ContextVar[DesktopTrace | None] = ContextVar("desktop_trace", default=None)


@contextmanager
def trace_request(transport: Literal["http", "websocket"], method: str | None = None) -> Iterator[None]:
    safe_method: Literal["GET", "POST", "OTHER"] | None = None
    if transport == "http":
        safe_method = "GET" if method == "GET" else "POST" if method == "POST" else "OTHER"
    trace = DesktopTrace(transport, method=safe_method)
    token = _trace.set(trace)
    trace.emit("received")
    try:
        yield
    except asyncio.CancelledError:
        trace.emit("cancelled")
        raise
    finally:
        trace.emit("closed")
        _trace.reset(token)


def current_trace() -> DesktopTrace | None:
    return _trace.get()


def emit(event: Event, *, status: int | None = None, reason: str | None = None) -> None:
    if (trace := current_trace()) is not None:
        trace.emit(event, status=status, reason=reason)
