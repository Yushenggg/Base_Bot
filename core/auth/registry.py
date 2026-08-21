import logging
from typing import Literal

from core.auth.flows.base import FlowProvider, ProviderInfo, ProviderStatus
from core.auth import store

logger = logging.getLogger("AUTH.REGISTRY")

_providers: dict[str, FlowProvider] = {}


def register_provider(spec: FlowProvider) -> None:
    if spec.provider_id in _providers:
        logger.debug("re-registering provider %s", spec.provider_id)
    _providers[spec.provider_id] = spec
    logger.info("registered provider %s (%s)", spec.provider_id, type(spec).__name__)


def list_providers() -> list[ProviderInfo]:
    out: list[ProviderInfo] = []
    for pid, spec in _providers.items():
        creds = store.load_client_creds_env_or_encrypted(
            pid, spec.client_id_env, spec.client_secret_env
        )
        tokens = store.load_tokens(pid)
        out.append(
            ProviderInfo(
                provider_id=pid,
                display_name=spec.display_name,
                flow_kind=spec.flow_kind,
                scopes_default=list(spec.scopes_default),
                scopes_supported=list(spec.scopes_supported),
                setup_urls=list(spec.setup_urls),
                setup_instructions=spec.setup_instructions,
                has_client_creds=creds is not None,
                logged_in=tokens is not None,
            )
        )
    return out


def get_provider(provider_id: str) -> FlowProvider:
    from core.auth.errors import ProviderNotFoundError

    spec = _providers.get(provider_id)
    if spec is None:
        raise ProviderNotFoundError(provider_id)
    return spec


def get_provider_status(provider_id: str) -> ProviderStatus:
    spec = get_provider(provider_id)
    env_cid = None
    env_sec = None
    if spec.client_id_env:
        import os

        env_cid = os.environ.get(spec.client_id_env)
    if spec.client_secret_env:
        import os

        env_sec = os.environ.get(spec.client_secret_env)

    has_env = bool(env_cid and (env_sec or not spec.client_secret_env))
    has_enc = store.has_encrypted_client_creds(provider_id)

    if has_env:
        source: Literal["env", "encrypted", "none"] = "env"
    elif has_enc:
        source = "encrypted"
    else:
        source = "none"

    tokens = store.load_tokens(provider_id)
    return ProviderStatus(
        provider_id=provider_id,
        display_name=spec.display_name,
        has_client_creds=has_env or has_enc,
        client_creds_source=source,
        logged_in=tokens is not None,
        account_hint=tokens.account_hint if tokens else None,
        scopes=list(tokens.scopes) if tokens else [],
        expires_at=tokens.expires_at if tokens else None,
    )


def all_provider_ids() -> list[str]:
    return sorted(_providers.keys())
