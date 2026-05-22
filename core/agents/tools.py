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
