import win32event
import win32api
import winerror
import sys
import logging


logger = logging.getLogger(__name__)

MUTEX_NAME = "Global\\AudioAgentSingleInstance"


class SingleInstance:

    def __init__(self):

        self.mutex = win32event.CreateMutex(None, False, MUTEX_NAME)

        last_error = win32api.GetLastError()

        if last_error == winerror.ERROR_ALREADY_EXISTS:
            logger.warning("Another instance is already running. Exiting.")
            sys.exit(0)

    def release(self):
        if self.mutex:
            win32api.CloseHandle(self.mutex)
