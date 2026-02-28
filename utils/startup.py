import os
import sys
import win32com.client


def add_to_startup():

    startup_folder = os.path.join(
        os.environ["APPDATA"],
        r"Microsoft\Windows\Start Menu\Programs\Startup"
    )

    shortcut_path = os.path.join(startup_folder, "AudioAgent.lnk")

    # Get actual exe path

    if getattr(sys, 'frozen', False):

        exe_path = sys.executable

    else:

        exe_path = os.path.abspath(sys.argv[0])

    if os.path.exists(shortcut_path):

        print("Startup shortcut already exists")

        return

    shell = win32com.client.Dispatch("WScript.Shell")

    shortcut = shell.CreateShortCut(shortcut_path)

    shortcut.Targetpath = exe_path

    shortcut.WorkingDirectory = os.path.dirname(exe_path)

    shortcut.IconLocation = exe_path

    shortcut.save()

    print("Startup shortcut created")


def remove_from_startup():

    startup_folder = os.path.join(
        os.environ["APPDATA"],
        r"Microsoft\Windows\Start Menu\Programs\Startup"
    )

    shortcut_path = os.path.join(startup_folder, "AudioAgent.lnk")

    if os.path.exists(shortcut_path):

        os.remove(shortcut_path)
