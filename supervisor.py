# supervisor.py

import subprocess
import sys
import time
import logging
from pathlib import Path

from utils.logger import setup_logging
setup_logging("supervisor")
logger = logging.getLogger(__name__)


def get_worker_command():
    logger.info("Determining worker command")

    exe = Path(sys.executable)

    if exe.name.endswith(".exe"):
        return [str(exe), "--worker"]
    else:
        return [str(exe), "main.py", "--worker"]


def run_supervisor():

    logger.info("Supervisor started")

    while True:

        logger.info("Launching worker process")

        worker = subprocess.Popen(get_worker_command())

        exit_code = worker.wait()

        logger.error(
            f"Worker exited unexpectedly (code={exit_code}). Restarting..."
        )

        time.sleep(3)
