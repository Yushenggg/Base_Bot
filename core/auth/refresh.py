import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core.auth.flows.base import AccessToken, FlowProvider, TokenSet
from core.auth import store

logger = logging.getLogger("AUTH.REFRESH")

_DEFAULT_SKEW = timedelta(seconds=60)

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(provider_id: str) -> asyncio.Lock:
    if provider_id not in _locks:
        _locks[provider_id] = asyncio.Lock()
    return _locks[provider_id]


def _needs_refresh(tokens: TokenSet, skew: timedelta) -> bool:
    if tokens.expires_at is None:
        return False
    return datetime.now(timezone.utc) >= (tokens.expires_at - skew)


async def get_credential(
    spec: FlowProvider,
    *,
    scopes: list[str] | None = None,
    skew: timedelta = _DEFAULT_SKEW,
) -> AccessToken:
    cached = store.load_tokens(spec.provider_id)
    if cached is None:
        from core.auth.errors import NotLoggedInError

        raise NotLoggedInError(spec.provider_id)

    requested = set(scopes) if scopes else set(cached.scopes)
    granted = set(cached.scopes)
    missing = requested - granted
    if missing and not scopes:
        missing = set()
    if missing:
        from core.auth.errors import ScopeNotGrantedError

        raise ScopeNotGrantedError(spec.provider_id, sorted(missing))

    if not _needs_refresh(cached, skew):
        return AccessToken(
            access_token=cached.access_token,
            expires_at=cached.expires_at,
            scopes=cached.scopes,
            account_hint=cached.account_hint,
        )

    if cached.refresh_token is None:
        from core.auth.errors import ReauthRequiredError

        raise ReauthRequiredError(spec.provider_id, "no refresh token")

    async with _lock_for(spec.provider_id):
        cached = store.load_tokens(spec.provider_id)
        if cached is None:
            from core.auth.errors import NotLoggedInError

            raise NotLoggedInError(spec.provider_id)
        if not _needs_refresh(cached, skew):
            return AccessToken(
                access_token=cached.access_token,
                expires_at=cached.expires_at,
                scopes=cached.scopes,
                account_hint=cached.account_hint,
            )

        creds = store.load_client_creds_env_or_encrypted(
            spec.provider_id,
            spec.client_id_env,
            spec.client_secret_env,
        )
        if creds is None:
            from core.auth.errors import ClientCredsMissingError

            raise ClientCredsMissingError(spec.provider_id)

        client_id, client_secret = creds
        try:
            fresh = await spec.refresh(client_id, client_secret or None, cached.refresh_token)
        except Exception as e:
            err = str(e).lower()
            if "invalid_grant" in err or "invalid_grant" in str(e):
                store.delete_tokens(spec.provider_id)
                from core.auth.errors import ReauthRequiredError

                raise ReauthRequiredError(spec.provider_id, str(e)) from e
            logger.error("refresh failed for %s: %s", spec.provider_id, e)
            from core.auth.errors import ReauthRequiredError

            raise ReauthRequiredError(spec.provider_id, str(e)) from e

        if fresh.refresh_token is None:
            fresh = fresh.model_copy(update={"refresh_token": cached.refresh_token})

        if fresh.account_hint is None:
            fresh = fresh.model_copy(update={"account_hint": cached.account_hint})

        store.save_tokens(spec.provider_id, fresh)
        logger.info("refreshed tokens for %s", spec.provider_id)

        return AccessToken(
            access_token=fresh.access_token,
            expires_at=fresh.expires_at,
            scopes=fresh.scopes,
            account_hint=fresh.account_hint,
        )
