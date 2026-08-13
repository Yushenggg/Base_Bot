import logging
import re
import subprocess
import tempfile
from pathlib import Path

from langchain_core.tools import tool

from core.agents.tools import PROJECT_ROOT, _is_secret_path, resolve_workspace_path
from core.config import WORKING_DIR

logger = logging.getLogger("CODE_AGENT_TOOLS")

MAX_OUTPUT_LINES = 2000
MAX_OUTPUT_BYTES = 51200
DEFAULT_TIMEOUT_MS = 120_000

_IGNORED_DIRS = {".git", ".venv", "__pycache__", "node_modules", "backup"}

_read_files: set[str] = set()


def reset_read_tracking() -> None:
    _read_files.clear()


def _mark_read(path: Path) -> None:
    _read_files.add(str(path))


def _was_read(path: Path) -> bool:
    return str(path) in _read_files


def _contained_in_working(path: Path) -> bool:
    work_dir = WORKING_DIR.resolve()
    return path == work_dir or work_dir in path.parents


def _read_text_with_numbers(abs_path: Path, offset: int, limit: int) -> str:
    content = abs_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    total = len(lines)
    if offset < 1:
        offset = 1
    start = offset - 1
    end = start + limit
    numbered = [f"{i}: {lines[i - 1]}" for i in range(start + 1, min(end, total) + 1)]
    out = "\n".join(numbered)
    if end < total:
        out += f"\n(File continues after line {min(end, total)} — use a larger offset to read more)"
    return out


@tool
def read_file_tool(file_path: str, offset: int = 1, limit: int = 2000) -> str:
    """Read a file or directory from the local filesystem. If the path does not exist, an error is returned.

Usage:
- The filePath parameter should be an absolute path, or a path relative to the project root.
- By default, this tool returns up to 2000 lines from the start of the file.
- The offset parameter is the line number to start from (1-indexed).
- To read later sections, call this tool again with a larger offset.
- Use the grep tool to find specific content in large files or files with long lines.
- If you are unsure of the correct file path, use the glob tool to look up filenames by glob pattern.
- Contents are returned with each line prefixed by its line number as `<line>: <content>`.
- Any line longer than 2000 characters is truncated.
- Call this tool in parallel when you know there are multiple files you want to read.
- Avoid tiny repeated slices (30 line chunks). If you need more context, read a larger window."""
    abs_path = resolve_workspace_path(file_path)
    if _is_secret_path(abs_path):
        logger.warning("read_tool DENIED secret path: %s", abs_path)
        return "Error: Access denied to this path."
    if not abs_path.exists():
        return f"Error: File not found: {file_path}"
    if abs_path.is_dir():
        items = sorted(p.relative_to(abs_path).as_posix() for p in abs_path.iterdir())
        listing = "\n".join(items) if items else "(empty)"
        return f"Contents of {abs_path}:\n{listing}"
    _mark_read(abs_path)
    content = _read_text_with_numbers(abs_path, offset, limit)
    logger.info("read_tool OK — %s (offset=%d limit=%d)", abs_path, offset, limit)
    return content


@tool
def edit_file_tool(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Performs exact string replacements in files.

Usage:
- You must use your Read tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: line number + colon + space (e.g., `1: `). Everything after that space is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not found in the file with an error "old_string not found in content".
- The edit will FAIL if `old_string` is found multiple times in the file with an error "Found multiple matches for old_string. Provide more surrounding lines in old_string to identify the correct match." Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."""
    abs_path = resolve_workspace_path(file_path).resolve()
    if not _contained_in_working(abs_path):
        logger.warning("edit_tool DENIED — outside working dir: %s", abs_path)
        return "Error: Access denied. Path must be within /working/."
    if not _was_read(abs_path):
        return "Error: You must read the file with the read tool before editing it."
    if not abs_path.exists():
        return f"Error: File not found: {file_path}"
    content = abs_path.read_text(encoding="utf-8")
    count = content.count(old_string)
    if count == 0:
        return "Error: old_string not found in content."
    if count > 1 and not replace_all:
        return (
            "Error: Found multiple matches for old_string. Provide more surrounding "
            "lines in old_string to identify the correct match, or set replace_all=True."
        )
    new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
    abs_path.write_text(new_content, encoding="utf-8")
    rel = abs_path.relative_to(WORKING_DIR.parent)
    logger.info("edit_tool OK — %d replacement(s) in %s", count if replace_all else 1, rel)
    return f"Successfully edited {rel} ({count if replace_all else 1} replacement(s))."


@tool
def write_workspace_file_tool(file_path: str, content: str) -> str:
    """Writes a file to the local filesystem.

Usage:
- This tool will overwrite the existing file if there is one at the provided path.
- If this is an existing file, you MUST use the Read tool first to read the file's contents. This tool will fail if you did not read the file first.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked.

Path must be within /working/."""
    abs_path = resolve_workspace_path(file_path).resolve()
    if not _contained_in_working(abs_path):
        logger.warning("write_tool DENIED — outside working dir: %s", abs_path)
        return "Error: Access denied. Path must be within /working/."
    if abs_path.exists() and not _was_read(abs_path):
        return "Error: You must read the file with the read tool before overwriting it."
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    rel = abs_path.relative_to(WORKING_DIR.parent)
    logger.info("write_tool OK — %d bytes to %s", len(content), rel)
    return f"Successfully wrote {len(content)} bytes to {rel}"


@tool
def glob_tool(pattern: str) -> str:
    """- Fast file pattern matching tool that works with any codebase size
- Supports glob patterns like "**/*.js" or "src/**/*.ts"
- Returns matching file paths
- Use this tool when you need to find files by name patterns
- When you are doing an open-ended search that may require multiple rounds of globbing and grepping, prefer batching several searches together.
- You have the capability to call multiple tools in a single response. It is always better to speculatively perform multiple searches as a batch that are potentially useful."""
    matches = []
    for p in PROJECT_ROOT.glob(pattern):
        if p.is_dir():
            continue
        if any(part in _IGNORED_DIRS for part in p.parts):
            continue
        matches.append(p.relative_to(PROJECT_ROOT).as_posix())
    matches = sorted(set(matches))
    if not matches:
        return "No files found."
    return "\n".join(matches)


@tool
def grep_tool(pattern: str, path: str = ".", include: str | None = None) -> str:
    """- Fast content search tool that works with any codebase size
- Searches file contents using regular expressions
- Supports full regex syntax (eg. "log.*Error", "function\\s+\\w+", etc.)
- Filter files by pattern with the include parameter (eg. "*.js", "*.{ts,tsx}")
- Returns file paths and line numbers with matching lines
- Use this tool when you need to find files containing specific patterns
- If you need to identify/count the number of matches within files, use the Bash tool with `rg` (ripgrep) directly. Do NOT use `grep`."""
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    base = resolve_workspace_path(path)
    if base.is_file():
        files = [base]
    else:
        files = [p for p in base.rglob("*") if p.is_file()]

    include_re = None
    if include:
        include_re = re.compile(_glob_to_regex(include))

    results: list[str] = []
    for f in files:
        if any(part in _IGNORED_DIRS for part in f.parts):
            continue
        if _is_secret_path(f):
            continue
        if include_re and not include_re.search(f.as_posix()):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rel = f.relative_to(PROJECT_ROOT).as_posix()
                results.append(f"{rel}:{lineno}: {line}")
                if len(results) >= 500:
                    results.append("(truncated — more than 500 matches)")
                    return "\n".join(results)
    if not results:
        return "No matches found."
    return "\n".join(results)


@tool
def bash_tool(command: str, timeout: int | None = None, workdir: str | None = None) -> str:
    """Executes a given bash command in a persistent shell session with optional timeout, ensuring proper handling and security measures.

Be aware: OS: linux, Shell: bash

All commands run in /working/ by default. Use the `workdir` parameter if you need to run a command in a different directory inside /working/. AVOID using `cd <directory> && <command>` patterns - use `workdir` instead.

IMPORTANT: This tool is for terminal operations. DO NOT use it for file operations (reading, writing, editing, searching, finding files) - use the specialized tools for this instead.

Before executing the command, please follow these steps:

1. Directory Verification:
   - If the command will create new directories or files, first use `ls` to verify the parent directory exists and is the correct location

2. Command Execution:
   - Always quote file paths that contain spaces with double quotes
   - After ensuring proper quoting, execute the command.
   - Capture the output of the command.

Usage notes:
  - The command argument is required.
  - You can specify an optional timeout in milliseconds. If not specified, commands will time out after 120000ms.
  - If the output exceeds 2000 lines or 51200 bytes, it will be truncated and the full output will be written to a file. You can use Read with offset/limit to read specific sections or Grep to search the full content. Do NOT use `head`, `tail`, or other truncation commands to limit output.

  - Avoid using Bash with the `find`, `grep`, `cat`, `head`, `tail`, `sed`, `awk`, or `echo` commands, unless explicitly instructed or when these commands are truly necessary for the task. Instead, always prefer using the dedicated tools for these commands:
    - File search: Use Glob (NOT find or ls)
    - Content search: Use Grep (NOT grep or rg)
    - Read files: Use Read (NOT cat/head/tail)
    - Edit files: Use Edit (NOT sed/awk)
    - Write files: Use Write (NOT echo >/cat <<EOF)
    - Communication: Output text directly (NOT echo/printf)
  - When issuing multiple commands:
    - If the commands are independent and can run in parallel, make multiple bash tool calls in a single message.
    - If the commands depend on each other and must run sequentially, use a single Bash call with '&&' to chain them together.
    - Use ';' only when you need to run commands sequentially but don't care if earlier commands fail
    - DO NOT use newlines to separate commands (newlines are ok in quoted strings)
  - AVOID using `cd <directory> && <command>`. Use the `workdir` parameter to change directories instead.

Security: commands run with their working directory pinned to /working/. Any workdir that resolves outside /working/ is rejected."""
    cwd = WORKING_DIR.resolve()
    if workdir:
        target = resolve_workspace_path(workdir).resolve()
        if not _contained_in_working(target):
            logger.warning("bash_tool DENIED workdir outside /working/: %s", target)
            return "Error: Access denied. workdir must be within /working/."
        if not target.is_dir():
            return f"Error: workdir not found: {workdir}"
        cwd = target

    timeout_s = (timeout if timeout is not None else DEFAULT_TIMEOUT_MS) / 1000.0
    logger.info("bash_tool cwd=%s cmd=%.300s", cwd, command)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        return f"Error: command timed out after {timeout_s:.0f}s."
    except Exception as e:
        return f"Error: failed to run command: {e}"

    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    if not output:
        output = "(no output)"

    truncated = len(output.encode("utf-8")) > MAX_OUTPUT_BYTES or output.count("\n") > MAX_OUTPUT_LINES
    if truncated:
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="bash_output_", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(output)
            out_path = tmp.name
        lines = output.splitlines()
        tail = "\n".join(lines[-MAX_OUTPUT_LINES:])[-MAX_OUTPUT_BYTES:]
        output = f"...output truncated...\n\nFull output saved to: {out_path}\n\n{tail}"

    if proc.returncode != 0:
        output += f"\n\n(exit code {proc.returncode})"
    logger.info("bash_tool done — exit=%d len=%d", proc.returncode, len(output))
    return output


@tool
def todowrite_tool(todos: list) -> str:
    """Create and maintain a structured task list for the current coding session. Tracks progress, organizes multi-step work, and surfaces status to the user.

When to use: proactively when the task requires 3+ distinct steps, the work is non-trivial and benefits from planning, or the user provides multiple tasks. Skip for single straightforward tasks or purely informational requests.

States: pending, in_progress, completed, cancelled. Keep exactly one in_progress while work remains; mark completed only after the work is actually done.

Provide the todos as a list of objects with fields: content (description), status (one of pending/in_progress/completed/cancelled), and priority (high/medium/low)."""
    if not isinstance(todos, list):
        return "Error: todos must be a list."
    counts = {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0}
    for item in todos:
        status = item.get("status") if isinstance(item, dict) else None
        if status in counts:
            counts[status] += 1
    logger.info("todowrite_tool — %s", counts)
    return (
        f"Todo list updated: {len(todos)} item(s) — "
        f"{counts['pending']} pending, {counts['in_progress']} in progress, "
        f"{counts['completed']} completed, {counts['cancelled']} cancelled."
    )


def _glob_to_regex(glob_pattern: str) -> str:
    parts = []
    i = 0
    while i < len(glob_pattern):
        c = glob_pattern[i]
        if c == "*":
            if i + 1 < len(glob_pattern) and glob_pattern[i + 1] == "*":
                parts.append(".*")
                i += 1
            else:
                parts.append("[^/]*")
        elif c == "?":
            parts.append("[^/]")
        elif c in ".^$+()[]{}\\|":
            parts.append("\\" + c)
        elif c == "/":
            parts.append("/")
        else:
            parts.append(c)
        i += 1
    return "".join(parts)
