import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core.auth.flows.base import TokenSet
from core.config import DATA_DIR

logger = logging.getLogger("AUTH.STORE")

_FERNET_KEY_ENV = "AUTH_ENCRYPTION_KEY"
_DEFAULT_TOKEN_DIR = DATA_DIR / "auth"
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_fernet: Fernet | None = None
_token_dir: Path = _DEFAULT_TOKEN_DIR


def init() -> None:
    global _fernet, _token_dir
    _token_dir = _DEFAULT_TOKEN_DIR
    _token_dir.mkdir(parents=True, exist_ok=True)
    _fernet = _load_or_create_fernet()


def _load_or_create_fernet() -> Fernet:
    key = os.environ.get(_FERNET_KEY_ENV)
    if key:
        try:
            return Fernet(key.encode())
        except Exception as e:
            raise RuntimeError(
                f"invalid {_FERNET_KEY_ENV} in environment: {e}"
            ) from e
    key = Fernet.generate_key().decode()
    _persist_env_var(_FERNET_KEY_ENV, key)
    logger.warning(
        "Generated %s and wrote it to .env. Back up .env — losing it invalidates "
        "all stored auth tokens (you will have to re-login to every provider).",
        _FERNET_KEY_ENV,
    )
    return Fernet(key.encode())


def _persist_env_var(name: str, value: str) -> None:
    env_path = Path(".env")
    line = f"{name}={value}\n"
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        if re.search(rf"^{re.escape(name)}=", text, re.MULTILINE):
            return
        if text and not text.endswith("\n"):
            text += "\n"
        text += line
    else:
        text = line
    env_path.write_text(text, encoding="utf-8")


def _validate_provider_id(provider_id: str) -> None:
    if not _PROVIDER_ID_PATTERN.match(provider_id):
        raise ValueError(f"invalid provider_id: {provider_id!r}")


def _client_creds_path(provider_id: str) -> Path:
    _validate_provider_id(provider_id)
    return _token_dir / f"{provider_id}.client.json.enc"


def _tokens_path(provider_id: str) -> Path:
    _validate_provider_id(provider_id)
    return _token_dir / f"{provider_id}.json.enc"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _encrypt(obj: dict) -> bytes:
    if _fernet is None:
        raise RuntimeError("auth store not initialized; call auth.init() first")
    raw = json.dumps(obj, default=_json_default).encode("utf-8")
    return _fernet.encrypt(raw)


def _decrypt(data: bytes) -> dict:
    if _fernet is None:
        raise RuntimeError("auth store not initialized; call auth.init() first")
    raw = _fernet.decrypt(data)
    return json.loads(raw.decode("utf-8"))


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def _parse_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


def load_client_creds_env_or_encrypted(
    provider_id: str,
    client_id_env: str,
    client_secret_env: str | None,
) -> tuple[str, str] | None:
    cid = os.environ.get(client_id_env)
    sec = os.environ.get(client_secret_env) if client_secret_env else None
    if cid and (sec is not None or not client_secret_env):
        return cid, sec or ""
    encrypted = _load_encrypted_client_creds(provider_id)
    if encrypted:
        return encrypted["client_id"], encrypted.get("client_secret", "")
    return None


def _load_encrypted_client_creds(provider_id: str) -> dict | None:
    path = _client_creds_path(provider_id)
    if not path.exists():
        return None
    try:
        return _decrypt(path.read_bytes())
    except InvalidToken:
        logger.error(
            "failed to decrypt client creds for %s; AUTH_ENCRYPTION_KEY may have changed",
            provider_id,
        )
        return None
    except Exception as e:
        logger.error("failed to read client creds for %s: %s", provider_id, e)
        return None


def save_client_creds(provider_id: str, client_id: str, client_secret: str | None) -> None:
    obj = {"client_id": client_id, "client_secret": client_secret or ""}
    _atomic_write(_client_creds_path(provider_id), _encrypt(obj))
    logger.info("saved client creds for %s", provider_id)


def has_encrypted_client_creds(provider_id: str) -> bool:
    return _client_creds_path(provider_id).exists()


def load_tokens(provider_id: str) -> TokenSet | None:
    path = _tokens_path(provider_id)
    if not path.exists():
        return None
    try:
        obj = _decrypt(path.read_bytes())
    except InvalidToken:
        logger.error(
            "failed to decrypt tokens for %s; AUTH_ENCRYPTION_KEY may have changed",
            provider_id,
        )
        return None
    except Exception as e:
        logger.error("failed to read tokens for %s: %s", provider_id, e)
        return None
    return TokenSet(
        access_token=obj["access_token"],
        refresh_token=obj.get("refresh_token"),
        expires_at=_parse_datetime(obj.get("expires_at")),
        scopes=obj.get("scopes", []),
        token_type=obj.get("token_type", "Bearer"),
        account_hint=obj.get("account_hint"),
        issued_at=_parse_datetime(obj.get("issued_at")),
        extra=obj.get("extra", {}),
    )


def save_tokens(provider_id: str, tokens: TokenSet) -> None:
    obj = tokens.model_dump(mode="json")
    _atomic_write(_tokens_path(provider_id), _encrypt(obj))
    logger.info("saved tokens for %s", provider_id)


def delete_tokens(provider_id: str) -> None:
    path = _tokens_path(provider_id)
    if path.exists():
        path.unlink()
    logger.info("deleted tokens for %s", provider_id)


def has_tokens(provider_id: str) -> bool:
    return _tokens_path(provider_id).exists()


def token_dir() -> Path:
    return _token_dir
