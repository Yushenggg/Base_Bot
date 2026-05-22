import logging

from langchain.agents import create_agent

from core.agents.logging_handler import ToolLoggingHandler
from core.agents.tools import read_workspace_file_tool

logger = logging.getLogger("PLAN_AGENT")
_tool_logger = ToolLoggingHandler()

SYSTEM_PROMPT = (
    "You are a requirements planner for a coding agent. "
    "The user wants to modify a Telegram bot by adding new tools or handlers. "
    "Ask clarifying questions to refine their request. "
    "When the requirements are clear, summarize them and ask for confirmation. "
    "Do NOT write any code yourself.\n\n"

    "KNOWN CONTEXT (do NOT ask about these):\n"
    "- Language: Python 3.12+\n"
    "- Library: python-telegram-bot v20+ (async)\n"
    "- Handlers live in: working/handlers/<name>.py\n"
    "  └─ Each file must export: def register(application, deps) -> None\n"
    "- Tools live in: working/tools/<name>.py\n"
    "  └─ Each file contains @tool decorated functions\n"
    "- You have read_workspace_file_tool — use it to inspect existing code "
    "in /working/ before planning so you understand the current structure."
)


class PlanAgent:
    def __init__(self, llm):
        self.llm = llm
        self.agent = create_agent(
            model=self.llm,
            system_prompt=SYSTEM_PROMPT,
            tools=[read_workspace_file_tool],
        )

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
