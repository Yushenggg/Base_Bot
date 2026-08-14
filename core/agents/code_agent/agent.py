import asyncio
import logging
from dataclasses import dataclass
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
MAX_STEPS = 40
STEP_WARNING_THRESHOLD = 6
MAX_RUN_RETRIES = 2
RETRY_DELAY_SECONDS = 2.0


@dataclass
class CodeResult:
    reply: str
    capped: bool
    failed: bool
    history: list


class _CodeState(TypedDict):
    messages: Annotated[list, add_messages]
    verify_attempts: int
    verify_error: str | None
    steps: int
    capped: bool


def _build_graph(llm, system_prompt, tools, work_dir):
    tool_node = ToolNode(tools)

    def agent_node(state: _CodeState) -> dict:
        steps = state.get("steps", 0) + 1
        msgs = [SystemMessage(content=system_prompt)] + state["messages"]
        remaining = MAX_STEPS - steps
        if remaining <= STEP_WARNING_THRESHOLD:
            msgs.append(HumanMessage(
                content=(
                    f"Step budget: {remaining} agent turns left. Stop testing and "
                    "exploration. Finish any remaining code now, then reply with "
                    "a brief summary of what you built."
                )
            ))
        if tools:
            bound = llm.bind_tools(tools)
            response = bound.invoke(msgs)
        else:
            response = llm.invoke(msgs)
        return {"messages": [response], "steps": steps}

    def finalize_node(state: _CodeState) -> dict:
        msgs = [SystemMessage(content=system_prompt)] + state["messages"]
        msgs.append(HumanMessage(
            content=(
                "You have reached the step limit. Do not call any tools. Produce "
                "your final message with exactly these two sections:\n"
                "Things done:\n- <what you implemented, which files you wrote>\n"
                "Things left:\n- <what still needs to be done to complete the spec>"
            )
        ))
        response = llm.invoke(msgs)
        return {"messages": [response], "capped": True}

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
                return "finalize"
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
    graph.add_node("finalize", finalize_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent", route_agent,
        {"tools": "tools", "verify": "verify", "finalize": "finalize"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
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

    def _make_state(self, messages: list) -> dict:
        return {
            "messages": messages,
            "verify_attempts": 0,
            "verify_error": None,
            "steps": 0,
            "capped": False,
        }

    async def ainvoke(self, instruction: str, messages: list[dict]) -> CodeResult:
        reset_read_tracking()
        full = messages + [
            {"role": "user", "content": f"Implement this spec:\n\n{instruction}"}
        ]
        logger.info(
            "Invoking with instruction: %.200s | history: %d msgs",
            instruction,
            len(messages),
        )
        code_result = await self._run_with_retry(self._make_state(full))
        logger.info(
            "Response: %.200s | capped=%s | failed=%s | history=%d msgs",
            code_result.reply,
            code_result.capped,
            code_result.failed,
            len(code_result.history),
        )
        return code_result

    async def ainvoke_continue(self, history: list, instruction: str) -> CodeResult:
        reset_read_tracking()
        full = list(history) + [HumanMessage(content=instruction)]
        logger.info("Continuing with %d history msgs", len(history))
        code_result = await self._run_with_retry(self._make_state(full))
        logger.info(
            "Continue response: %.200s | capped=%s | failed=%s | history=%d msgs",
            code_result.reply,
            code_result.capped,
            code_result.failed,
            len(code_result.history),
        )
        return code_result

    async def _run_with_retry(self, state: dict) -> CodeResult:
        last: dict = state
        for attempt in range(MAX_RUN_RETRIES + 1):
            resume = dict(state)
            if attempt > 0:
                resume = {
                    "messages": list(last.get("messages", state.get("messages", []))),
                    "verify_attempts": last.get("verify_attempts", 0),
                    "verify_error": None,
                    "steps": last.get("steps", state.get("steps", 0)),
                    "capped": last.get("capped", False),
                }
            collected: dict = {}
            try:
                async for chunk in self.agent.astream(
                    resume,
                    stream_mode="values",
                    config={"callbacks": [_tool_logger]},
                ):
                    collected = chunk
                return self._to_code_result(collected)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(
                    "CodeAgent run failed (attempt %d/%d)",
                    attempt + 1,
                    MAX_RUN_RETRIES + 1,
                )
                last = collected or resume
                if attempt >= MAX_RUN_RETRIES:
                    return CodeResult(
                        reply=(
                            f"The coding agent hit an error after "
                            f"{MAX_RUN_RETRIES + 1} attempts: {e}"
                        ),
                        capped=False,
                        failed=True,
                        history=list(last.get("messages", [])),
                    )
                await asyncio.sleep(RETRY_DELAY_SECONDS * (attempt + 1))
        return CodeResult(reply="", capped=False, failed=True, history=[])

    @staticmethod
    def _to_code_result(result: dict) -> CodeResult:
        return CodeResult(
            reply=extract_agent_reply(result),
            capped=bool(result.get("capped")),
            failed=False,
            history=list(result.get("messages", [])),
        )
