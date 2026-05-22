import logging

from core.config import app_config
from core.telegram_worker.bot import TeleBaseBot

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, app_config.log_level.upper(), logging.INFO),
)
logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    bot = TeleBaseBot()
    bot.run()


if __name__ == "__main__":
    main()
