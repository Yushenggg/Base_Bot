import logging
from datetime import datetime, timezone
from typing import Callable

from core.auth.flows.base import (
    FlowProvider,
    FlowResult,
    FlowTicket,
    TokenSet,
)

logger = logging.getLogger("AUTH.CUSTOM")


TokenExtractor = Callable[[str], TokenSet]


class CustomProvider(FlowProvider):
    prompt: str = "Paste your token:"
    extractor: TokenExtractor

    async def start(
        self,
        client_id: str,
        client_secret: str | None,
        scopes: list[str],
    ) -> FlowResult:
        ticket = FlowTicket(
            provider_id=self.provider_id,
            flow_kind="custom",
            expires_at=datetime.now(timezone.utc).replace(year=9999),
        )
        return FlowResult(status="needs_input", ticket=ticket, prompt=self.prompt)

    async def complete(
        self,
        ticket: FlowTicket,
        user_input: str,
    ) -> TokenSet:
        try:
            tokens = self.extractor(user_input)
        except Exception as e:
            logger.error("custom extractor failed for %s: %s", self.provider_id, e)
            raise RuntimeError(f"extractor failed: {e}") from e
        if tokens.issued_at is None:
            tokens = tokens.model_copy(update={"issued_at": datetime.now(timezone.utc)})
        return tokens

    async def poll(
        self,
        client_id: str,
        client_secret: str | None,
        ticket: FlowTicket,
    ) -> FlowResult:
        return FlowResult(status="pending", ticket=ticket)

    async def refresh(
        self,
        client_id: str,
        client_secret: str | None,
        refresh_token: str,
    ) -> TokenSet:
        raise RuntimeError(
            f"provider {self.provider_id!r} does not support refresh; re-supply the token"
        )
