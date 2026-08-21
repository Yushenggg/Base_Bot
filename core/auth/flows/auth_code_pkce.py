import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from core.auth.flows.base import (
    FlowProvider,
    FlowResult,
    FlowTicket,
    TokenSet,
)

logger = logging.getLogger("AUTH.AUTH_CODE_PKCE")

DEFAULT_TIMEOUT = 15.0


class AuthCodePkceProvider(FlowProvider):
    auth_url: str
    token_url: str
    redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob"
    extra_auth_params: dict[str, str] = {}
    extra_token_params: dict[str, str] = {}

    async def start(
        self,
        client_id: str,
        client_secret: str | None,
        scopes: list[str],
    ) -> FlowResult:
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **self.extra_auth_params,
        }
        from urllib.parse import urlencode

        url = f"{self.auth_url}?{urlencode(params)}"
        ticket = FlowTicket(
            provider_id=self.provider_id,
            flow_kind="auth_code_pkce",
            data={"code_verifier": verifier, "state": state},
            auth_url=url,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        return FlowResult(status="needs_input", ticket=ticket)

    async def poll(
        self,
        client_id: str,
        client_secret: str | None,
        ticket: FlowTicket,
    ) -> FlowResult:
        return FlowResult(status="pending", ticket=ticket)

    async def exchange(
        self,
        client_id: str,
        client_secret: str | None,
        ticket: FlowTicket,
        authorization_code: str,
    ) -> TokenSet:
        params = {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": ticket.data["code_verifier"],
            **self.extra_token_params,
        }
        if client_secret:
            params["client_secret"] = client_secret
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as c:
            r = await c.post(self.token_url, data=params)
            body = r.json()
        if "error" in body:
            raise RuntimeError(f"token exchange failed: {body['error']}")
        return _tokens_from_response(body)

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
        return _tokens_from_response(body)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _tokens_from_response(body: dict) -> TokenSet:
    expires_in = body.get("expires_in")
    expires_at = None
    if expires_in is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    scope_str = body.get("scope")
    scopes = scope_str.split() if scope_str else []
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
