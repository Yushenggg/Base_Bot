from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FlowKind = Literal["device_code", "auth_code_pkce", "custom"]


class FlowTicket(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider_id: str
    flow_kind: FlowKind
    data: dict[str, Any] = Field(default_factory=dict)
    user_code: str | None = None
    verification_uri: str | None = None
    verification_uri_complete: str | None = None
    auth_url: str | None = None
    interval: int = 5
    expires_at: datetime | None = None


class TokenSet(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    token_type: str = "Bearer"
    account_hint: str | None = None
    issued_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AccessToken(BaseModel):
    access_token: str
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    account_hint: str | None = None


FlowStatus = Literal[
    "pending",
    "slow_down",
    "complete",
    "expired",
    "denied",
    "error",
    "needs_input",
]


class FlowResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: FlowStatus
    tokens: TokenSet | None = None
    ticket: FlowTicket | None = None
    error: str | None = None
    prompt: str | None = None


class FlowProvider(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    display_name: str
    client_id_env: str
    client_secret_env: str | None = None
    scopes_default: list[str] = Field(default_factory=list)
    scopes_supported: list[str] = Field(default_factory=list)
    setup_instructions: str = ""
    setup_urls: list[tuple[str, str]] = Field(default_factory=list)
    revoke_url: str | None = None

    @property
    def flow_kind(self) -> FlowKind:
        cls_name = type(self).__name__
        if cls_name == "DeviceCodeProvider":
            return "device_code"
        if cls_name == "AuthCodePkceProvider":
            return "auth_code_pkce"
        if cls_name == "CustomProvider":
            return "custom"
        raise ValueError(f"unknown flow provider class: {cls_name}")

    async def start(
        self,
        client_id: str,
        client_secret: str | None,
        scopes: list[str],
    ) -> FlowResult:
        raise NotImplementedError

    async def poll(
        self,
        client_id: str,
        client_secret: str | None,
        ticket: FlowTicket,
    ) -> FlowResult:
        raise NotImplementedError

    async def refresh(
        self,
        client_id: str,
        client_secret: str | None,
        refresh_token: str,
    ) -> TokenSet:
        raise NotImplementedError

    async def revoke(
        self,
        client_id: str,
        client_secret: str | None,
        token: str,
    ) -> None:
        if not self.revoke_url:
            return
        return None


class ProviderInfo(BaseModel):
    provider_id: str
    display_name: str
    flow_kind: FlowKind
    scopes_default: list[str]
    scopes_supported: list[str]
    setup_urls: list[tuple[str, str]]
    setup_instructions: str
    has_client_creds: bool
    logged_in: bool


class ProviderStatus(BaseModel):
    provider_id: str
    display_name: str
    has_client_creds: bool
    client_creds_source: Literal["env", "encrypted", "none"]
    logged_in: bool
    account_hint: str | None = None
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
