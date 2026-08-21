# Auth providers

This document explains how to add a new OAuth/SSO provider to TeleBaseBot.
If you are an end user who wants to connect your account to a provider
(e.g. log into your Google account so the bot can read your calendar),
see `docs/user-auth.md` instead.

## How providers work

TeleBaseBot's auth engine lives in `core/auth/` and is immutable. It supports
three flow types:

| Flow | When to use | Library support |
|---|---|---|
| `DeviceCodeProvider` | Provider supports RFC 8628 Device Authorization Grant | Google, Microsoft, GitHub, GitLab, most modern IdPs |
| `AuthCodePkceProvider` | Provider supports standard OAuth but no device code | Older IdPs, generic OIDC |
| `CustomProvider` | Provider uses internal tokens, API keys, or a non-standard flow | Notion, many SaaS APIs |

Providers are config-only registrations. They live in `core/auth/providers/`
and are imported by `core/auth/providers/__init__.py`. Adding a provider
means adding one file — no engine changes.

## Adding a new provider (Device Code example)

```bash
# 1. Create the file
touch core/auth/providers/<provider_id>.py
```

```python
# core/auth/providers/<provider_id>.py
from core.auth import register_provider
from core.auth.flows import DeviceCodeProvider

register_provider(
    DeviceCodeProvider(
        provider_id="myprovider",                  # must match the filename
        display_name="My Provider",                # shown to users
        client_id_env="MYPROVIDER_CLIENT_ID",      # .env var for OAuth app id
        client_secret_env="MYPROVIDER_CLIENT_SECRET",
        device_code_url="https://myprovider.com/oauth/device/code",
        token_url="https://myprovider.com/oauth/token",
        scopes_default=["read"],                   # requested on first login
        scopes_supported=["read", "write"],        # whitelist of grantable scopes
        extra_device_code_params={"audience": "https://api.myprovider.com"},
        rotate_refresh_tokens=True,                # use new refresh_token on each refresh
        setup_urls=[
            ("Developer console", "https://myprovider.com/developers"),
        ],
        setup_instructions=(
            "1. Open the developer console.\n"
            "2. Create a new OAuth application.\n"
            "3. Copy the Client ID and Client Secret into .env."
        ),
        revoke_url="https://myprovider.com/oauth/revoke",
    )
)
```

```python
# core/auth/providers/__init__.py — add the import
from core.auth.providers import google  # noqa: F401
from core.auth.providers import myprovider  # noqa: F401
```

Then add the env vars to `.env.example`:

```dotenv
# My Provider (https://myprovider.com/developers)
MYPROVIDER_CLIENT_ID=
MYPROVIDER_CLIENT_SECRET=
```

Restart the bot: `/restart_bot`.

## Field reference

### `provider_id`

- Lowercase letters, digits, underscores, hyphens
- Matches the filename (`google.py` → `"google"`)
- Used as the key everywhere — encrypted blob paths, env var lookups, registry
- Cannot be changed without losing existing tokens; pick carefully

### `client_id_env` / `client_secret_env`

- Names of env vars holding the OAuth app's client credentials
- Read at login time (live `os.environ`)
- `client_secret_env=None` for public clients (PKCE-only flows)
- These are checked FIRST; encrypted-store fallback only used when missing

### `scopes_default`

- Requested on the first login via `/login_<provider>` with no scope override
- Conservative — request what you actually need
- Can be widened later by re-logging in

### `scopes_supported`

- Whitelist the engine uses to detect `ScopeNotGrantedError`
- A user who logs in with scope X cannot call `get_credential(scopes=[Y])`
  for Y not in this list (nor in their stored scopes)
- Be generous here — include everything the user might legitimately want

### `extra_device_code_params`

- Provider-specific quirks merged into the device code request body
- Google needs `{"access_type": "offline", "prompt": "consent"}` to get a refresh token
- Auth0 needs `{"audience": "..."}` for API tokens
- Omit if unsure

### `rotate_refresh_tokens`

- If True and the provider returns a new refresh_token on refresh, swap it in
- Old refresh_token is invalidated by the provider on next use
- Recommended for Google, GitHub — they're known to support this
- Set False if the provider doesn't rotate

### `setup_urls` / `setup_instructions`

- Shown to the user when they try to log in without client creds
- Be specific: paste the exact URL with path, name the exact buttons to click
- Mention any "verify later" tricks for personal use (Google's External +
  Testing mode, for instance)

### `revoke_url`

- Called by `auth.logout()` if set, to revoke the user's grant server-side
- Optional — leaving it None just deletes local tokens

## Adding a Custom provider (Notion-style)

For providers that don't do OAuth at all:

```python
# core/auth/providers/notion.py
from core.auth import register_provider
from core.auth.flows.base import TokenSet
from core.auth.flows import CustomProvider

def _extract(raw_text: str) -> TokenSet:
    return TokenSet(
        access_token=raw_text.strip(),
        scopes=["*"],
    )

register_provider(
    CustomProvider(
        provider_id="notion",
        display_name="Notion",
        client_id_env="",        # no OAuth
        client_secret_env=None,
        scopes_default=["*"],
        scopes_supported=["*"],
        prompt=(
            "Paste your Notion internal integration token.\n"
            "Get one from https://www.notion.so/my-integrations"
        ),
        extractor=_extract,
    )
)
```

## Testing a new provider locally

```python
# tests are not yet part of the repo, but you can verify end-to-end:
from core import auth
auth.init()
import core.auth.providers  # trigger registrations

# 1. List shows your provider
assert "myprovider" in [p.provider_id for p in auth.list_providers()]

# 2. Start a login — should prompt for client creds (none configured yet)
import asyncio
flow = asyncio.run(auth.start_login("myprovider"))
assert flow.step == "needs_client_id"

# 3. (Optional) Simulate creds via env vars and re-run
import os
os.environ["MYPROVIDER_CLIENT_ID"] = "test"
os.environ["MYPROVIDER_CLIENT_SECRET"] = "test"
flow = asyncio.run(auth.start_login("myprovider"))
assert flow.step == "awaiting_user"
assert flow.user_code is not None
```

## Hot reload

Providers are static infrastructure — they are NOT hot-reloaded.
Adding a new provider requires `/restart_bot`.

`core/auth/providers/__init__.py` is imported once at startup by
`core/telegram_worker/bot.py`. To add a provider:

1. Drop the file in `core/auth/providers/`
2. Add the import line to `core/auth/providers/__init__.py`
3. Add the env vars to `.env.example` (and `.env` if you'll use them now)
4. `/restart_bot`

## Common pitfalls

- **Scopes URL-encoded incorrectly.** Most providers accept bare space-separated
  scopes in `scope=`. If you see "invalid_scope" errors, check the provider's
  docs — some want `+` or `%20`.
- **Missing refresh token on first login.** For Google, you must include
  `access_type=offline` in `extra_device_code_params`. Without it, Google
  returns only an access_token and the user has to re-auth every hour.
- **Clock skew.** OAuth tokens have `expires_in`; if your server's clock is
  way off, `get_credential` may try to use an expired token. Check `date`.
- **Tenant IDs for Microsoft.** Microsoft Entra needs `?tenant=common`
  (or your tenant ID) appended to the auth/token URLs, OR use the v2.0 endpoint
  with the tenant in the path: `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token`.

## Security model recap

- Client credentials (`client_id`, `client_secret`) live in `.env` (plaintext)
  by convention. For higher security, store them in a system keyring or
  Vault and load into env at startup.
- User tokens (`access_token`, `refresh_token`) are always Fernet-encrypted
  at `data/auth/{provider_id}.json.enc`. The Fernet key is in `.env`.
- An attacker needs both `data/auth/*.json.enc` files AND the Fernet key
  to decrypt. Two-file compromise beats single-file `.env`-only.
- The CodeAgent cannot read either (denylist covers `.env*` and `data/auth/`).
