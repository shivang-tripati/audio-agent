import time
import os
import sys
import logging
import threading

logger = logging.getLogger(__name__)


class Watchdog:
    """
    Watchdog to monitor agent health and restart if needed
    """

    def __init__(
        self,
        agent,
        heartbeat_timeout=120,
        scheduler_timeout=120,
        check_interval=10
    ):
        self.agent = agent
        self.heartbeat_timeout = heartbeat_timeout
        self.scheduler_timeout = scheduler_timeout
        self.check_interval = check_interval

        self.last_scheduler_tick = time.time()
        self.running = False

        self.thread = threading.Thread(
            target=self._run,
            daemon=True
        )

    def start(self):
        logger.info("Watchdog started")
        self.running = True
        self.thread.start()

    def stop(self):
        self.running = False

    def notify_scheduler_tick(self):
        """Called by scheduler loop"""
        self.last_scheduler_tick = time.time()

    def _run(self):
        while self.running:
            try:
                self._check_health()
            except Exception:
                logger.exception("Watchdog error")
            time.sleep(self.check_interval)

    def _check_health(self):
        now = time.time()

        # 1️⃣ Heartbeat stalled
        if now - self.agent.last_heartbeat > self.heartbeat_timeout:
            logger.error("Watchdog: Heartbeat stalled")
            self._restart_agent("Heartbeat timeout")
            return

        # 2️⃣ Scheduler stalled
        if now - self.last_scheduler_tick > self.scheduler_timeout:
            logger.error("Watchdog: Scheduler stalled")
            self._restart_agent("Scheduler timeout")
            return

        # 3️⃣ Threads dead
        if not self.agent.scheduler_thread.is_alive():
            logger.error("Watchdog: Scheduler thread died")
            self._restart_agent("Scheduler thread dead")
            return

        if not self.agent.heartbeat_thread.is_alive():
            logger.error("Watchdog: Heartbeat thread died")
            self._restart_agent("Heartbeat thread dead")
            return

    def _restart_agent(self, reason):
        logger.critical(f"Watchdog restarting agent: {reason}")

        try:
            self.agent.stop()
            time.sleep(2)
        except Exception:
            pass

        # HARD restart (exe-safe)
        python = sys.executable
        os.execl(python, python, *sys.argv)
