import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

BASE_DIR = Path("C:/ProgramData/AudioAgent")
LOG_DIR = BASE_DIR / "logs"


def setup_logging(process_name="agent"):

    process_dir = LOG_DIR / process_name
    process_dir.mkdir(parents=True, exist_ok=True)

    log_file = process_dir / f"{process_name}.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s"
    )

    handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",      # rotate daily
        interval=1,
        backupCount=14,       # keep 14 days
        encoding="utf-8"
    )

    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # console logging in development
    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    return logger
