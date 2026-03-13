import requests
import os
import subprocess
import time
import logging
from config_manager import ConfigManager
from ui.activation import ActivationWindow
from ui.tray_app import TrayApp, find_api_url
from utils.single_instance import SingleInstance

from utils.logger import setup_logging
setup_logging("ui")
logger = logging.getLogger(__name__)


def service_running():
    """
    Check if the agent API is reachable on any known port.
    Uses find_api_url() instead of hardcoded port so fallback
    ports are also checked.
    """
    for port in [57821, 57822, 57823, 57824]:
        try:
            requests.get(f"http://127.0.0.1:{port}/ping", timeout=1)
            return True
        except Exception:
            continue
    return False


def main():
    # Prevent duplicate tray instances
    instance = SingleInstance(mode="ui")

    config = ConfigManager()

    # Device not activated → show activation window first
    if not config.token:
        ActivationWindow().run()

        config = ConfigManager()
        if not config.token:
            instance.release()
            return

    # Start service if not already running
    if not service_running():
        logger.info("Service not running — attempting to start...")
        try:
            subprocess.run(
                ["sc", "start", "AudioAgentService"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Wait up to 10 seconds for service to come up
            for _ in range(10):
                time.sleep(1)
                if service_running():
                    logger.info("Service started successfully")
                    break
            else:
                logger.warning("Service did not respond after 10s — continuing anyway")
        except Exception as e:
            logger.error(f"Failed to start service: {e}")

    # Start tray UI — blocks until user exits
    TrayApp().start()

    instance.release()


if __name__ == "__main__":
    main()