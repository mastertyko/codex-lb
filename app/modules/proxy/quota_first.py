from __future__ import annotations

from app.core.clients.proxy import ProxyResponseError
from app.core.errors import openai_error
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy._load_balancer.quota_first import account_allowed
from app.modules.proxy.load_balancer import LoadBalancer


async def enforce_quota_first_admission(
    balancer: LoadBalancer,
    *,
    routing_strategy: str,
    account_id: str,
    model: str | None,
    service_tier: str | None,
    api_key: ApiKeyData | None,
    require_security_work_authorized: bool = False,
) -> None:
    if routing_strategy != "quota_first_balanced":
        return
    account_ids = (
        set(api_key.assigned_account_ids) if api_key is not None and api_key.account_assignment_scope_enabled else None
    )
    if not await account_allowed(
        balancer,
        account_id,
        model=model,
        service_tier=service_tier,
        account_ids=account_ids,
        require_security_work_authorized=require_security_work_authorized,
    ):
        raise ProxyResponseError(
            503,
            openai_error(
                "quota_first_owner_unavailable",
                "This account cannot serve under quota-first routing; retry after subscription availability changes.",
                error_type="server_error",
            ),
        )
