import asyncio
import logging

from core.config import app_config
from core.dependency_sync import sync_dependencies
from core.telegram_worker.bot import TeleBaseBot

logger = logging.getLogger("MAIN")


def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, app_config.log_level.upper(), logging.INFO),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    sync_result = asyncio.run(sync_dependencies())
    if sync_result.error:
        logger.error(
            "Startup dependency sync FAILED — working deps may be missing: %s",
            sync_result.error,
        )
    elif sync_result.synced:
        logger.info(
            "Startup dependency sync applied: +%s -%s",
            sync_result.added,
            sync_result.removed or [],
        )
    else:
        logger.info("Startup dependency sync: up to date")

    bot = TeleBaseBot()
    bot.run()


if __name__ == "__main__":
    main()
