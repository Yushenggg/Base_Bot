from pathlib import Path

from core.auth import store


def auth_secret_paths() -> list[str]:
    base = store.token_dir().resolve()
    return [str(base)]


def is_auth_secret_path(path: Path) -> bool:
    base = store.token_dir().resolve()
    try:
        path = path.resolve()
    except OSError:
        return False
    if path == base:
        return True
    return base in path.parents
