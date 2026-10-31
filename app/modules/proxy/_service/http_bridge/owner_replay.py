"""Context proof for an unchanged full resend pinned to its durable owner."""

from __future__ import annotations

from collections.abc import Mapping

from app.core.openai.requests import MutableJsonObject, strip_replayed_tool_call_namespaces_from_payload
from app.core.types import JsonValue
from app.modules.proxy.replay_safety import (
    _is_retained_response_message,
    _message_has_valid_account_neutral_content,
    project_responses_input_for_account_neutral_fresh_replay,
    responses_input_suffix_matches_pending_tool_calls,
)


def retains_owner_bound_tool_context(
    input_items: list[JsonValue], *, stored_count: int, pending_tool_calls: Mapping[str, str] | None
) -> bool:
    """Verify context only; never serialize this projection or use it to move accounts.

    The caller separately proves the durable prefix and owner. Native metadata
    and reasoning remain in the original wire body on that owner. The projection
    lets the existing exact-manifest verifier check tool settlement independently
    of metadata's stricter cross-account policy.
    """
    if not pending_tool_calls:
        return False
    wire_shape: MutableJsonObject = {"input": input_items}
    strip_replayed_tool_call_namespaces_from_payload(wire_shape)
    normalized_input = wire_shape["input"]
    assert isinstance(normalized_input, list)
    projection = project_responses_input_for_account_neutral_fresh_replay(
        normalized_input, stored_count=stored_count, preserve_developer_message_ids=True
    )
    if projection is None:
        return False
    items: list[JsonValue] = [
        {key: value for key, value in item.items() if key != "internal_chat_message_metadata_passthrough"}
        if isinstance(item, dict)
        else item
        for item in projection.input_items
    ]
    boundary = projection.stored_prefix_count
    # A retained assistant preamble may precede the response's calls. It cannot
    # substitute for a call or result, or introduce new input after settlement.
    # The prefix is already bound to an accepted request by its exact hash.
    # Keep historical developer controls on the wire, but do not apply the
    # cross-account interleave restriction while checking its tool lifecycle.
    prefix: list[JsonValue] = []
    for item in items[:boundary]:
        if isinstance(item, dict) and item.get("role") == "developer" and item.get("type") in (None, "message"):
            if not _message_has_valid_account_neutral_content(item):
                return False
            continue
        prefix.append(item)
    end = boundary
    while end < len(items):
        item = items[end]
        if not isinstance(item, dict) or item.get("role") != "assistant":
            break
        if not _is_retained_response_message(item):
            return False
        end += 1
    return responses_input_suffix_matches_pending_tool_calls(
        [*prefix, *items[end:]],
        stored_count=len(prefix),
        pending_tool_calls=pending_tool_calls,
    )
