import threading
import time
import logging

logger = logging.getLogger(__name__)


class SchedulerThread:
    def __init__(self, scheduler, interval=1):
        """
        Args:
            scheduler (AudioScheduler): Scheduler instance
            interval (int): seconds between checks
        """
        self.scheduler = scheduler
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True
        )

    def start(self):
        logger.info("Starting scheduler thread")
        self._thread.start()

    def stop(self):
        logger.info("Stopping scheduler thread")
        self._stop_event.set()

    def _run(self):
        logger.info("Scheduler loop running")
        while not self._stop_event.is_set():
            try:
                self.scheduler.check_and_execute()
            except Exception as e:
                logger.exception("Scheduler execution error")
            time.sleep(self.interval)
