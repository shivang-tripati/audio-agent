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
from utils.single_instance import SingleInstance

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

    RESTART_DELAY = 5        # crash restart
    STANDBY_DELAY = 60       # clean exit (e.g. device not activated) re-check

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None
        self.instance = None

    def _stopping(self):
        return win32event.WaitForSingleObject(
            self.stop_event, 0) == win32event.WAIT_OBJECT_0

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

            # Only one service instance may own a worker. SCM recovery
            # (sc failure ... restart/5000) and installer taskkill can start a
            # second instance while the first is still alive; without this the
            # second instance spawned its own worker and both played audio.
            self.instance = SingleInstance(
                mode="service", wait=True, stop_check=self._stopping)

            if not self.instance.acquired:
                logger.info("Service shutting down before owning the worker lock")
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            logger.info(f"AudioAgent Service running (worker PID={self.process.pid})")

            self._monitor_worker()

        except Exception as e:
            logger.exception("Service SvcDoRun failed")
            servicemanager.LogErrorMsg(f"AudioAgent Service failed: {str(e)}")
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)
        finally:
            self._cleanup()

    def _wait_stop(self, seconds):
        """Wait on the stop event. Returns True if shutdown was requested."""
        return win32event.WaitForSingleObject(
            self.stop_event, int(seconds * 1000)) == win32event.WAIT_OBJECT_0

    def _cleanup(self):
        self._terminate_worker()
        if self.instance:
            self.instance.release()
            self.instance = None

    def _terminate_worker(self):
        proc = self.process
        self.process = None
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                logger.warning("Worker force-killed after timeout")
        except Exception as e:
            logger.error(f"Failed to stop worker: {e}")

    def _monitor_worker(self):
        while not self._wait_stop(1):
            if not self.process or self.process.poll() is None:
                continue

            exit_code = self.process.returncode
            self.process = None

            if exit_code == SingleInstance.DUPLICATE_EXIT_CODE:
                logger.error(
                    "Another worker already owns this device (code="
                    f"{exit_code}). Service will not start a second one.")
                return

            if exit_code == 0:
                logger.info(
                    "Worker exited cleanly (expected shutdown). "
                    f"Standing by {self.STANDBY_DELAY}s before re-check.")
                if self._wait_stop(self.STANDBY_DELAY):
                    return
            else:
                logger.error(
                    f"Worker exited unexpectedly (code={exit_code}). "
                    f"Restarting in {self.RESTART_DELAY}s...")
                if self._wait_stop(self.RESTART_DELAY):
                    return

            try:
                cmd = _get_worker_command()
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                logger.info(f"Worker restarted (PID={self.process.pid})")
            except Exception as e:
                logger.error(f"Failed to restart worker: {e}")

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        servicemanager.LogInfoMsg("AudioAgent Service stopping")
        logger.info("AudioAgent Service stopping")

        # Signal first: the monitor loop must not respawn a worker while we
        # are tearing the current one down (that left an orphaned worker
        # holding the device mutex and playing audio).
        win32event.SetEvent(self.stop_event)

        self._terminate_worker()

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