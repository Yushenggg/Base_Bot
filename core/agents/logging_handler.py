import logging

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger("AGENT_TOOLS")


class ToolLoggingHandler(BaseCallbackHandler):
    def on_tool_start(
        self,
        serialized: dict,
        input_str: str,
        **kwargs,
    ) -> None:
        name = serialized.get("name", "unknown")
        logger.info("Tool called: %s | input: %s", name, str(input_str)[:400])

    def on_tool_end(self, output: str, **kwargs) -> None:
        logger.info("Tool returned: %s", str(output)[:500])

    def on_tool_error(self, error: Exception, **kwargs) -> None:
        logger.error("Tool error: %s", error)
