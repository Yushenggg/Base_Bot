import logging
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import tool

from core.config import WORKING_DIR

logger = logging.getLogger("CODE_AGENT")

SYSTEM_PROMPT = (
    "You are an Autonomous Systems Engineer. "
    "You write Python code for a Telegram bot. "
    "You can create two kinds of artifacts:\n"
    "1. Tools in working/tools/ — @tool decorated functions\n"
    "2. Handlers in working/handlers/ — files exporting register(app, deps)\n\n"
    "Always validate your code before finishing."
)


class CodeAgent:
    def __init__(self, llm):
        self.llm = llm
        self.agent = create_agent(
            model=self.llm,
            system_prompt=SYSTEM_PROMPT,
            tools=[read_workspace_file_tool, write_workspace_file_tool],
        )

    async def ainvoke(self, instruction: str, messages: list[dict]) -> str:
        full = messages + [{"role": "user", "content": instruction}]
        result = await self.agent.ainvoke({"messages": full})
        return self._extract_reply(result)

    @staticmethod
    def _extract_reply(result: dict) -> str:
        msgs = result.get("messages", [])
        if msgs:
            return str(msgs[-1].content)
        return str(result)


@tool
def read_workspace_file_tool(file_path: str) -> str:
    """Read a file from the workspace. Path must be within /working/."""
    abs_path = Path(file_path).resolve()
    if not str(abs_path).startswith(str(WORKING_DIR)):
        return "Error: Access denied. Path must be within /working/."
    if not abs_path.exists():
        return f"Error: File not found: {file_path}"
    return abs_path.read_text(encoding="utf-8")


@tool
def write_workspace_file_tool(file_path: str, content: str) -> str:
    """Write content to a file in the workspace. Path must be within /working/."""
    abs_path = Path(file_path).resolve()
    if not str(abs_path).startswith(str(WORKING_DIR)):
        return "Error: Access denied. Path must be within /working/."
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} bytes to {abs_path.relative_to(WORKING_DIR.parent)}"
