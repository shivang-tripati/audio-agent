import sys
import tkinter as tk
from tkinter import messagebox

def check_vlc_installed():
    try:
        import vlc
        test_instance = vlc.Instance()
        del test_instance
        return True
    except Exception:
        root = tk.Tk()
        root.withdraw()  # hide main window

        messagebox.showerror(
            "VLC Not Installed",
            "VLC Media Player (64-bit) is required to run Audio Agent.\n\n"
            "Please install VLC from:\n"
            "https://www.videolan.org/vlc/\n\n"
            "After installation, restart the application."
        )

        root.destroy()
        return False
