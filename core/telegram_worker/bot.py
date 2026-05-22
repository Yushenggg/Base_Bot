import importlib
import logging

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from core.config import app_config, WORKING_DIR
from core.core_agent import CoreAgent
from core.telegram_worker.auth import RoleResolver
from core.telegram_worker.handlers import BotHandlers

logger = logging.getLogger("BOT")


class TeleBaseBot:
    def __init__(self):
        self.agent = CoreAgent()
        self.auth = RoleResolver()
        self.handlers = BotHandlers(self.agent, self.auth)
        self.application = (
            ApplicationBuilder()
            .token(app_config.telegram_token)
            .concurrent_updates(True)
            .build()
        )
        self._setup()

    def _setup(self):
        self.application.add_handler(
            CommandHandler("start", self.handlers.handle_start),
        )
        self.application.add_handler(
            CommandHandler("edit", self.handlers.handle_edit),
        )
        self.application.add_handler(
            MessageHandler(
                filters.ALL & ~filters.COMMAND,
                self.handlers.handle_message,
            ),
        )
        self._load_handler_files()

    def _load_handler_files(self):
        handlers_dir = WORKING_DIR / "handlers"
        if not handlers_dir.exists():
            return
        for f in sorted(handlers_dir.glob("*.py")):
            if f.name == "__init__.py":
                continue
            module_name = f"working.handlers.{f.stem}"
            try:
                module = importlib.import_module(module_name)
                importlib.reload(module)
                if hasattr(module, "register"):
                    module.register(self.application, {
                        "agent": self.agent,
                        "config": app_config,
                        "working_dir": WORKING_DIR,
                    })
                    logger.info("Loaded handler module: %s", module_name)
                else:
                    logger.warning(
                        "Handler module %s has no register() function, skipping",
                        module_name,
                    )
            except Exception as e:
                logger.exception("Failed to load handler %s: %s", module_name, e)

    def run(self):
        logger.info("Starting TeleBaseBot")
        self.application.run_polling()
