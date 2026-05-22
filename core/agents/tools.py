import logging
from pathlib import Path

from langchain_core.tools import tool

from core.config import WORKING_DIR

logger = logging.getLogger("FILE_TOOLS")


@tool
def read_workspace_file_tool(file_path: str) -> str:
    """Read a file from the workspace. Path must be within /working/."""
    abs_path = Path(file_path).resolve()
    logger.info("read_tool path=%s resolved=%s", file_path, abs_path)
    if not str(abs_path).startswith(str(WORKING_DIR)):
        logger.warning("read_tool DENIED — outside working dir: %s", abs_path)
        return "Error: Access denied. Path must be within /working/."
    if not abs_path.exists():
        logger.warning("read_tool NOT FOUND: %s", abs_path)
        return f"Error: File not found: {file_path}"
    content = abs_path.read_text(encoding="utf-8")
    logger.info("read_tool OK — %d bytes from %s", len(content), abs_path)
    return content


@tool
def duckduckgo_search_tool(query: str) -> str:
    """Search the web using DuckDuckGo. Returns a summary of results."""
    from duckduckgo_search import DDGS

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
