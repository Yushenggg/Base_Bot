import logging
import subprocess
import sys
import time
from pathlib import Path

BOT_MODULE = "core.main_telegram_bot"
PROJECT_ROOT = Path(__file__).resolve().parent

RESTART_DELAY_SECONDS = 3
MAX_RESTART_DELAY_SECONDS = 60

logging.basicConfig(
    format="%(asctime)s - WATCHDOG - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("WATCHDOG")


def main():
    logger.info("Watchdog started. Managing bot process.")
    delay = RESTART_DELAY_SECONDS
    while True:
        logger.info("Starting bot process...")
        proc = subprocess.run(
            [sys.executable, "-m", BOT_MODULE],
            cwd=PROJECT_ROOT,
        )
        if proc.returncode == 0:
            logger.info("Bot exited cleanly (code 0). Restarting in %ds.", delay)
            delay = RESTART_DELAY_SECONDS
        else:
            logger.warning(
                "Bot process exited with code %d. Restarting in %ds.",
                proc.returncode,
                delay,
            )
        time.sleep(delay)
        delay = min(delay * 2, MAX_RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    main()
