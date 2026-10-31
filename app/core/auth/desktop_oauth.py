"""Server-granted native OAuth admission, independent of untrusted JWT selectors."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from starlette.requests import HTTPConnection

from app.core.auth.desktop_diagnostics import emit
from app.core.auth.desktop_identity import (
    DesktopIdentityAuthError,
    DesktopIdentityPrincipal,
    parse_desktop_identity_principal,
    verify_desktop_identity_principal,
)
from app.core.config.settings import get_settings
from app.core.exceptions import ProxyAuthError
from app.core.utils.shared_future import _await_result_deferring_cancellation
from app.db.session import get_background_session
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyData, ApiKeyInvalidError, ApiKeysService


@dataclass(frozen=True, slots=True)
class DesktopOAuthCredentials:
    access_token: str = field(repr=False)
    chatgpt_account_id: str | None = field(repr=False)
    attestation: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class DesktopOAuthAdmission:
    credentials: DesktopOAuthCredentials = field(repr=False)
    principal: DesktopIdentityPrincipal = field(repr=False)
    api_key: ApiKeyData = field(repr=False)

    @property
    def pool_namespace(self) -> str:
        identity = f"{self.principal.user_id}\0{self.principal.workspace_id}\0{self.api_key.id}"
        return hashlib.sha256(identity.encode()).hexdigest()


def get_desktop_oauth(connection: HTTPConnection) -> DesktopOAuthAdmission | None:
    value = getattr(connection.state, "desktop_oauth", None)
    return value if isinstance(value, DesktopOAuthAdmission) else None


def _grant_key(principal: DesktopIdentityPrincipal) -> str:
    matches = [
        grant.api_key_id
        for grant in get_settings().desktop_oauth_grants
        if grant.user_id == principal.user_id and grant.workspace_id == principal.workspace_id
    ]
    if len(matches) != 1:
        raise ProxyAuthError("Native Desktop access is not granted")
    return matches[0]


async def recheck_desktop_grant(principal: DesktopIdentityPrincipal, key_id: str) -> ApiKeyData:
    if _grant_key(principal) != key_id:
        raise ProxyAuthError("Native Desktop grant changed")

    async def load_key() -> ApiKeyData:
        async with get_background_session() as session:
            try:
                return await ApiKeysService(ApiKeysRepository(session)).get_key_by_id(key_id)
            except ApiKeyInvalidError:
                raise ProxyAuthError("Native Desktop key is unavailable") from None

    key, cancellation = await _await_result_deferring_cancellation(load_key())
    if cancellation is not None:
        raise cancellation
    if _grant_key(principal) != key_id:
        raise ProxyAuthError("Native Desktop grant changed")
    return key


async def authenticate_desktop_oauth(
    credentials: DesktopOAuthCredentials,
    *,
    previous: DesktopOAuthAdmission | None = None,
) -> DesktopOAuthAdmission:
    emit("auth_start")
    try:
        result = await _authenticate(credentials, previous=previous)
    except Exception:
        emit("auth_denied", reason="auth")
        raise
    emit("auth_allowed")
    return result


async def _authenticate(
    credentials: DesktopOAuthCredentials,
    *,
    previous: DesktopOAuthAdmission | None,
) -> DesktopOAuthAdmission:
    try:
        selector = parse_desktop_identity_principal(credentials.access_token, credentials.chatgpt_account_id)
    except DesktopIdentityAuthError:
        emit("auth_verification_failed", reason="invalid_selector")
        raise
    key_id = _grant_key(selector)
    if previous is not None and (selector != previous.principal or key_id != previous.api_key.id):
        raise ProxyAuthError("Native Desktop identity changed")
    principal = await verify_desktop_identity_principal(credentials)
    if principal != selector:
        raise ProxyAuthError("Native Desktop identity changed")
    key = await recheck_desktop_grant(principal, key_id)
    return DesktopOAuthAdmission(credentials, principal, key)
