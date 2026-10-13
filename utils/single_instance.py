import win32event
import win32api
import win32security
import win32con
import winerror
import sys
import logging
import os
import time

logger = logging.getLogger(__name__)


def _winerror_of(exc):
    """Windows error code from a pywintypes/OSError exception."""
    code = getattr(exc, "winerror", None)
    if code is None and exc.args:
        code = exc.args[0]
    return code


class SingleInstance:
    """
    Single instance checker — separate logic for service vs worker vs UI.

    Three contexts:
      - Service  (service.py)   → Global\\AudioAgent_Service  (one service system-wide)
      - Worker   (worker_main)  → Global\\AudioAgent_Worker   (one worker system-wide)
      - UI       (ui_main.py)   → Local\\AudioAgent_User_SID  (one UI per user session)

    Why separate names?
      Both service and worker run in session 0, so _is_running_as_service()
      returns True for both. Without distinct mutex names they'd conflict —
      the worker would see the service mutex and exit immediately thinking
      another instance is running.

    Usage:
        instance = SingleInstance()           # auto-detects context
        instance = SingleInstance("worker")   # force worker context
        instance = SingleInstance("service")  # force service context

    wait=True does not exit on a duplicate — it blocks until the other owner
    exits (or stop_check() returns True) and is used by the supervisors so a
    second supervisor parks instead of fighting the first one.
    """

    # Exit code meaning "another instance already owns this role".
    # Distinct from 0 so supervisors do not treat a rejected duplicate as an
    # ordinary clean exit and respawn it.
    DUPLICATE_EXIT_CODE = 3

    WORKER_MUTEX_NAME = "Global\\AudioAgent_Worker"
    SERVICE_MUTEX_NAME = "Global\\AudioAgent_Service"

    def __init__(self, mode: str = None, wait: bool = False,
                 stop_check=None, poll_interval: float = 2.0,
                 mutex_name: str = None):
        """
        Args:
            mode: Force a specific mode — 'service', 'worker', or 'ui'.
                  If None, auto-detects from process context.
            wait:       Block until the mutex is free instead of exiting.
            stop_check: Callable polled while waiting; returning True aborts
                        the wait (the caller is shutting down).
            mutex_name: Override the mutex name (used by the tests so they
                        never collide with a live agent).
        """
        self.mutex = None
        self.acquired = False

        if mode:
            self._mode = mode
        else:
            self._mode = self._detect_mode()

        logger.info(f"SingleInstance mode: {self._mode}")

        if self._mode == "service":
            name = mutex_name or self.SERVICE_MUTEX_NAME
        elif self._mode == "worker":
            name = mutex_name or self.WORKER_MUTEX_NAME
        else:
            self._init_ui_mutex(mutex_name)
            return

        # A worker without its mutex would be a second playback owner, so a
        # failed CreateMutex is fatal for both service and worker.
        self._acquire_mutex(name, critical=True, wait=wait,
                           stop_check=stop_check, poll_interval=poll_interval)

    # --------------------------------------------------
    # Mode detection
    # --------------------------------------------------

    def _detect_mode(self) -> str:
        """
        Auto-detect whether we are running as service, worker, or UI.

        Detection order:
          1. Check if parent is services.exe → service
          2. Check if session ID is 0 → could be service or worker subprocess
             In this case we default to 'worker' because service.py should
             always pass mode='service' explicitly.
          3. Fallback → UI
        """
        try:
            import psutil
            parent = psutil.Process(os.getppid())
            parent_name = parent.name().lower()

            if parent_name in ['services.exe', 'svchost.exe']:
                # Direct child of SCM → we are the service
                return "service"

            # Check session ID
            process = psutil.Process()
            if process.session_id() == 0:
                # Session 0 but parent is not SCM → we are a worker subprocess
                return "worker"

        except Exception:
            pass

        # No SESSIONNAME env var → likely non-interactive / service context
        if 'SESSIONNAME' not in os.environ:
            return "worker"

        return "ui"

    # --------------------------------------------------
    # Generic mutex init (service + worker)
    # --------------------------------------------------

    def _build_security_attributes(self):
        """SYSTEM + Administrators full access — matches how these run."""
        sd = win32security.SECURITY_DESCRIPTOR()
        system_sid = win32security.ConvertStringSidToSid("S-1-5-18")
        admin_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")

        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(win32con.ACL_REVISION, win32con.GENERIC_ALL, system_sid)
        dacl.AddAccessAllowedAce(win32con.ACL_REVISION, win32con.GENERIC_ALL, admin_sid)
        sd.SetSecurityDescriptorDacl(1, dacl, 0)

        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        return sa

    def _try_acquire(self, mutex_name: str):
        """
        One atomic attempt to take ownership of the named mutex.

        Returns:
            "acquired" — we created the object and now own it.
            "duplicate" — the object already existed (another owner alive).
            ("error", exc) on failure.

        CreateMutex is the only race-free way to test this: a pre-check with
        OpenMutex can be beaten by a second process between check and create.
        The old code used exactly that pre-check and it never ran at all —
        win32con has no MUTEX_ALL_ACCESS, so the call raised AttributeError
        and the blanket `except Exception: pass` swallowed it. Every worker
        therefore "created" the mutex and started a second playback owner.
        The existing-object signal is ERROR_ALREADY_EXISTS from GetLastError.

        ERROR_ACCESS_DENIED counts as duplicate too: these mutexes are created
        with a DACL limited to SYSTEM/Administrators, so a worker running as
        any other account cannot open the one its predecessor created. That is
        still "somebody else owns this role", never "safe to start".
        """
        try:
            sa = self._build_security_attributes()
            handle = win32event.CreateMutex(sa, True, mutex_name)
        except Exception as e:
            if _winerror_of(e) == winerror.ERROR_ACCESS_DENIED:
                logger.warning(
                    f"CreateMutex on '{mutex_name}' denied access — "
                    "another instance owns it under a different account")
                return "duplicate"
            raise

        already_exists = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS

        if already_exists:
            win32api.CloseHandle(handle)
            return "duplicate"

        self.mutex = handle
        return "acquired"

    def _acquire_mutex(self, mutex_name: str, critical: bool,
                       wait: bool = False, stop_check=None,
                       poll_interval: float = 2.0):
        logger.info(f"Acquiring mutex: {mutex_name}")

        announced_wait = False
        while True:
            try:
                result = self._try_acquire(mutex_name)
            except Exception as e:
                logger.error(f"Failed to create mutex '{mutex_name}': {e}")
                if critical:
                    logger.critical("Critical mutex failed — exiting.")
                    sys.exit(1)
                logger.warning("Non-critical mutex failed — continuing without it.")
                return

            if result == "acquired":
                self.acquired = True
                logger.info(f"Mutex acquired: {mutex_name}")
                return

            # result == "duplicate"
            if not wait:
                logger.warning(
                    f"Another instance already holds mutex: {mutex_name}. Exiting.")
                sys.exit(self.DUPLICATE_EXIT_CODE)

            if not announced_wait:
                logger.warning(
                    f"Another instance already holds mutex: {mutex_name}. Waiting.")
                announced_wait = True

            if stop_check and stop_check():
                logger.info("Shutdown requested while waiting for mutex — giving up.")
                return

            time.sleep(poll_interval)

    # --------------------------------------------------
    # UI mutex init
    # --------------------------------------------------

    def _init_ui_mutex(self, mutex_name: str = None):
        """Session-scoped mutex — one UI instance per user session."""
        try:
            if mutex_name is None:
                token = win32security.OpenProcessToken(
                    win32api.GetCurrentProcess(),
                    win32con.TOKEN_QUERY
                )
                user_sid = win32security.GetTokenInformation(
                    token, win32security.TokenUser
                )[0]
                sid_string = win32security.ConvertSidToStringSid(user_sid)
                mutex_name = f"Local\\AudioAgent_User_{sid_string}"

            logger.info(f"UI mode: Creating session mutex: {mutex_name}")

            self.mutex = win32event.CreateMutex(None, False, mutex_name)
            last_error = win32api.GetLastError()

            if last_error == winerror.ERROR_ALREADY_EXISTS:
                logger.warning(
                    "Another UI instance already running. Exiting with code "
                    f"{self.DUPLICATE_EXIT_CODE}.")
                sys.exit(self.DUPLICATE_EXIT_CODE)

            self.acquired = True
            logger.info("UI mutex created successfully")

        except Exception as e:
            logger.error(f"Failed to create UI mutex: {e}")
            logger.warning("Continuing without mutex — multiple UI instances possible")
            self.mutex = None

    # --------------------------------------------------
    # Release
    # --------------------------------------------------

    def release(self):
        """Release the mutex on clean exit."""
        if self.mutex:
            try:
                win32api.CloseHandle(self.mutex)
                self.mutex = None
                self.acquired = False
                logger.debug("Mutex released")
            except Exception as e:
                logger.error(f"Error releasing mutex: {e}")