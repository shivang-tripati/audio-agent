import subprocess
import tkinter as tk
from tkinter import messagebox
import requests
from agent.device_identity import get_device_identity
from config_manager import ConfigManager


class ActivationWindow:
    def __init__(self):
        self.config = ConfigManager()
        self.identity = get_device_identity()

        self.root = tk.Tk()
        self.root.title("Audio Agent Activation")
        self.root.geometry("400x250")
        self.root.resizable(False, False)

        self._build_ui()

    def _build_ui(self):
        tk.Label(self.root, text="Device Code").pack(pady=(20, 5))
        self.device_code_entry = tk.Entry(self.root, width=40)
        self.device_code_entry.pack()

        tk.Label(self.root, text="Server URL").pack(pady=(15, 5))
        self.server_entry = tk.Entry(self.root, width=40)
        self.server_entry.insert(0, self.config.server_url)
        self.server_entry.pack()

        tk.Button(
            self.root,
            text="Activate",
            command=self.activate_device,
            width=20,
            bg="#4CAF50",
            fg="white"
        ).pack(pady=25)

    def activate_device(self):
        device_code = self.device_code_entry.get().strip()
        server_url = self.server_entry.get().strip()

        if not device_code:
            messagebox.showerror("Error", "Device code is required.")
            return

        payload = {
            "device_code": device_code,
            "device_uuid": self.identity["device_uuid"],
            "device_fingerprint": self.identity["device_fingerprint"],
            "host_name": self.identity["host_name"]
        }

        try:
            response = requests.post(
                f"{server_url}/api/devices/activate",
                json=payload,
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(response.text)

            data = response.json()["data"]

            self.config.update_server_settings(
                server_url=server_url,
                token=data["token"],
                branch_id=data["branch_id"]
            )

            messagebox.showinfo(
                "Activated",
                "Device activated successfully.\n\n"
                "Audio Agent will now run in background."
            )
            subprocess.run(["sc", "start", "AudioAgentService"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
            )
            self.root.destroy()

        except Exception as e:
            messagebox.showerror("Activation Failed", str(e))

    def run(self):
        self.root.mainloop()
