"""Lossless native quota handoff proofs, separate from generic retry safety.

The projection below is only a validator. Dispatch always uses the original
input, including encrypted context, ids, namespaces and metadata.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from app.core.openai.requests import strip_replayed_tool_call_namespaces_from_payload
from app.core.types import JsonValue
from app.modules.proxy.replay_safety import (
    _is_retained_response_message,
    responses_input_suffix_matches_pending_tool_calls,
    responses_input_suffix_retains_prior_output,
    responses_payload_is_account_neutral_fresh_replay,
)


def _project_tools(value: JsonValue) -> list[JsonValue] | None:
    if not isinstance(value, list):
        return None
    tools: list[JsonValue] = []
    for tool in value:
        if not isinstance(tool, dict):
            return None
        if tool.get("type") != "namespace":
            tools.append(tool)
            continue
        if (
            set(tool) - {"type", "name", "description", "tools"}
            or not isinstance(tool.get("name"), str)
            or not tool["name"]
        ):
            return None
        children = _project_tools(tool.get("tools"))
        if children is None:
            return None
        tools.extend(children)
    return tools


def native_quota_context_is_complete(
    payload: Mapping[str, JsonValue],
    *,
    stored_count: int,
    pending_tool_calls: Mapping[str, str] | None,
) -> bool:
    """Validate a previously prefix-matched full resend without altering it."""
    projected = deepcopy(dict(payload))
    if projected.pop("type", "response.create") != "response.create":
        return False
    reasoning = projected.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("context") == "all_turns":
        reasoning.pop("context")
    inputs = projected.get("input")
    if not isinstance(inputs, list) or not 0 < stored_count < len(inputs):
        return False
    strip_replayed_tool_call_namespaces_from_payload(projected)
    inputs = projected.get("input")
    assert isinstance(inputs, list)
    items: list[JsonValue] = []
    boundary = 0
    for index, value in enumerate(inputs):
        if not isinstance(value, dict):
            return False
        item = dict(value)
        kind = item.get("type")
        if kind is not None and not isinstance(kind, str):
            return False
        # Only documented native bookkeeping is ignored by the proof. It is
        # still sent byte-for-byte as JSON values in the real request.
        metadata = item.pop("internal_chat_message_metadata_passthrough", None)
        if metadata is not None and (
            not isinstance(metadata, dict) or set(metadata) - {"turn_id", "create_time", "content_item_kinds"}
        ):
            return False
        item.pop("id", None)
        if kind in {"reasoning", "compaction"}:
            encrypted = item.get("encrypted_content")
            if (
                not isinstance(encrypted, str)
                or not encrypted.strip()
                or set(item) - {"type", "encrypted_content", "summary", "content", "status"}
                or item.get("status") not in (None, "completed")
            ):
                return False
            # A new compaction changes the stored prefix rather than extending
            # it. It cannot stand in for the previous response's output.
            if kind == "compaction" and index >= stored_count:
                return False
        else:
            if kind == "additional_tools":
                tools = _project_tools(item.get("tools"))
                if tools is None:
                    return False
                item["tools"] = tools
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        for key in ("annotations", "logprobs"):
                            if part.get(key) == []:
                                part.pop(key)
            if index < stored_count and item.get("role") in {"developer", "system"} and kind != "additional_tools":
                # Historical instructions are retained on the wire. Validate
                # their content, but do not interpret them as new tool output.
                if not responses_payload_is_account_neutral_fresh_replay({"input": [item]}):
                    return False
            else:
                # No unfinished async call may move even when a later final
                # assistant message exists. The generic validator permits
                # pending async calls; quota handoff deliberately does not.
                if item.get("async") is True:
                    return False
                items.append(item)
        if index + 1 == stored_count:
            boundary = len(items)
    if "tools" in projected:
        tools = _project_tools(projected["tools"])
        if tools is None:
            return False
        projected["tools"] = tools
    projected["input"] = items
    if not responses_payload_is_account_neutral_fresh_replay(projected):
        return False
    if not pending_tool_calls:
        # Native clients append developer/system control messages on abort or
        # resume. Like a new user message they cannot stand in for prior output.
        for item in items[boundary:]:
            if isinstance(item, dict) and item.get("role") in {"developer", "system"}:
                item["role"] = "user"
        return responses_input_suffix_retains_prior_output(items, stored_count=boundary)
    # The preceding response can contain commentary before its tool calls.
    # It cannot replace any call/result from the complete recorded manifest.
    end = boundary
    while end < len(items):
        item = items[end]
        if not isinstance(item, dict) or item.get("role") != "assistant":
            break
        if not _is_retained_response_message(item):
            return False
        end += 1
    # A client can append user instructions or native abort/resume controls
    # while a tool result is returning. Validate every recorded result first.
    tail = len(items)
    while tail > end:
        item = items[tail - 1]
        if not isinstance(item, dict) or item.get("role") not in {"user", "developer", "system"}:
            break
        tail -= 1
    return responses_input_suffix_matches_pending_tool_calls(
        [*items[:boundary], *items[end:tail]],
        stored_count=boundary,
        pending_tool_calls=pending_tool_calls,
    )
