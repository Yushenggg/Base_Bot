import logging

from langchain_openai import ChatOpenAI

from core.agents.code_agent.agent import CodeAgent
from core.agents.plan_agent.agent import PlanAgent
from core.agents.standard_agent.agent import StandardAgent
from core.config import app_config

logger = logging.getLogger("CORE_AGENT")


class CoreAgent:
    def __init__(self):
        logger.info("Initializing CoreAgent (model=%s)", app_config.default_model)
        self.llm = ChatOpenAI(
            model=app_config.default_model,
            openai_api_key=app_config.openai_api_key,
            openai_api_base=app_config.openai_base_url_for_client,
        )
        self.standard = StandardAgent(self.llm)
        self.planner = PlanAgent(self.llm)
        self.code = CodeAgent(self.llm)
        logger.info("CoreAgent ready — %d standard tools loaded", len(self.standard.tools))

    async def ainvoke_standard(self, messages: list[dict]) -> str:
        logger.debug("→ standard (%d messages)", len(messages))
        return await self.standard.ainvoke(messages)

    async def ainvoke_planner(self, messages: list[dict]) -> str:
        logger.debug("→ planner (%d messages)", len(messages))
        return await self.planner.ainvoke(messages)

    async def ainvoke_code(self, instruction: str, messages: list[dict]) -> str:
        logger.debug("→ code (%d messages, instruction=%.80s)", len(messages), instruction)
        return await self.code.ainvoke(instruction, messages)
