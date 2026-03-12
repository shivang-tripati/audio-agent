import win32serviceutil
import win32service
import win32event
import servicemanager
import sys
import logging
import threading
import subprocess
import logging
import os

from utils.logger import setup_logging

setup_logging("service")
logger = logging.getLogger(__name__)


class AudioAgentService(win32serviceutil.ServiceFramework):

    _svc_name_ = "AudioAgentService"
    _svc_display_name_ = "Audio Agent Service"
    _svc_description_ = "Cloud Audio Scheduler Agent"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)

        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None

    # ----------------------------------------
    # Service start
    # ----------------------------------------

    def SvcDoRun(self):

        try:

            servicemanager.LogInfoMsg("AudioAgent Service starting")
            logger.info("AudioAgent Service starting")

            exe_dir = os.path.dirname(sys.executable)
            agent_exe = os.path.join(exe_dir, "AudioAgent.exe")

            if not os.path.exists(agent_exe):
                logger.error("AudioAgent.exe not found")
                return

            self.process = subprocess.Popen(
                [agent_exe, "--supervisor"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            logger.info("Supervisor process started")

            win32event.WaitForSingleObject(
                self.stop_event,
                win32event.INFINITE
            )

        except Exception as e:
            logger.exception("Service crashed")
            servicemanager.LogErrorMsg(str(e))

    # ----------------------------------------
    # Service stop
    # ----------------------------------------

    def SvcStop(self):

        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)

        servicemanager.LogInfoMsg("AudioAgent Service stopping")
        logger.info("AudioAgent Service stopping")

        if self.process:
            self.process.terminate()

        win32event.SetEvent(self.stop_event)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(AudioAgentService)
