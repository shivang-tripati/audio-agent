import logging
import sys
import os
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler


def get_log_dir() -> Path:
    """
    Use PROGRAMDATA env var instead of hardcoded path.
    Consistent with ConfigManager — same base directory.
    On standard Windows: C:\\ProgramData\\AudioAgent\\logs
    On enterprise machines where PROGRAMDATA is redirected: still correct.
    """
    program_data = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
    return Path(program_data) / "AudioAgent" / "logs"


def setup_logging(process_name: str = "agent"):

    log_dir = get_log_dir() / process_name
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"{process_name}.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(processName)s | %(name)s | %(levelname)s | %(message)s"
    )

    # File handler — rotates daily, keeps 14 days
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8"
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler — only in dev (not in packaged exe)
    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger