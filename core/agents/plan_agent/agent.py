import logging

from langchain.agents import create_agent

logger = logging.getLogger("PLAN_AGENT")

SYSTEM_PROMPT = (
    "You are a requirements planner for a coding agent. "
    "The user wants to modify a Telegram bot by adding new tools or handlers. "
    "Ask clarifying questions to refine their request. "
    "When the requirements are clear, summarize them and ask for confirmation. "
    "Do NOT write any code yourself."
)


class PlanAgent:
    def __init__(self, llm):
        self.llm = llm
        self.agent = create_agent(
            model=self.llm,
            system_prompt=SYSTEM_PROMPT,
        )

    async def ainvoke(self, messages: list[dict]) -> str:
        result = await self.agent.ainvoke({"messages": messages})
        return self._extract_reply(result)

    @staticmethod
    def _extract_reply(result: dict) -> str:
        msgs = result.get("messages", [])
        if msgs:
            return str(msgs[-1].content)
        return str(result)
