import sys
import os
import time
import subprocess
import threading
import logging

import win32serviceutil
import win32service
import win32event
import servicemanager

from utils.logger import setup_logging

setup_logging("service")
logger = logging.getLogger(__name__)


# --------------------------------------------------
# Helper: resolve absolute path to our executable
# --------------------------------------------------

def get_exe_path():
    if getattr(sys, 'frozen', False):
        service_dir = os.path.dirname(sys.executable)
        worker_exe = os.path.join(service_dir, "AudioAgent.exe")
        if not os.path.exists(worker_exe):
            logger.error(f"Worker exe not found: {worker_exe}")
            raise FileNotFoundError(f"AudioAgent.exe not found at: {worker_exe}")
        return worker_exe
    else:
        return sys.executable


def _get_worker_command():
    if getattr(sys, 'frozen', False):
        worker_exe = get_exe_path()
        return [worker_exe, "--worker"]
    else:
        main_py = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "main.py")
        )
        return [sys.executable, main_py, "--worker"]


# --------------------------------------------------
# Windows Service
# --------------------------------------------------

class AudioAgentService(win32serviceutil.ServiceFramework):

    _svc_name_ = "AudioAgentService"
    _svc_display_name_ = "Audio Agent Service"
    _svc_description_ = "Cloud Audio Scheduler Agent"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None

    def SvcDoRun(self):
        try:
            self.ReportServiceStatus(win32service.SERVICE_START_PENDING)

            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, "")
            )

            cmd = _get_worker_command()
            logger.info(f"Service exe: {sys.executable}")
            logger.info(f"Worker cmd: {cmd}")
            logger.info(f"Worker exists: {os.path.exists(cmd[0])}")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            logger.info("AudioAgent Service running")

            self._monitor_worker()

        except Exception as e:
            logger.exception("Service SvcDoRun failed")
            servicemanager.LogErrorMsg(f"AudioAgent Service failed: {str(e)}")
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def _monitor_worker(self):
        RESTART_DELAY = 5

        while True:
            result = win32event.WaitForSingleObject(self.stop_event, 1000)

            if result == win32event.WAIT_OBJECT_0:
                logger.info("Stop event received — exiting monitor loop")
                break

            if self.process and self.process.poll() is not None:
                exit_code = self.process.returncode
                logger.error(f"Worker exited (code={exit_code}). Restarting in {RESTART_DELAY}s...")

                stop_during_wait = win32event.WaitForSingleObject(
                    self.stop_event, RESTART_DELAY * 1000
                )
                if stop_during_wait == win32event.WAIT_OBJECT_0:
                    break

                try:
                    cmd = _get_worker_command()
                    self.process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    logger.info("Worker restarted successfully")
                except Exception as e:
                    logger.error(f"Failed to restart worker: {e}")

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        servicemanager.LogInfoMsg("AudioAgent Service stopping")
        logger.info("AudioAgent Service stopping")

        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    logger.warning("Worker force-killed after timeout")
            except Exception as e:
                logger.error(f"Failed to stop worker: {e}")

        win32event.SetEvent(self.stop_event)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)
        logger.info("AudioAgent Service stopped")


# --------------------------------------------------
# Entry point
# --------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No arguments — launched by SCM
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(AudioAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # install / remove / start / stop from command line
        win32serviceutil.HandleCommandLine(AudioAgentService)