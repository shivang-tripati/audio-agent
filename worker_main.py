"""
Worker Main — the actual AudioAgent process.
Launched by supervisor or service as a subprocess with --worker flag.
"""

import sys
import os
import time
import logging
from pathlib import Path


# --------------------------------------------------
# STEP 0: Raw debug — before ANY import
# --------------------------------------------------
os.makedirs(r"C:\ProgramData\AudioAgent\logs", exist_ok=True)
with open(r"C:\ProgramData\AudioAgent\logs\worker_debug.txt", "a") as f:
    f.write(f"=== Worker started ===\n")
    f.write(f"exe: {sys.executable}\n")
    f.write(f"argv: {sys.argv}\n")
    f.write(f"CWD: {os.getcwd()}\n")


# --------------------------------------------------
# STEP 1: Fix working directory BEFORE any local import
# --------------------------------------------------
def fix_working_directory():
    if getattr(sys, 'frozen', False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parent

    os.chdir(str(app_dir))

    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))

    return app_dir


try:
    app_dir = fix_working_directory()
    with open(r"C:\ProgramData\AudioAgent\logs\worker_debug.txt", "a") as f:
        f.write(f"CWD fixed to: {app_dir}\n")
except Exception as e:
    with open(r"C:\ProgramData\AudioAgent\logs\worker_debug.txt", "a") as f:
        f.write(f"fix_working_directory FAILED: {e}\n")
    raise


# --------------------------------------------------
# STEP 2: NOW safe to import local modules
# --------------------------------------------------
try:
    from utils.logger import setup_logging
    setup_logging("worker")
    logger = logging.getLogger(__name__)
    logger.info(f"Worker CWD set to: {app_dir}")
    with open(r"C:\ProgramData\AudioAgent\logs\worker_debug.txt", "a") as f:
        f.write(f"setup_logging OK\n")
except Exception as e:
    with open(r"C:\ProgramData\AudioAgent\logs\worker_debug.txt", "a") as f:
        f.write(f"setup_logging FAILED: {e}\n")
    raise

from utils.single_instance import SingleInstance


# --------------------------------------------------
# Worker entry point
# --------------------------------------------------
def run_worker():
    logger.info(f"Worker starting — PID={os.getpid()}")

    instance = SingleInstance(mode="worker")

    try:
        while True:
            try:
                from agent_app import AudioAgent
                agent = AudioAgent()
                agent.start()

            except KeyboardInterrupt:
                logger.info("Worker received keyboard interrupt — stopping")
                break

            except Exception as e:
                logger.exception(f"Worker crashed: {e}")

            from config_manager import ConfigManager
            if not ConfigManager().token:
                logger.error("Device not activated — worker will not restart. Run UI to activate.")
                break

            logger.info("Worker restarting in 5 seconds...")
            time.sleep(5)

    finally:
        instance.release()
        logger.info("Worker exited cleanly")