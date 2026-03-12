import os
import sys

if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.getcwd()

vlc_path = os.path.join(base_dir, "vlc")

os.environ["VLC_PLUGIN_PATH"] = os.path.join(vlc_path, "plugins")
os.add_dll_directory(vlc_path)
