import requests
import os
import subprocess
import time
import logging
from config_manager import ConfigManager
from ui.activation import ActivationWindow
from ui.tray_app import TrayApp

from utils.logger import setup_logging
setup_logging("ui")
logger = logging.getLogger(__name__)

API = "http://127.0.0.1:57821"


def service_running():
    try:
        requests.get(API + "/ping", timeout=1)
        return True
    except:
        return False


def main():

    config = ConfigManager()

    # Device not activated → show activation
    if not config.token:
        ActivationWindow().run()

        config = ConfigManager()
        if not config.token:
            return

    if not service_running():
        try:
            # Start worker process
            subprocess.run(["sc", "start", "AudioAgentService"],
                           stdout=subprocess.DEVNULL)
            time.sleep(3)  # Wait a moment for the service to start
        except Exception as e:
            logger.error(f"Failed to start service: {e}")
            pass

    # Start tray UI
    TrayApp().start()


if __name__ == "__main__":
    main()
