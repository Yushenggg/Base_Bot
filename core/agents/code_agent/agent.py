import logging
from pathlib import Path
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from core.agents import extract_agent_reply, verify_working_code
from core.agents.logging_handler import ToolLoggingHandler
from core.agents.tools import read_workspace_file_tool, resolve_workspace_path
from core.config import WORKING_DIR

logger = logging.getLogger("CODE_AGENT")
_tool_logger = ToolLoggingHandler()

SYSTEM_PROMPT = (
    "You are the code-generation component of a self-evolving Telegram bot. "
    "A requirements planner has already refined the user's request into a clear spec. "
    "Your only job: write the code. Do NOT ask questions, suggest alternatives, "
    "or seek clarification — the spec is final. Just implement it.\n\n"

    "You write Python code for a Telegram bot. The core infrastructure in /core/ is "
    "immutable — you only create or modify files in /working/.\n\n"

    "KINDS OF ARTIFACTS:\n"
    "1. Tools in working/tools/ — @tool decorated functions\n"
    "2. Handlers in working/handlers/ — files exporting register(app, deps)\n\n"

    "KNOWN CONTEXT:\n"
    "- Language: Python 3.12+\n"
    "- Library: python-telegram-bot v20+ (async)\n"
    "- The Application is ALREADY built and running. Never create a new Application "
    "or call ApplicationBuilder.\n"
    "- Handler interface:\n"
    "  def register(application, deps) -> None:\n"
    "      application.add_handler(CommandHandler('mycommand', callback))\n"
    "- Tool interface: @tool decorated functions (from langchain_core.tools import tool)\n"
    "- Always read existing files in /working/ first to understand current structure "
    "before creating new ones.\n\n"

    "CRITICAL RULES:\n"
    "- Do NOT write boilerplate (ApplicationBuilder, run_polling, main(), etc.)\n"
    "- Do NOT ask questions, request clarification, or propose alternatives\n"
    "- If the spec is unambiguous, implement it exactly as described\n"
    "- If a minor detail is missing, make a reasonable assumption and proceed\n"
    "- After writing all files, you are done — your code will be automatically verified\n"
    "- Only report what you built, not what you thought about building\n\n"
    "MESSAGE FORMATTING: When your handler sends text to the user, always use this "
    "safe pattern:\n"
    "  text = str(result)\n"
    "  for fmt in ('Markdown', None):\n"
    "      try:\n"
    "          await update.message.reply_text(text, parse_mode=fmt)\n"
    "          break\n"
    "      except Exception:\n"
    "          continue\n"
    "  else:\n"
    "      await update.message.reply_text(text[:4000])\n"
    "This tries Markdown, falls back to plain text, and if both fail "
    "(e.g. message too long) sends a truncated version. Telegram's message "
    "limit is 4096 characters. Never use pipe tables (|) — unsupported."
)

MAX_VERIFY_ATTEMPTS = 3


class _CodeState(TypedDict):
    messages: Annotated[list, add_messages]
    verify_attempts: int
    verify_error: str | None


def _build_graph(llm, system_prompt, tools, work_dir):
    tool_node = ToolNode(tools)

    def agent_node(state: _CodeState) -> dict:
        msgs = [SystemMessage(content=system_prompt)] + state["messages"]
        if tools:
            bound = llm.bind_tools(tools)
            response = bound.invoke(msgs)
        else:
            response = llm.invoke(msgs)
        return {"messages": [response]}

    def verify_node(state: _CodeState) -> dict:
        error = verify_working_code(work_dir)
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
    graph.add_conditional_edges("agent", route_agent, {"tools": "tools", "verify": "verify"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("verify", route_verify, {"agent": "agent", "end": END})
    return graph.compile()


class CodeAgent:
    def __init__(self, llm, work_dir: Path = WORKING_DIR):
        self.llm = llm
        self.work_dir = work_dir
        self.tools = [read_workspace_file_tool, write_workspace_file_tool]
        self.agent = _build_graph(llm, SYSTEM_PROMPT, self.tools, work_dir)

    async def ainvoke(self, instruction: str, messages: list[dict]) -> str:
        full = messages + [{"role": "user", "content": instruction}]
        logger.info(
            "Invoking with instruction: %.200s | history: %d msgs",
            instruction,
            len(messages),
        )
        result = await self.agent.ainvoke(
            {"messages": full, "verify_attempts": 0, "verify_error": None},
            config={"callbacks": [_tool_logger]},
        )
        verify_err = result.get("verify_error")
        reply = extract_agent_reply(result)
        logger.info(
            "Response: %.200s | verify_attempts=%d | verify_error=%s",
            reply,
            result.get("verify_attempts", 0),
            verify_err,
        )
        return reply


@tool
def write_workspace_file_tool(file_path: str, content: str) -> str:
    """Write content to a file in the workspace. Path must be within /working/."""
    abs_path = resolve_workspace_path(file_path)
    logger.info("write_tool path=%s resolved=%s (%d bytes)", file_path, abs_path, len(content))
    if not str(abs_path).startswith(str(WORKING_DIR)):
        logger.warning("write_tool DENIED — outside working dir: %s", abs_path)
        return "Error: Access denied. Path must be within /working/."
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    rel = abs_path.relative_to(WORKING_DIR.parent)
    logger.info("write_tool OK — %d bytes to %s", len(content), rel)
    return f"Successfully wrote {len(content)} bytes to {rel}"
