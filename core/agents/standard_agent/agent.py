import importlib
import logging

from langchain.agents import create_agent
from langchain_core.tools import BaseTool

from core.agents.logging_handler import ToolLoggingHandler
from core.config import WORKING_DIR

logger = logging.getLogger("STANDARD_AGENT")
_tool_logger = ToolLoggingHandler()

SYSTEM_PROMPT = (
    "You are a helpful AI assistant running on Telegram. "
    "Give concise, accurate answers. "
    "You have access to tools to help you answer questions.\n\n"
    "IMPORTANT: If someone asks you to write, edit, or modify code for the bot, "
    "tell them to use the /edit command instead. You cannot modify code yourself."
)


class StandardAgent:
    def __init__(self, llm):
        self.llm = llm
        self.tools = self._discover_tools()
        self.agent = create_agent(
            model=self.llm,
            system_prompt=SYSTEM_PROMPT,
            tools=self.tools,
        )

    def _discover_tools(self) -> list:
        tools = []

        tools_dir = WORKING_DIR / "tools"
        if tools_dir.exists():
            for f in sorted(tools_dir.glob("*.py")):
                if f.name == "__init__.py":
                    continue
                try:
                    module = importlib.import_module(f"working.tools.{f.stem}")
                    importlib.reload(module)
                    for attr in dir(module):
                        obj = getattr(module, attr)
                        if isinstance(obj, BaseTool):
                            tools.append(obj)
                except Exception as e:
                    logger.warning("Failed to load tool %s: %s", f.stem, e)

        subagents_dir = WORKING_DIR / "subagents"
        if subagents_dir.exists():
            for f in sorted(subagents_dir.glob("*.py")):
                if f.name == "__init__.py":
                    continue
                try:
                    module = importlib.import_module(f"working.subagents.{f.stem}")
                    importlib.reload(module)
                    if hasattr(module, "create_tool"):
                        tool = module.create_tool(self.llm)
                        tools.append(tool)
                        logger.info("Loaded subagent tool: %s", tool.name)
                except Exception as e:
                    logger.warning("Failed to load subagent %s: %s", f.stem, e)

        return tools

    async def ainvoke(self, messages: list[dict]) -> str:
        logger.info(
            "Invoking with %d messages, last: %.100s",
            len(messages),
            messages[-1].get("content", "") if messages else "",
        )
        result = await self.agent.ainvoke(
            {"messages": messages},
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
