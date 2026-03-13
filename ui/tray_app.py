import pystray
from PIL import Image
import requests
import threading
import time
import os

PORTS = [57821, 57822, 57823, 57824]


def find_api_url():
    """
    Scan ports to find whichever one the agent is actually running on.
    Needed because local_agent_api.py falls back to next port if
    default 57821 is busy on restart.
    """
    for port in PORTS:
        try:
            requests.get(f"http://127.0.0.1:{port}/ping", timeout=1)
            return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return f"http://127.0.0.1:{PORTS[0]}"  # default if all offline


class TrayApp:

    def __init__(self):
        self.running = True
        self.api_url = find_api_url()  # resolve once on startup

        base = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base, "..", "icon.ico")

        self.icon = pystray.Icon(
            "AudioAgent",
            Image.open(icon_path),
            "AudioAgent"
        )

        self.icon.menu = pystray.Menu(
            pystray.MenuItem("Status", self.show_status),
            pystray.MenuItem("Stop Audio", self.stop_audio),
            pystray.MenuItem("Restart Service", self.restart_service),
            pystray.MenuItem("Exit", self.exit)
        )

    def start(self):
        threading.Thread(target=self._poll_status, daemon=True).start()
        self.icon.run()

    def _poll_status(self):
        while self.running:
            try:
                # Re-discover API URL each poll cycle in case service restarted
                # on a different port
                self.api_url = find_api_url()

                r = requests.get(self.api_url + "/status", timeout=2)
                r.raise_for_status()
                s = r.json()

                audio = s.get("audio") or "Idle"
                status = s.get("status", "UNKNOWN")
                pos = int(s.get("position_ms", 0) / 1000)
                mins, secs = divmod(pos, 60)
                uptime = int(s.get("uptime", 0) / 60)

                if status == "PLAYING":
                    self.icon.title = f"▶️ {audio} | {mins:02d}:{secs:02d} | Uptime: {uptime}m"
                else:
                    self.icon.title = f"⏸️ {status} | {audio} | Uptime: {uptime}m"

            except Exception:
                self.icon.title = "AudioAgent — service offline"

            time.sleep(5)

    def show_status(self):
        try:
            r = requests.get(self.api_url + "/status")
            print(r.json())
        except Exception:
            print("Agent offline")

    def stop_audio(self):
        try:
            requests.post(self.api_url + "/stop")
        except Exception:
            pass

    def restart_service(self):
        import subprocess
        result = subprocess.run(
            ["sc", "query", "AudioAgentService"],
            capture_output=True,
            text=True
        )
        if "RUNNING" in result.stdout:
            subprocess.run(["sc", "stop", "AudioAgentService"])

        time.sleep(2)

        subprocess.run(
            ["sc", "start", "AudioAgentService"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # After restart, re-discover which port the agent came up on
        time.sleep(3)
        self.api_url = find_api_url()

    def exit(self):
        self.running = False
        self.icon.stop()