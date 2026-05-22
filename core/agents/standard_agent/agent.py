import importlib
import logging
import sys
from typing import Annotated

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from core.agents import extract_agent_reply
from core.agents.logging_handler import ToolLoggingHandler
from core.config import WORKING_DIR

logger = logging.getLogger("STANDARD_AGENT")
_tool_logger = ToolLoggingHandler()

SYSTEM_PROMPT = (
    "You are a helpful AI assistant running on Telegram. "
    "Give concise, accurate answers. "
    "You have access to tools to help you answer questions.\n\n"
    "TOOL USAGE: Proactively use available tools. For factual claims, use the "
    "fact_check tool if available. For recent or unknown information, use search. "
    "Do NOT wait for the user to explicitly ask you to use a tool.\n\n"
    "FORMATTING: Output plain text or Telegram Markdown. "
    "Do NOT use pipe tables (|) — Telegram does not support them. "
    "Prefer bullet lists. When presenting URLs, put them on their own line — "
    "do NOT wrap them in markdown links.\n\n"
    "IMPORTANT: If someone asks you to write, edit, or modify code for the bot, "
    "tell them to use the /edit command instead. You cannot modify code yourself."
)


class _GraphState(TypedDict):
    messages: Annotated[list, add_messages]


class StandardAgent:
    def __init__(self, llm):
        self.llm = llm
        self._subagent_tool_names: set[str] = set()
        self.tools = self._discover_tools()
        self._rebuild_agent()

    def _rebuild_agent(self):
        subagent_names = self._subagent_tool_names
        all_tools = self.tools

        tool_node = ToolNode(all_tools)

        def agent_node(state: _GraphState) -> dict:
            msgs = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
            if all_tools:
                bound = self.llm.bind_tools(all_tools)
                response = bound.invoke(msgs)
            else:
                response = self.llm.invoke(msgs)
            return {"messages": [response]}

        def route_agent(state: _GraphState) -> str:
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return "end"

        def route_tools(state: _GraphState) -> str:
            last_msg = state["messages"][-1]
            if isinstance(last_msg, ToolMessage) and last_msg.name in subagent_names:
                return "subagent_response"
            return "agent"

        def subagent_response_node(state: _GraphState) -> dict:
            last_tool = state["messages"][-1]
            return {"messages": [AIMessage(content=str(last_tool.content))]}

        graph = StateGraph(_GraphState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)
        graph.add_node("subagent_response", subagent_response_node)
        graph.set_entry_point("agent")
        graph.add_conditional_edges("agent", route_agent, {"tools": "tools", "end": END})
        graph.add_conditional_edges("tools", route_tools, {"agent": "agent", "subagent_response": "subagent_response"})
        graph.add_edge("subagent_response", END)

        self.agent = graph.compile()

    def _discover_tools(self) -> list:
        importlib.invalidate_caches()
        tools = []
        self._subagent_tool_names = set()

        tools_dir = WORKING_DIR / "tools"
        if tools_dir.exists():
            for f in sorted(tools_dir.glob("*.py")):
                if f.name == "__init__.py":
                    continue
                module_name = f"working.tools.{f.stem}"
                try:
                    if module_name in sys.modules:
                        module = importlib.reload(sys.modules[module_name])
                    else:
                        module = importlib.import_module(module_name)
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
                module_name = f"working.subagents.{f.stem}"
                try:
                    if module_name in sys.modules:
                        module = importlib.reload(sys.modules[module_name])
                    else:
                        module = importlib.import_module(module_name)
                    if hasattr(module, "create_tool"):
                        tool = module.create_tool(self.llm)
                        tools.append(tool)
                        self._subagent_tool_names.add(tool.name)
                        logger.info("Loaded subagent tool: %s", tool.name)
                except Exception as e:
                    logger.warning("Failed to load subagent %s: %s", f.stem, e)

        return tools

    def reload_tools(self):
        self.tools = self._discover_tools()
        self._rebuild_agent()
        logger.info("Tools reloaded — %d total (%d subagents)",
                     len(self.tools), len(self._subagent_tool_names))

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
        reply = extract_agent_reply(result)
        logger.info("Response: %.200s", reply)
        return reply
