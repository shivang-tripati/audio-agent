import win32event
import win32api
import win32security
import win32con
import winerror
import sys
import logging
import os

logger = logging.getLogger(__name__)


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
    """

    def __init__(self, mode: str = None):
        """
        Args:
            mode: Force a specific mode — 'service', 'worker', or 'ui'.
                  If None, auto-detects from process context.
        """
        self.mutex = None

        if mode:
            self._mode = mode
        else:
            self._mode = self._detect_mode()

        logger.info(f"SingleInstance mode: {self._mode}")

        if self._mode == "service":
            self._init_mutex("Global\\AudioAgent_Service", critical=True)

        elif self._mode == "worker":
            self._init_mutex("Global\\AudioAgent_Worker", critical=False)

        elif self._mode == "ui":
            self._init_ui_mutex()

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

    def _init_mutex(self, mutex_name: str, critical: bool):
        """
        Create a named global mutex.

        Args:
            mutex_name: Full mutex name e.g. 'Global\\AudioAgent_Worker'
            critical:   If True, exit(1) on failure (service must have mutex).
                        If False, log warning and continue (worker is best-effort).
        """
        try:
            logger.info(f"Creating mutex: {mutex_name}")

            # Security descriptor: allow SYSTEM + Administrators full access
            sd = win32security.SECURITY_DESCRIPTOR()
            system_sid = win32security.ConvertStringSidToSid("S-1-5-18")
            admin_sid = win32security.ConvertStringSidToSid("S-1-5-32-544")

            dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(win32con.ACL_REVISION, win32con.GENERIC_ALL, system_sid)
            dacl.AddAccessAllowedAce(win32con.ACL_REVISION, win32con.GENERIC_ALL, admin_sid)
            sd.SetSecurityDescriptorDacl(1, dacl, 0)

            sa = win32security.SECURITY_ATTRIBUTES()
            sa.SECURITY_DESCRIPTOR = sd

            # Try to open first — if it succeeds, another instance is running
            try:
                existing = win32event.OpenMutex(
                    win32con.MUTEX_ALL_ACCESS, False, mutex_name
                )
                win32api.CloseHandle(existing)
                logger.warning(f"Another instance already holds mutex: {mutex_name}. Exiting.")
                sys.exit(0)
            except Exception:
                pass  # mutex doesn't exist yet — good, create it

            self.mutex = win32event.CreateMutex(sa, False, mutex_name)
            logger.info(f"Mutex created: {mutex_name}")

        except Exception as e:
            logger.error(f"Failed to create mutex '{mutex_name}': {e}")
            if critical:
                logger.critical("Critical mutex failed — exiting.")
                sys.exit(1)
            else:
                logger.warning("Non-critical mutex failed — continuing without it.")

    # --------------------------------------------------
    # UI mutex init
    # --------------------------------------------------

    def _init_ui_mutex(self):
        """Session-scoped mutex — one UI instance per user session."""
        try:
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
                logger.warning("Another UI instance already running. Exiting.")
                sys.exit(0)

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
                logger.debug("Mutex released")
            except Exception as e:
                logger.error(f"Error releasing mutex: {e}")