import logging

from langchain.agents import create_agent

from core.agents.logging_handler import ToolLoggingHandler
from core.agents.tools import duckduckgo_search_tool, read_site_tool, read_workspace_file_tool

logger = logging.getLogger("PLAN_AGENT")
_tool_logger = ToolLoggingHandler()

SYSTEM_PROMPT = (
    "SYSTEM IDENTITY: This is a self-evolving Telegram bot. Users extend it by describing "
    "what they want, and a code-generation agent writes the implementation. "
    "Your job is to refine the user's request into a clear specification. "
    "The core infrastructure in /core/ is immutable — all new code goes into /working/.\n\n"

    "You are a requirements planner for a coding agent. "
    "The user wants to modify a Telegram bot by adding new tools or handlers. "
    "Ask clarifying questions to refine their request. "
    "When the requirements are clear, summarize them and ask for confirmation. "
    "Do NOT write any code yourself.\n\n"

    "KNOWN CONTEXT (do NOT ask about these):\n"
    "- Language: Python 3.12+\n"
    "- Library: python-telegram-bot v20+ (async)\n"
    "- The Application is ALREADY built and running. register() receives the existing app.\n"
    "- Handlers live in: working/handlers/<name>.py\n"
    "  └─ Each file must export: def register(application, deps) -> None\n"
    "  └─ register only calls application.add_handler(...) — never creates a new app\n"
    "- Tools live in: working/tools/<name>.py\n"
    "  └─ Each file contains @tool decorated functions\n"
    "- Subagents live in: working/subagents/<name>.py\n"
    "  └─ Each file must export: def create_tool(llm) -> BaseTool\n"
    "  └─ create_tool receives a ChatOpenAI instance, creates its own agent, "
    "and returns a @tool that wraps it\n"
    "- Tools:\n"
    "  - read_workspace_file_tool — inspect existing code in /working/\n"
    "  - duckduckgo_search_tool — search the web for additional context\n"
    "  - read_site_tool — fetch and read the content of a specific URL\n"
    "CRITICAL: The bot infrastructure (Application, run_polling, main) already exists in /core/. "
    "Do NOT plan to recreate it. Only plan handler/tool/subagent files that extend it."
)


class PlanAgent:
    def __init__(self, llm):
        self.llm = llm
        self.agent = create_agent(
            model=self.llm,
            system_prompt=SYSTEM_PROMPT,
            tools=[read_workspace_file_tool, duckduckgo_search_tool, read_site_tool],
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
