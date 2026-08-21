from core.auth.errors import (
    AuthError,
    ClientCredsMissingError,
    LoginDenied,
    LoginFlowExpired,
    NotLoggedInError,
    ProviderNotFoundError,
    ReauthRequiredError,
    ScopeNotGrantedError,
)
from core.auth.flows.auth_code_pkce import AuthCodePkceProvider
from core.auth.flows.base import (
    AccessToken,
    FlowProvider,
    FlowResult,
    FlowTicket,
    ProviderInfo,
    ProviderStatus,
    TokenSet,
)
from core.auth.flows.custom import CustomProvider
from core.auth.flows.device_code import DeviceCodeProvider
from core.auth.login_flow import (
    LoginFlow,
    cancel_login,
    expire_idle_flows,
    get_flow,
    poll_login,
    provide_credential,
    start_login,
)
from core.auth import registry, secrets as _secrets
from core.auth import store as _store


def init() -> None:
    _store.init()


def register_provider(spec: FlowProvider) -> None:
    registry.register_provider(spec)


def list_providers() -> list[ProviderInfo]:
    return registry.list_providers()


def get_provider(provider_id: str) -> FlowProvider:
    return registry.get_provider(provider_id)


def get_provider_status(provider_id: str) -> ProviderStatus:
    return registry.get_provider_status(provider_id)


def all_provider_ids() -> list[str]:
    return registry.all_provider_ids()


async def get_credential(
    provider_id: str, *, scopes: list[str] | None = None
) -> AccessToken:
    from core.auth.refresh import get_credential as _get_cred

    spec = registry.get_provider(provider_id)
    return await _get_cred(spec, scopes=scopes)


async def logout(provider_id: str) -> None:
    registry.get_provider(provider_id)
    _store.delete_tokens(provider_id)


def auth_secret_paths() -> list[str]:
    return _secrets.auth_secret_paths()


def is_auth_secret_path(path) -> bool:
    from pathlib import Path

    return _secrets.is_auth_secret_path(Path(path))


__all__ = [
    "AccessToken",
    "AuthCodePkceProvider",
    "AuthError",
    "ClientCredsMissingError",
    "CustomProvider",
    "DeviceCodeProvider",
    "FlowProvider",
    "FlowResult",
    "FlowTicket",
    "LoginDenied",
    "LoginFlow",
    "LoginFlowExpired",
    "NotLoggedInError",
    "ProviderInfo",
    "ProviderNotFoundError",
    "ProviderStatus",
    "ReauthRequiredError",
    "ScopeNotGrantedError",
    "TokenSet",
    "all_provider_ids",
    "auth_secret_paths",
    "cancel_login",
    "expire_idle_flows",
    "get_credential",
    "get_flow",
    "get_provider",
    "get_provider_status",
    "init",
    "is_auth_secret_path",
    "list_providers",
    "logout",
    "poll_login",
    "provide_credential",
    "register_provider",
    "start_login",
]
