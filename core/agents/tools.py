import logging
from pathlib import Path

from langchain_core.tools import tool

from core.config import WORKING_DIR

logger = logging.getLogger("FILE_TOOLS")

PROJECT_ROOT = WORKING_DIR.parent


def resolve_workspace_path(file_path: str) -> Path:
    p = Path(file_path)
    parts = p.parts
    if len(parts) >= 2 and parts[0] == "/" and parts[1] == "working":
        return (PROJECT_ROOT / Path(*parts[1:])).resolve()
    if p.is_absolute():
        return p.resolve()
    return (PROJECT_ROOT / p).resolve()


_SECRET_PATH_PARTS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".netrc",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "id_ecdsa",
    "credentials",
)


def _is_secret_path(path: Path) -> bool:
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    lowered = str(path).lower()
    return any(marker in lowered for marker in _SECRET_PATH_PARTS)


@tool
def read_workspace_file_tool(file_path: str) -> str:
    """Read a file or list a directory on the filesystem. Denies access to secret files."""
    abs_path = resolve_workspace_path(file_path)
    if _is_secret_path(abs_path):
        logger.warning("read_tool DENIED secret path: %s", abs_path)
        return "Error: Access denied to this path."
    logger.info("read_tool path=%s resolved=%s", file_path, abs_path)
    if not abs_path.exists():
        logger.warning("read_tool NOT FOUND: %s", abs_path)
        return f"Error: File not found: {file_path}"
    if abs_path.is_dir():
        items = sorted(
            p.relative_to(abs_path).as_posix()
            for p in abs_path.iterdir()
        )
        listing = "\n".join(items) if items else "(empty)"
        logger.info("read_tool dir — %d entries in %s", len(items), abs_path)
        return f"Contents of {abs_path}:\n{listing}"
    content = abs_path.read_text(encoding="utf-8")
    logger.info("read_tool OK — %d bytes from %s", len(content), abs_path)
    return content


@tool
def duckduckgo_search_tool(query: str) -> str:
    """Search the web using DuckDuckGo. Returns a summary of results."""
    from ddgs import DDGS

    logger.info("search_tool query=%.200s", query)
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
    except Exception as e:
        logger.error("search_tool error: %s", e)
        return f"Search failed: {e}"

    if not results:
        logger.info("search_tool — no results")
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        lines.append(f"{i}. {title}\n   {body}\n   {href}")

    out = "\n\n".join(lines)
    logger.info("search_tool OK — %d results", len(results))
    return out


@tool
def read_site_tool(url: str) -> str:
    """Fetch the content of a URL and return it as plain text."""
    import httpx

    logger.info("site_tool url=%s", url)
    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logger.error("site_tool error: %s", e)
        return f"Failed to fetch {url}: {e}"

    content = resp.text[:8000]
    logger.info("site_tool OK — %d bytes from %s", len(content), url)
    return content
