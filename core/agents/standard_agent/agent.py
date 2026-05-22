import importlib
import logging

from langchain.agents import create_agent
from langchain_core.tools import BaseTool

from core.config import WORKING_DIR

logger = logging.getLogger("STANDARD_AGENT")

SYSTEM_PROMPT = (
    "You are a helpful AI assistant running on Telegram. "
    "Give concise, accurate answers. "
    "You have access to tools to help you answer questions."
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
        if not tools_dir.exists():
            return tools
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
        return tools

    async def ainvoke(self, messages: list[dict]) -> str:
        result = await self.agent.ainvoke({"messages": messages})
        return self._extract_reply(result)

    @staticmethod
    def _extract_reply(result: dict) -> str:
        msgs = result.get("messages", [])
        if msgs:
            return str(msgs[-1].content)
        return str(result)
