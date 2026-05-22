import logging

from langchain.agents import create_agent
from langchain_core.tools import tool

from core.agents.logging_handler import ToolLoggingHandler
from core.agents.tools import read_workspace_file_tool, resolve_workspace_path
from core.config import WORKING_DIR

logger = logging.getLogger("CODE_AGENT")
_tool_logger = ToolLoggingHandler()

SYSTEM_PROMPT = (
    "SYSTEM IDENTITY: You are the code-generation component of a self-evolving Telegram bot. "
    "The bot can extend itself at runtime by creating new tools, handlers, and subagents. "
    "The core infrastructure in /core/ is immutable — you only write files to /working/.\n\n"

    "You are an Autonomous Systems Engineer. "
    "You write Python code for a Telegram bot. "
    "You can create two kinds of artifacts:\n"
    "1. Tools in working/tools/ — @tool decorated functions\n"
    "2. Handlers in working/handlers/ — files exporting register(app, deps)\n\n"

    "KNOWN CONTEXT:\n"
    "- Language: Python 3.12+\n"
    "- Library: python-telegram-bot v20+ (async)\n"
    "- The Application is ALREADY built and running in core/. Never create a new Application or call ApplicationBuilder.\n"
    "- Your handler's register(application, deps) receives the existing running Application. "
    "Only call application.add_handler(...) inside register().\n"
    "- Handler interface:\n"
    "  def register(application, deps) -> None:\n"
    "      application.add_handler(CommandHandler('mycommand', callback))\n"
    "- Tool interface: @tool decorated functions (from langchain_core.tools import tool)\n"
    "- Always read existing files in /working/ first to understand current structure "
    "before creating new ones.\n\n"

    "CRITICAL: Do NOT write boilerplate for setting up a Telegram bot (ApplicationBuilder, "
    "run_polling, main() blocks, etc.). The infrastructure already exists. "
    "Only write the handler/tool logic and the register() function."
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
    abs_path = resolve_workspace_path(file_path)
    logger.info("write_tool path=%s resolved=%s (%d bytes)", file_path, abs_path, len(content))
    if not str(abs_path).startswith(str(WORKING_DIR)):
        logger.warning("write_tool DENIED — outside working dir: %s", abs_path)
        return "Error: Access denied. Path must be within /working/."
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    rel = abs_path.relative_to(WORKING_DIR.parent)
    logger.info("write_tool OK — %d bytes to %s", len(content), rel)
    return f"Successfully wrote {len(content)} bytes to {rel}"
