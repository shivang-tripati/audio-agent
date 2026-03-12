import os
import sys
import win32com.client


SHORTCUT_NAME = "AudioAgent.lnk"


def get_startup_folder():

    return os.path.join(

        os.environ["APPDATA"],

        r"Microsoft\Windows\Start Menu\Programs\Startup"

    )


def get_exe_path():

    if getattr(sys, 'frozen', False):

        return sys.executable

    else:

        return os.path.abspath(sys.argv[0])


def add_to_startup():

    try:

        startup_folder = get_startup_folder()

        shortcut_path = os.path.join(startup_folder, SHORTCUT_NAME)

        exe_path = get_exe_path()

        # ✅ ALWAYS DELETE OLD SHORTCUT

        if os.path.exists(shortcut_path):

            os.remove(shortcut_path)

            print("Old shortcut removed")

        shell = win32com.client.Dispatch("WScript.Shell")

        shortcut = shell.CreateShortCut(shortcut_path)

        shortcut.TargetPath = exe_path

        shortcut.WorkingDirectory = os.path.dirname(exe_path)

        shortcut.Arguments = ""

        shortcut.IconLocation = exe_path

        shortcut.save()

        print("Startup shortcut created:", exe_path)

    except Exception as e:

        print("Startup error:", e)


def remove_from_startup():

    try:

        shortcut_path = os.path.join(

            get_startup_folder(),

            SHORTCUT_NAME

        )

        if os.path.exists(shortcut_path):

            os.remove(shortcut_path)

            print("Startup shortcut removed")

    except Exception as e:

        print("Remove error:", e)
