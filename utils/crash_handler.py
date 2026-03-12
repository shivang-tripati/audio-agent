import sys
import traceback
from pathlib import Path
from datetime import datetime

LOG_DIR = Path("C:/ProgramData/AudioAgent/logs")


def install_crash_handler():

    def handle_exception(exc_type, exc_value, exc_traceback):

        crash_file = LOG_DIR / "crashes.log"

        with open(crash_file, "a", encoding="utf-8") as f:
            f.write("\n\n==== CRASH ====\n")
            f.write(datetime.now().isoformat())
            f.write("\n")
            traceback.print_exception(
                exc_type, exc_value, exc_traceback, file=f)

    sys.excepthook = handle_exception
