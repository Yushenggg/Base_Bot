import logging
import subprocess
import sys
from pathlib import Path

BOT_MODULE = "core.main_telegram_bot"
PROJECT_ROOT = Path(__file__).resolve().parent

logging.basicConfig(
    format="%(asctime)s - WATCHDOG - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("WATCHDOG")


def main():
    logger.info("Watchdog started. Managing bot process.")
    while True:
        logger.info("Starting bot process...")
        proc = subprocess.run(
            [sys.executable, "-m", BOT_MODULE],
            cwd=PROJECT_ROOT,
        )
        logger.info(
            "Bot process exited (return code %d). Restarting.",
            proc.returncode,
        )


if __name__ == "__main__":
    main()
