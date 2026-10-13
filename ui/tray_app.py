"""
Enhanced Tray Application with comprehensive logging.
Modern design, responsive behavior, detailed event tracking.
Integrates with your existing logger setup.
"""

import pystray
from PIL import Image, ImageDraw
import requests
import re
import threading
import time
import os
import subprocess
import tkinter as tk
import logging
from datetime import datetime

# Use your existing logger setup - no separate file handlers needed!
tray_logger = logging.getLogger("TrayApp")

# Set level if not already configured
if tray_logger.level == logging.NOTSET:
    tray_logger.setLevel(logging.DEBUG)

from ui.status_panel import ModernStatusPanel

PORTS = [57821, 57822, 57823, 57824]
PORT_CHECK_TIMEOUT = 1

SERVICE_NAME = "AudioAgentService"
# "sc stop" is asynchronous: the SCM accepts the request and returns straight
# away. Starting a new instance before the old one has actually stopped is what
# produced two AudioAgentService.exe processes (and two workers) at once.
SERVICE_STOP_TIMEOUT = 90
SERVICE_START_TIMEOUT = 60

# --------------------------------------------------
# State-aware playback control
#
# The tray shows what the agent can actually do right now, based on the last
# successful /status response - never on an unverified local toggle.
#   PLAYING -> pause the current track (position is preserved by VLC)
#   PAUSED  -> resume the same track at the same position
#   IDLE    -> start the playlist engine (existing playlist semantics)
# Stop stays a separate control: pausing is not stopping.
# --------------------------------------------------
PLAYBACK_ACTIONS = {
    "PLAYING": ("⏸ Pause Audio", "/pause"),
    "PAUSED": ("▶ Resume Audio", "/resume"),
    "IDLE": ("▶ Start Playback", "/playlist/start"),
}
OFFLINE_ACTION = ("⏹ Playback unavailable (agent offline)", None, False)


def playback_action_for(status):
    """(label, endpoint, enabled) for the given agent state."""
    if status in PLAYBACK_ACTIONS:
        label, endpoint = PLAYBACK_ACTIONS[status]
        return label, endpoint, True
    return OFFLINE_ACTION


def query_service_state(name=SERVICE_NAME):
    """Current SCM state name (e.g. 'RUNNING'), or None if it cannot be read."""
    try:
        result = subprocess.run(
            ["sc", "query", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        tray_logger.warning(f"sc query failed: {e}")
        return None

    match = re.search(r"STATE\s+:\s+\d+\s+(\w+)", result.stdout or "")
    if not match:
        tray_logger.warning(f"Could not parse sc query output: {result.stdout!r}")
        return None
    return match.group(1)


def wait_for_service_state(target, timeout, name=SERVICE_NAME):
    """Wait until the SCM reports `target`. True if reached within `timeout`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if query_service_state(name) == target:
            return True
        time.sleep(1)
    return query_service_state(name) == target


def control_service(action, name=SERVICE_NAME):
    """Run "sc <action> <name>". Returns (ok, stderr)."""
    try:
        result = subprocess.run(
            ["sc", action, name],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        tray_logger.error(f"sc {action} failed: {e}")
        return False, str(e)

    if result.returncode != 0:
        tray_logger.warning(
            f"sc {action} {name} returned {result.returncode}: "
            f"{(result.stderr or '').strip()}"
        )
        return False, (result.stderr or "").strip()
    return True, ""


def find_api_url():
    """
    Scan ports to find which one the agent is running on.
    Logs all attempts for debugging.
    """
    tray_logger.debug("Scanning for API service")
    
    for port in PORTS:
        try:
            url = f"http://127.0.0.1:{port}/ping"
            tray_logger.debug(f"Trying port {port}")
            
            response = requests.get(url, timeout=PORT_CHECK_TIMEOUT)
            response.raise_for_status()
            
            api_url = f"http://127.0.0.1:{port}"
            tray_logger.info(f"API found at {api_url}")
            return api_url
            
        except requests.RequestException as e:
            tray_logger.debug(f"Port {port} failed: {type(e).__name__}")
            continue
        except Exception as e:
            tray_logger.warning(f"Unexpected error checking port {port}: {e}")
            continue

    default_url = f"http://127.0.0.1:{PORTS[0]}"
    tray_logger.warning(f"API not found on any port, using default: {default_url}")
    return default_url




class EnhancedTrayApp:
    """
    Enhanced tray application with comprehensive logging and modern design.
    Handles system tray icon, menu, and status panel.
    """

    def __init__(self):
        tray_logger.info("Initializing EnhancedTrayApp")
        self.running = True
        self.api_url = find_api_url()
        self.last_status = None
        self.last_audio = None
        self.agent_status = "UNKNOWN"
        self._status_update_count = 0

        # Serialises playback commands: a burst of clicks must not produce
        # overlapping /pause + /resume + /playlist/start requests.
        self._command_lock = threading.Lock()

        # Create status panel
        self.panel = ModernStatusPanel(lambda: self.api_url)
        self.panel._on_exit = self.exit

        # Load or create tray icon
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(base_dir, "..", "icon.ico")
            
            if os.path.exists(icon_path):
                tray_logger.info(f"Loading icon from {icon_path}")
                icon_image = Image.open(icon_path)
            else:
                tray_logger.warning(f"Icon not found at {icon_path}, creating default")
                icon_image = create_tray_icon()
        except Exception as e:
            tray_logger.error(f"Icon loading error: {e}, creating default")
            icon_image = create_tray_icon()

        # Create pystray icon with menu
        self.icon = pystray.Icon(
            "AudioAgent",
            icon_image,
            "Audio Agent"
        )

        # The playback item is state-aware: its label and enabled flag are
        # refreshed from every successful /status response. pystray's
        # MenuItem.text is read-only, so the menu is rebuilt on change.
        self.agent_status = "UNKNOWN"
        self._playback_label = OFFLINE_ACTION[0]
        self._playback_item = pystray.MenuItem(
            self._playback_label, self._playback_action, enabled=False)
        self.icon.menu = self._build_menu(self._playback_item)

        tray_logger.info("TrayApp initialized successfully")

    def _build_menu(self, playback_item):
        return pystray.Menu(
            pystray.MenuItem(
                "📊 Open Panel",
                self._open_panel,
                default=True
            ),
            pystray.Menu.SEPARATOR,
            playback_item,
            pystray.MenuItem("⏹ Stop Audio", self._stop_audio),
            pystray.MenuItem("↻ Restart Service", self._restart_service),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Exit", self.exit)
        )

    def start(self):
        """Start the tray application"""
        tray_logger.info("Starting TrayApp")
        
        # Status polling thread
        polling_thread = threading.Thread(
            target=self._poll_status,
            daemon=True,
            name="TrayApp-StatusPoller"
        )
        polling_thread.start()
        tray_logger.info("Status polling thread started")

        # Icon thread
        icon_thread = threading.Thread(
            target=self._run_icon,
            daemon=True,
            name="TrayApp-IconThread"
        )
        icon_thread.start()
        tray_logger.info("Icon thread started")

        # Tkinter main loop on main thread
        self._tk_root = tk.Tk()
        self._tk_root.withdraw()
        tray_logger.info("Tkinter root window created")
        
        try:
            self._tk_root.mainloop()
        except Exception as e:
            tray_logger.error(f"Tkinter mainloop error: {e}", exc_info=True)
        finally:
            tray_logger.info("Tkinter mainloop ended")

    def _run_icon(self):
        """Run the tray icon (in separate thread)"""
        try:
            tray_logger.info("Icon thread running")
            self.icon.run()
        except Exception as e:
            tray_logger.error(f"Icon thread error: {e}", exc_info=True)
        finally:
            tray_logger.info("Icon thread stopped")

    def _poll_status(self):
        """Poll API for status updates"""
        tray_logger.info("Status polling started")
        consecutive_errors = 0
        max_errors = 5

        while self.running:
            try:
                self.api_url = find_api_url()

                status_data = self._fetch_status(self.api_url)
                if status_data is None:
                    raise requests.RequestException("status unavailable")

                consecutive_errors = 0  # Reset error counter
                self._apply_status(status_data)

                if self._status_update_count % 10 == 0:  # Log every 10 updates
                    tray_logger.debug(
                        f"Status update #{self._status_update_count}: "
                        f"{self.last_status} - {self.last_audio} "
                        f"({(status_data.get('uptime') or 0) // 60}m)"
                    )

            except requests.RequestException as e:
                consecutive_errors += 1
                tray_logger.warning(
                    f"Status poll failed (#{consecutive_errors}): {type(e).__name__}"
                )

                if consecutive_errors >= max_errors:
                    tray_logger.error("Max consecutive errors reached, updating to offline")
                    self.icon.title = "Audio Agent · Offline"
                    self.last_status = "OFFLINE"
                    self._sync_playback_menu("OFFLINE")

            except Exception as e:
                consecutive_errors += 1
                tray_logger.error(f"Poll loop error: {e}", exc_info=True)
                self.icon.title = "Audio Agent · Error"

            time.sleep(4)  # Poll every 4 seconds

        tray_logger.info("Status polling stopped")

    def _fetch_status(self, api_url=None):
        """GET /status. Returns the payload dict, or None if unreachable."""
        url = api_url or self.api_url
        try:
            r = requests.get(f"{url}/status", timeout=2)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            tray_logger.debug(f"GET {url}/status failed: {type(e).__name__}")
            return None

    def _apply_status(self, status_data):
        """Apply a /status payload to the tray title, menu and cached state."""
        status = status_data.get("status", "IDLE")
        audio = status_data.get("audio") or "Idle"
        uptime = int(status_data.get("uptime", 0)) // 60
        volume = status_data.get("volume", 0)

        if status != self.last_status or audio != self.last_audio:
            tray_logger.info(
                f"Status: {self.last_status} -> {status}, "
                f"Audio: {self.last_audio} -> {audio}"
            )
            self.last_status = status
            self.last_audio = audio

        self._update_tray_title(status, audio, uptime, volume)
        self._sync_playback_menu(status)
        self._status_update_count += 1

    def _sync_playback_menu(self, status):
        """Point the playback item at the action the agent can do right now."""
        label, endpoint, enabled = playback_action_for(status)
        if status == self.agent_status and label == self._playback_label:
            return

        self.agent_status = status
        self._playback_label = label
        # pystray.MenuItem.text is a read-only property, so the item (and the
        # menu that holds it) is rebuilt whenever the action changes.
        self._playback_item = pystray.MenuItem(
            label, self._playback_action, enabled=enabled)
        try:
            self.icon.menu = self._build_menu(self._playback_item)
            self.icon.update_menu()
        except Exception as e:
            tray_logger.warning(f"Could not refresh tray menu: {e}")
        tray_logger.info(
            f"Tray playback action for {status}: {label} (enabled={enabled})")

    def _update_tray_title(self, status, audio, uptime, volume):
        """Update the tray icon title with current status"""
        try:
            if status == "PLAYING":
                title = f"▶ {audio[:40]} · {uptime}m · {volume}%"
            elif status == "PAUSED":
                title = f"⏸ Paused · {audio[:40]} · {volume}%"
            else:
                title = f"Audio Agent · Idle · {volume}%"
            
            self.icon.title = title
            
        except Exception as e:
            tray_logger.error(f"Error updating tray title: {e}")

    def _open_panel(self):
        """Open the status panel"""
        tray_logger.info("Opening status panel")
        try:
            if self._tk_root:
                self._tk_root.after(0, self.panel.show)
        except Exception as e:
            tray_logger.error(f"Error opening panel: {e}")

    def _stop_audio(self):
        """Stop audio playback (distinct from pause)"""
        tray_logger.info("Stop audio requested from tray menu")
        self._spawn_command("/stop", "⏹ Stop Audio")

    # --------------------------------------------------
    # Playback commands
    # --------------------------------------------------

    def _playback_action(self, icon=None):
        """Tray callback for the state-aware playback item."""
        label, endpoint, enabled = playback_action_for(self.agent_status)
        if not enabled:
            tray_logger.warning(
                f"'{label}' - agent state is {self.agent_status}; not sending "
                "any command (the tray never starts a worker itself)")
            try:
                self.icon.title = "Audio Agent · Offline"
            except Exception:
                pass
            return

        tray_logger.info(
            f"Playback action requested: {label} (state={self.agent_status})")
        self._spawn_command(endpoint, label)

    def _spawn_command(self, endpoint, label):
        """Run a playback command off the tray event loop, one at a time."""
        threading.Thread(
            target=self._run_command,
            args=(endpoint, label, self.agent_status),
            daemon=True,
            name="TrayApp-Playback",
        ).start()

    def _run_command(self, endpoint, label, previous_state):
        if not self._command_lock.acquire(blocking=False):
            tray_logger.info(
                f"Ignoring '{label}' - another playback command is in flight")
            return

        try:
            tray_logger.info(
                f"POST {endpoint} ({label}, previous state {previous_state})")
            r = requests.post(f"{self.api_url}{endpoint}", timeout=5)
            r.raise_for_status()
            try:
                body = r.json()
            except ValueError:
                body = r.text
            tray_logger.info(f"API {endpoint} -> {r.status_code} {body}")

            # Never trust the HTTP 200 alone - confirm with a fresh /status.
            confirmed = self._fetch_status()
            if confirmed is None:
                confirmed = self._fetch_status(find_api_url())
            if confirmed is None:
                tray_logger.error(
                    f"'{label}' sent but /status is unreachable - state unknown")
                return
            self._apply_status(confirmed)
            tray_logger.info(
                f"Confirmed state after '{label}': {self.last_status} "
                f"({self.last_audio})")
        except requests.RequestException as e:
            tray_logger.error(
                f"'{label}' failed: {e} - agent/service may be offline")
            try:
                self.icon.title = "Audio Agent · Offline"
            except Exception:
                pass
        except Exception as e:
            tray_logger.error(f"Playback command '{label}' error: {e}", exc_info=True)
        finally:
            self._command_lock.release()

    def _restart_service(self):
        """Restart the service"""
        tray_logger.info("Service restart requested from tray menu")
        threading.Thread(
            target=self._do_restart,
            daemon=True,
            name="ServiceRestarter"
        ).start()

    def _do_restart(self):
        """
        Restart the Windows service.

        "sc stop" only *requests* a stop — the old service (and its worker) can
        still be alive seconds later. Starting a new instance while that happens
        yields two service processes with two workers on one audio device, so we
        wait for STOPPED before starting and verify RUNNING afterwards.
        """
        try:
            state = query_service_state()
            tray_logger.info(f"Service state before restart: {state}")

            if state != "STOPPED":
                tray_logger.info("Requesting AudioAgentService stop via SC")
                control_service("stop")

                if not wait_for_service_state("STOPPED", SERVICE_STOP_TIMEOUT):
                    tray_logger.error(
                        "Service did not reach STOPPED within "
                        f"{SERVICE_STOP_TIMEOUT}s (state: "
                        f"{query_service_state()}) — not starting a second "
                        "instance."
                    )
                    return
                tray_logger.info("Service reached STOPPED")

            tray_logger.info("Starting AudioAgentService via SC")
            ok, err = control_service("start")
            if not ok:
                tray_logger.error(f"sc start failed: {err}")
                return

            if not wait_for_service_state("RUNNING", SERVICE_START_TIMEOUT):
                tray_logger.error(
                    "Service did not reach RUNNING within "
                    f"{SERVICE_START_TIMEOUT}s"
                )
                return

            tray_logger.info("Service is RUNNING")
            time.sleep(2)
            self.api_url = find_api_url()
            tray_logger.info("Service restart completed")

        except Exception as e:
            tray_logger.error(f"Service restart error: {e}", exc_info=True)

    def exit(self):
        """Exit the tray application"""
        tray_logger.info("Exit requested")
        self.running = False

        try:
            self.icon.stop()
            tray_logger.info("Icon stopped")
        except Exception as e:
            tray_logger.warning(f"Error stopping icon: {e}")

        try:
            if self._tk_root:
                self._tk_root.after(0, self._tk_root.quit)
                tray_logger.info("Tkinter quit scheduled")
        except Exception as e:
            tray_logger.warning(f"Error quitting tkinter: {e}")

        tray_logger.info("TrayApp exiting")


# For backward compatibility
TrayApp = EnhancedTrayApp

if __name__ == "__main__":
    tray_logger.info("=== TrayApp started ===")
    app = EnhancedTrayApp()
    app.start()
    tray_logger.info("=== TrayApp ended ===")