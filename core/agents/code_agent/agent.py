import logging
from pathlib import Path
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from core.agents import extract_agent_reply, verify_working_code
from core.agents.code_agent.prompts import build_system_prompt
from core.agents.code_agent.tools import (
    bash_tool,
    edit_file_tool,
    glob_tool,
    grep_tool,
    read_file_tool,
    reset_read_tracking,
    todowrite_tool,
    write_workspace_file_tool,
)
from core.agents.logging_handler import ToolLoggingHandler
from core.config import WORKING_DIR
from core.dependency_sync import sync_dependencies

logger = logging.getLogger("CODE_AGENT")
_tool_logger = ToolLoggingHandler()

MAX_VERIFY_ATTEMPTS = 3
MAX_STEPS = 30


class _CodeState(TypedDict):
    messages: Annotated[list, add_messages]
    verify_attempts: int
    verify_error: str | None
    steps: int


def _build_graph(llm, system_prompt, tools, work_dir):
    tool_node = ToolNode(tools)

    def agent_node(state: _CodeState) -> dict:
        msgs = [SystemMessage(content=system_prompt)] + state["messages"]
        if tools:
            bound = llm.bind_tools(tools)
            response = bound.invoke(msgs)
        else:
            response = llm.invoke(msgs)
        return {"messages": [response], "steps": state.get("steps", 0) + 1}

    async def verify_node(state: _CodeState) -> dict:
        sync = await sync_dependencies()
        sync_error = f"Dependency sync failed: {sync.error}" if sync.error else None

        error = verify_working_code(work_dir)
        if error is None:
            error = sync_error
        elif sync_error:
            error = f"{sync_error}\n{error}"

        attempts = state.get("verify_attempts", 0)

        if error:
            new_attempts = attempts + 1
            if new_attempts >= MAX_VERIFY_ATTEMPTS:
                return {
                    "verify_attempts": new_attempts,
                    "verify_error": error,
                }
            return {
                "messages": [HumanMessage(
                    content=(
                        f"Verification failed (attempt {new_attempts}/{MAX_VERIFY_ATTEMPTS}): {error}\n\n"
                        f"Fix the issues in your code files and try again."
                    )
                )],
                "verify_attempts": new_attempts,
                "verify_error": error,
            }
        return {"verify_error": None}

    def route_agent(state: _CodeState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            if state.get("steps", 0) >= MAX_STEPS:
                return "end"
            return "tools"
        return "verify"

    def route_verify(state: _CodeState) -> str:
        error = state.get("verify_error")
        if error is None:
            return "end"
        if state.get("verify_attempts", 0) >= MAX_VERIFY_ATTEMPTS:
            return "end"
        return "agent"

    graph = StateGraph(_CodeState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("verify", verify_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_agent, {"tools": "tools", "verify": "verify", "end": END})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("verify", route_verify, {"agent": "agent", "end": END})
    return graph.compile()


class CodeAgent:
    def __init__(self, llm, work_dir: Path = WORKING_DIR):
        self.llm = llm
        self.work_dir = work_dir
        self.tools = [
            read_file_tool,
            write_workspace_file_tool,
            edit_file_tool,
            glob_tool,
            grep_tool,
            bash_tool,
            todowrite_tool,
        ]
        model_name = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        system_prompt = build_system_prompt(model_name)
        self.agent = _build_graph(llm, system_prompt, self.tools, work_dir)

    async def ainvoke(self, instruction: str, messages: list[dict]) -> str:
        reset_read_tracking()
        full = messages + [
            {"role": "user", "content": f"Implement this spec:\n\n{instruction}"}
        ]
        logger.info(
            "Invoking with instruction: %.200s | history: %d msgs",
            instruction,
            len(messages),
        )
        result = await self.agent.ainvoke(
            {
                "messages": full,
                "verify_attempts": 0,
                "verify_error": None,
                "steps": 0,
            },
            config={"callbacks": [_tool_logger]},
        )
        verify_err = result.get("verify_error")
        reply = extract_agent_reply(result)
        logger.info(
            "Response: %.200s | verify_attempts=%d | steps=%d | verify_error=%s",
            reply,
            result.get("verify_attempts", 0),
            result.get("steps", 0),
            verify_err,
        )
        return reply
