import logging
from datetime import datetime, timedelta, timezone

import httpx

from core.auth.flows.base import (
    FlowProvider,
    FlowResult,
    FlowTicket,
    TokenSet,
)

logger = logging.getLogger("AUTH.DEVICE_CODE")

DEFAULT_TIMEOUT = 15.0


class DeviceCodeProvider(FlowProvider):
    device_code_url: str
    token_url: str
    polling_interval: int = 5
    extra_device_code_params: dict[str, str] = {}
    extra_token_params: dict[str, str] = {}
    rotate_refresh_tokens: bool = True

    async def start(
        self,
        client_id: str,
        client_secret: str | None,
        scopes: list[str],
    ) -> FlowResult:
        params = {
            "client_id": client_id,
            "scope": " ".join(scopes),
            **self.extra_device_code_params,
        }
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as c:
                r = await c.post(self.device_code_url, data=params)
                r.raise_for_status()
                body = r.json()
        except Exception as e:
            logger.error("device_code start failed for %s: %s", self.provider_id, e)
            return FlowResult(status="error", error=str(e))

        interval = int(body.get("interval", self.polling_interval))
        expires_in = int(body.get("expires_in", 600))
        ticket = FlowTicket(
            provider_id=self.provider_id,
            flow_kind="device_code",
            data={"device_code": body["device_code"]},
            user_code=body.get("user_code"),
            verification_uri=body.get("verification_uri"),
            verification_uri_complete=body.get("verification_uri_complete"),
            interval=interval,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )
        return FlowResult(status="needs_input", ticket=ticket)

    async def poll(
        self,
        client_id: str,
        client_secret: str | None,
        ticket: FlowTicket,
    ) -> FlowResult:
        if ticket.expires_at and datetime.now(timezone.utc) >= ticket.expires_at:
            return FlowResult(status="expired", error="device code expired")

        params = {
            "client_id": client_id,
            "device_code": ticket.data["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            **self.extra_token_params,
        }
        if client_secret:
            params["client_secret"] = client_secret

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as c:
                r = await c.post(self.token_url, data=params)
                body = r.json()
        except Exception as e:
            logger.error("device_code poll failed for %s: %s", self.provider_id, e)
            return FlowResult(status="error", error=str(e))

        if "error" in body:
            err = body["error"]
            if err == "authorization_pending":
                return FlowResult(status="pending", ticket=ticket)
            if err == "slow_down":
                new_ticket = ticket.model_copy(update={"interval": ticket.interval + 5})
                return FlowResult(status="slow_down", ticket=new_ticket)
            if err == "expired_token":
                return FlowResult(status="expired", error="device code expired")
            if err == "access_denied":
                return FlowResult(status="denied", error="user denied access")
            return FlowResult(status="error", error=err)

        tokens = _tokens_from_response(body, default_scopes=ticket.data.get("scopes", []))
        return FlowResult(status="complete", tokens=tokens)

    async def refresh(
        self,
        client_id: str,
        client_secret: str | None,
        refresh_token: str,
    ) -> TokenSet:
        params = {
            "client_id": client_id,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            **self.extra_token_params,
        }
        if client_secret:
            params["client_secret"] = client_secret

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as c:
            r = await c.post(self.token_url, data=params)
            r.raise_for_status()
            body = r.json()

        if "error" in body:
            raise RuntimeError(f"refresh failed: {body['error']}")

        return _tokens_from_response(body, default_scopes=[])


def _tokens_from_response(body: dict, default_scopes: list[str]) -> TokenSet:
    expires_in = body.get("expires_in")
    expires_at = None
    if expires_in is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    scope_str = body.get("scope")
    scopes = scope_str.split() if scope_str else default_scopes
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=expires_at,
        scopes=scopes,
        token_type=body.get("token_type", "Bearer"),
        account_hint=None,
        issued_at=datetime.now(timezone.utc),
        extra={"id_token": body["id_token"]} if "id_token" in body else {},
    )
