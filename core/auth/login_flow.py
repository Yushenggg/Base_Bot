import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from core.auth import store
from core.auth.errors import (
    ClientCredsMissingError,
    LoginDenied,
    LoginFlowExpired,
    ProviderNotFoundError,
)
from core.auth.flows.auth_code_pkce import AuthCodePkceProvider
from core.auth.flows.base import FlowProvider, FlowTicket, ProviderStatus, TokenSet
from core.auth.flows.custom import CustomProvider
from core.auth.flows.device_code import DeviceCodeProvider
from core.auth import registry

logger = logging.getLogger("AUTH.LOGIN_FLOW")

LoginStep = Literal[
    "needs_client_id",
    "needs_client_secret",
    "awaiting_user",
    "complete",
    "failed",
]


@dataclass
class LoginFlow:
    flow_id: str
    provider_id: str
    step: LoginStep
    ticket: FlowTicket | None = None
    prompt: str | None = None
    error: str | None = None
    last_poll_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    account_hint: str | None = None


_flows: dict[str, LoginFlow] = {}
_pending_client_id: dict[str, str] = {}


def _new_flow(provider_id: str, step: LoginStep) -> LoginFlow:
    fl = LoginFlow(flow_id=uuid.uuid4().hex, provider_id=provider_id, step=step)
    _flows[fl.flow_id] = fl
    return fl


def _drop(flow_id: str) -> None:
    _flows.pop(flow_id, None)
    _pending_client_id.pop(flow_id, None)


def get_flow(flow_id: str) -> LoginFlow | None:
    return _flows.get(flow_id)


def cancel_login(flow: LoginFlow) -> None:
    _drop(flow.flow_id)


def _client_creds_available(spec: FlowProvider) -> bool:
    return (
        store.load_client_creds_env_or_encrypted(
            spec.provider_id, spec.client_id_env, spec.client_secret_env
        )
        is not None
    )


async def start_login(provider_id: str, *, scopes: list[str] | None = None) -> LoginFlow:
    spec = registry.get_provider(provider_id)
    use_scopes = list(scopes) if scopes else list(spec.scopes_default)
    if not use_scopes:
        raise ClientCredsMissingError(
            provider_id, "no scopes requested and provider has no default scopes"
        )

    if isinstance(spec, CustomProvider):
        fl = _new_flow(provider_id, "awaiting_user")
        result = await spec.start("", None, use_scopes)
        fl.ticket = result.ticket
        fl.prompt = spec.prompt
        return fl

    if _client_creds_available(spec):
        creds = store.load_client_creds_env_or_encrypted(
            provider_id, spec.client_id_env, spec.client_secret_env
        )
        return await _kickoff_flow(spec, use_scopes, creds[0], creds[1])

    if not spec.client_id_env:
        raise ClientCredsMissingError(provider_id)

    fl = _new_flow(provider_id, "needs_client_id")
    fl.scopes = use_scopes
    fl.prompt = (
        f"Paste your {spec.display_name} Client ID.\n"
        f"(If you don't have one yet, see: {spec.setup_urls[0][1] if spec.setup_urls else 'provider docs'})"
    )
    return fl


async def provide_credential(flow: LoginFlow, value: str) -> LoginFlow:
    spec = registry.get_provider(flow.provider_id)
    value = value.strip()

    if flow.step == "needs_client_id":
        if not value:
            flow.error = "empty client id"
            return flow
        _pending_client_id[flow.flow_id] = value
        if spec.client_secret_env:
            flow.step = "needs_client_secret"
            flow.prompt = f"Paste your {spec.display_name} Client Secret."
            return flow
        fl = await _kickoff_flow(spec, flow.scopes, value, "")
        _pending_client_id.pop(flow.flow_id, None)
        return fl

    if flow.step == "needs_client_secret":
        client_id = _pending_client_id.get(flow.flow_id)
        if not client_id:
            flow.error = "internal: client id missing"
            flow.step = "failed"
            return flow
        store.save_client_creds(spec.provider_id, client_id, value or None)
        _pending_client_id.pop(flow.flow_id, None)
        fl = await _kickoff_flow(spec, flow.scopes, client_id, value)
        fl.flow_id = flow.flow_id
        _flows[fl.flow_id] = fl
        return fl

    if flow.step == "awaiting_user":
        if isinstance(spec, AuthCodePkceProvider) and flow.ticket is not None:
            return await _exchange_pkce(spec, flow, value)
        if isinstance(spec, CustomProvider) and flow.ticket is not None:
            return await _complete_custom(spec, flow, value)
        return flow

    return flow


async def _kickoff_flow(
    spec: FlowProvider,
    scopes: list[str],
    client_id: str,
    client_secret: str,
) -> LoginFlow:
    if isinstance(spec, CustomProvider):
        fl = _new_flow(spec.provider_id, "awaiting_user")
        result = await spec.start(client_id, client_secret or None, scopes)
        fl.ticket = result.ticket
        fl.prompt = spec.prompt
        fl.scopes = scopes
        return fl

    if not spec.client_secret_env and not client_secret:
        store.save_client_creds(spec.provider_id, client_id, None)

    result = await spec.start(client_id, client_secret or None, scopes)

    if result.status == "error":
        fl = _new_flow(spec.provider_id, "failed")
        fl.error = result.error or "start failed"
        return fl

    fl = _new_flow(spec.provider_id, "awaiting_user")
    fl.ticket = result.ticket
    fl.scopes = scopes
    if isinstance(spec, DeviceCodeProvider):
        fl.prompt = (
            f"Open {result.ticket.verification_uri} and enter code "
            f"{result.ticket.user_code}.\nThen click Allow."
        )
    elif isinstance(spec, AuthCodePkceProvider):
        fl.prompt = (
            f"Open this URL in your browser and approve:\n{result.ticket.auth_url}\n"
            f"Copy the authorization code from the redirect and paste it here."
        )
    else:
        fl.prompt = result.prompt or "Complete the provider's authentication step."
    return fl


async def _exchange_pkce(spec: AuthCodePkceProvider, flow: LoginFlow, code: str) -> LoginFlow:
    if not code:
        flow.error = "empty authorization code"
        return flow
    creds = store.load_client_creds_env_or_encrypted(
        spec.provider_id, spec.client_id_env, spec.client_secret_env
    )
    if creds is None:
        flow.step = "failed"
        flow.error = "client creds missing"
        return flow
    try:
        tokens = await spec.exchange(creds[0], creds[1] or None, flow.ticket, code)
    except Exception as e:
        flow.step = "failed"
        flow.error = str(e)
        return flow
    tokens = _with_metadata(tokens, flow.scopes)
    store.save_tokens(spec.provider_id, tokens)
    flow.step = "complete"
    flow.account_hint = tokens.account_hint
    return flow


async def _complete_custom(
    spec: CustomProvider, flow: LoginFlow, value: str
) -> LoginFlow:
    if not value:
        flow.error = "empty value"
        return flow
    try:
        tokens = await spec.complete(flow.ticket, value)
    except Exception as e:
        flow.step = "failed"
        flow.error = str(e)
        return flow
    tokens = _with_metadata(tokens, flow.scopes)
    store.save_tokens(spec.provider_id, tokens)
    flow.step = "complete"
    flow.account_hint = tokens.account_hint
    return flow


def _with_metadata(tokens: TokenSet, scopes: list[str]) -> TokenSet:
    update: dict = {}
    if not tokens.scopes:
        update["scopes"] = scopes
    if tokens.issued_at is None:
        update["issued_at"] = datetime.now(timezone.utc)
    return tokens.model_copy(update=update) if update else tokens


async def poll_login(flow: LoginFlow) -> LoginFlow:
    spec = registry.get_provider(flow.provider_id)
    if flow.step != "awaiting_user" or flow.ticket is None:
        return flow
    if not isinstance(spec, DeviceCodeProvider):
        return flow

    if flow.ticket.expires_at and datetime.now(timezone.utc) >= flow.ticket.expires_at:
        flow.step = "failed"
        flow.error = "device code expired"
        return flow

    creds = store.load_client_creds_env_or_encrypted(
        spec.provider_id, spec.client_id_env, spec.client_secret_env
    )
    if creds is None:
        flow.step = "failed"
        flow.error = "client creds missing"
        return flow

    result = await spec.poll(creds[0], creds[1] or None, flow.ticket)
    flow.last_poll_at = datetime.now(timezone.utc)

    if result.status == "pending":
        return flow
    if result.status == "slow_down":
        flow.ticket = result.ticket
        return flow
    if result.status == "complete" and result.tokens is not None:
        tokens = _with_metadata(result.tokens, flow.scopes)
        store.save_tokens(spec.provider_id, tokens)
        flow.step = "complete"
        flow.account_hint = tokens.account_hint
        return flow
    if result.status == "expired":
        raise LoginFlowExpired(spec.provider_id, "device code expired")
    if result.status == "denied":
        raise LoginDenied(spec.provider_id, "user denied")
    if result.status == "error":
        flow.step = "failed"
        flow.error = result.error or "poll error"
        return flow
    return flow


def expire_idle_flows(max_idle_seconds: int = 600) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - max_idle_seconds
    expired = 0
    for fid in list(_flows.keys()):
        fl = _flows[fid]
        last = fl.last_poll_at or _pending_client_id.get(fid) and datetime.now(timezone.utc)
        anchor = last or datetime.fromtimestamp(0, tz=timezone.utc)
        if anchor.timestamp() < cutoff and fl.step not in ("complete", "failed"):
            _drop(fid)
            expired += 1
    return expired
