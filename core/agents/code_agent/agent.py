import logging
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import tool

from core.agents.logging_handler import ToolLoggingHandler
from core.agents.tools import read_workspace_file_tool
from core.config import WORKING_DIR

logger = logging.getLogger("CODE_AGENT")
_tool_logger = ToolLoggingHandler()

SYSTEM_PROMPT = (
    "You are an Autonomous Systems Engineer. "
    "You write Python code for a Telegram bot. "
    "You can create two kinds of artifacts:\n"
    "1. Tools in working/tools/ — @tool decorated functions\n"
    "2. Handlers in working/handlers/ — files exporting register(app, deps)\n\n"
    "KNOWN CONTEXT:\n"
    "- Language: Python 3.12+\n"
    "- Library: python-telegram-bot v20+ (async)\n"
    "- Handler interface: def register(application, deps) -> None\n"
    "- Tool interface: @tool decorated functions (from langchain_core.tools import tool)\n\n"
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
        logger.info(
            "Invoking with instruction: %.200s | history: %d msgs",
            instruction,
            len(messages),
        )
        result = await self.agent.ainvoke(
            {"messages": full},
            config={"callbacks": [_tool_logger]},
        )
        reply = self._extract_reply(result)
        logger.info("Response: %.200s", reply)
        return reply

    @staticmethod
    def _extract_reply(result: dict) -> str:
        msgs = result.get("messages", [])
        if msgs:
            return str(msgs[-1].content)
        return str(result)


@tool
def write_workspace_file_tool(file_path: str, content: str) -> str:
    """Write content to a file in the workspace. Path must be within /working/."""
    abs_path = Path(file_path).resolve()
    logger.info("write_tool path=%s resolved=%s (%d bytes)", file_path, abs_path, len(content))
    if not str(abs_path).startswith(str(WORKING_DIR)):
        logger.warning("write_tool DENIED — outside working dir: %s", abs_path)
        return "Error: Access denied. Path must be within /working/."
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    rel = abs_path.relative_to(WORKING_DIR.parent)
    logger.info("write_tool OK — %d bytes to %s", len(content), rel)
    return f"Successfully wrote {len(content)} bytes to {rel}"
