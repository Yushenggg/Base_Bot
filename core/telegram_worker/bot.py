import asyncio
import importlib
import logging
import os
import sys

from telegram import BotCommand, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.config import app_config, WORKING_DIR
from core.core_agent import CoreAgent
from core.telegram_worker.auth import RoleResolver
from core.telegram_worker.handlers import BotHandlers

logger = logging.getLogger("BOT")


STATIC_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("edit", "Create or modify code in the workspace"),
    BotCommand("restart_bot", "Restart the bot process"),
]


async def _register_commands(application, bot_ref):
    await bot_ref._register_all_commands()


class TeleBaseBot:
    def __init__(self):
        self.agent = CoreAgent()
        self.auth = RoleResolver()
        self.handlers = BotHandlers(self.agent, self.auth, reload_callback=self.reload)
        self.application = (
            ApplicationBuilder()
            .token(app_config.telegram_token)
            .concurrent_updates(True)
            .post_init(lambda app: _register_commands(app, self))
            .build()
        )
        self._loaded_handler_modules: set[str] = set()
        self._loaded_handler_commands: dict[str, list[BotCommand]] = {}
        self._setup()

    def _setup(self):
        self.application.add_handler(
            CommandHandler("start", self.handlers.handle_start),
        )
        self.application.add_handler(
            CommandHandler("edit", self.handlers.handle_edit),
        )
        self.application.add_handler(
            CommandHandler("restart_bot", self._handle_restart),
        )
        self.application.add_handler(
            MessageHandler(
                filters.ALL & ~filters.COMMAND,
                self.handlers.handle_message,
            ),
        )
        self._load_handler_files()

    def _load_handler_files(self):
        importlib.invalidate_caches()
        handlers_dir = WORKING_DIR / "handlers"
        if not handlers_dir.exists():
            return
        for f in sorted(handlers_dir.glob("*.py")):
            if f.name == "__init__.py":
                continue
            module_name = f"working.handlers.{f.stem}"
            try:
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)
                if hasattr(module, "register"):
                    module.register(self.application, {
                        "agent": self.agent,
                        "config": app_config,
                        "working_dir": WORKING_DIR,
                    })
                    self._loaded_handler_modules.add(module_name)
                    handler_commands = getattr(module, "commands", [])
                    if handler_commands:
                        self._loaded_handler_commands[module_name] = handler_commands
                    logger.info("Loaded handler module: %s", module_name)
                else:
                    logger.warning(
                        "Handler module %s has no register() function, skipping",
                        module_name,
                    )
            except Exception as e:
                logger.exception("Failed to load handler %s: %s", module_name, e)

    def reload(self):
        logger.info("Reloading bot components in-process")
        self._load_handler_files()
        self.agent.reload_standard_tools()
        logger.info("Reload complete — %d handler modules, %d tools",
                     len(self._loaded_handler_modules), len(self.agent.standard.tools))
        asyncio.create_task(self._register_all_commands())

    async def _register_all_commands(self):
        all_commands = list(STATIC_COMMANDS)
        for module_name, commands in self._loaded_handler_commands.items():
            all_commands.extend(commands)
        await self.application.bot.set_my_commands(all_commands)
        logger.info("Registered %d bot commands for auto-completion", len(all_commands))

    def run(self):
        logger.info("Starting TeleBaseBot")
        self.application.run_polling()

    async def _handle_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.auth.is_authorized(
            update.effective_user.id if update.effective_user else None,
        ):
            return
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id:
            await context.bot.send_message(chat_id=chat_id, text="🔄 Restarting bot...")
        logger.info("Manual restart via /restart_bot by user %s",
                     update.effective_user.id if update.effective_user else "unknown")
        os.execv(sys.executable, [sys.executable] + sys.argv)
