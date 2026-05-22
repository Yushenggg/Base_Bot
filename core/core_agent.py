import logging

from langchain_openai import ChatOpenAI

from core.agents.code_agent.agent import CodeAgent
from core.agents.plan_agent.agent import PlanAgent
from core.agents.standard_agent.agent import StandardAgent
from core.config import app_config

logger = logging.getLogger("CORE_AGENT")


class CoreAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=app_config.default_model,
            openai_api_key=app_config.openai_api_key,
            openai_api_base=app_config.openai_base_url_for_client,
        )
        self.standard = StandardAgent(self.llm)
        self.planner = PlanAgent(self.llm)
        self.code = CodeAgent(self.llm)

    async def ainvoke_standard(self, messages: list[dict]) -> str:
        return await self.standard.ainvoke(messages)

    async def ainvoke_planner(self, messages: list[dict]) -> str:
        return await self.planner.ainvoke(messages)

    async def ainvoke_code(self, instruction: str, messages: list[dict]) -> str:
        return await self.code.ainvoke(instruction, messages)
