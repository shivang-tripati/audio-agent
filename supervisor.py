"""
Supervisor — launches and monitors the worker process.
Runs inside the service. Restarts worker if it crashes.
"""

import subprocess
import sys
import time
import logging
import os
from pathlib import Path

from utils.logger import setup_logging
setup_logging("supervisor")
logger = logging.getLogger(__name__)


# --------------------------------------------------
# Resolve absolute path — critical for service mode
# --------------------------------------------------

def get_base_dir():
    """
    Returns the absolute directory where our exe / script lives.
    When running as a Windows service, CWD is C:\\Windows\\System32
    so we MUST use this instead of any relative path.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller compiled exe — use exe's own directory
        return Path(sys.executable).resolve().parent
    else:
        # Development — use the directory of THIS file
        return Path(__file__).resolve().parent


def get_worker_command():
    """
    Build the exact command to launch the worker subprocess.
    Always uses absolute paths.
    """
    base_dir = get_base_dir()

    if getattr(sys, 'frozen', False):
        # Compiled: same exe, different argument
        exe = Path(sys.executable).resolve()
        cmd = [str(exe), "--worker"]
        logger.info(f"Worker command (compiled): {cmd}")
        return cmd
    else:
        # Development: python interpreter + absolute path to main.py
        interpreter = Path(sys.executable).resolve()
        main_script = base_dir / "main.py"

        if not main_script.exists():
            logger.error(f"main.py not found at: {main_script}")
            raise FileNotFoundError(f"main.py not found at: {main_script}")

        cmd = [str(interpreter), str(main_script), "--worker"]
        logger.info(f"Worker command (dev): {cmd}")
        return cmd


# --------------------------------------------------
# Supervisor loop
# --------------------------------------------------

def run_supervisor():
    logger.info("Supervisor started")
    logger.info(f"Base dir: {get_base_dir()}")
    logger.info(f"CWD: {os.getcwd()}")  # log so you can see if it's System32

    # Set working directory to our app directory
    # This ensures any relative paths inside the worker resolve correctly
    app_dir = str(get_base_dir())
    os.chdir(app_dir)
    logger.info(f"CWD changed to: {os.getcwd()}")

    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 10

    while True:
        try:
            cmd = get_worker_command()
            logger.info(f"Launching worker: {cmd}")

            worker = subprocess.Popen(
                cmd,
                cwd=app_dir,              # explicit CWD for worker too
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            exit_code = worker.wait()

            if exit_code == 0:
                logger.info("Worker exited cleanly (code=0)")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.error(
                    f"Worker exited unexpectedly (code={exit_code}). "
                    f"Failure {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}"
                )

            # If worker keeps crashing back to back, slow down restarts
            # to avoid hammering the system
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error("Too many consecutive failures — waiting 60s before retry")
                time.sleep(60)
                consecutive_failures = 0
            else:
                time.sleep(3)

        except FileNotFoundError as e:
            logger.error(f"Worker executable not found: {e}")
            time.sleep(30)  # wait longer — this won't fix itself quickly

        except Exception as e:
            logger.exception(f"Supervisor error: {e}")
            time.sleep(5)