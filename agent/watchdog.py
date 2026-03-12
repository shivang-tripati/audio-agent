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
                self.check_audio_health()
            except Exception:
                logger.exception("Watchdog error")
            time.sleep(self.check_interval)

    def _check_health(self):
        now = time.time()

        self.check_audio_health()

        try:
            if self.agent.audio_controller and self.agent.audio_controller.is_stuck():
                logger.error("Audio appears stuck — restarting player")
                self.agent.audio_controller._restart_vlc_instance()
        except Exception as e:
            logger.error(f"Audio health check failed: {e}")

        # 1️⃣ Heartbeat stalled
        if self.agent.heartbeat_thread and not self.agent.heartbeat_thread.is_alive():
            logger.error("Watchdog: Heartbeat stalled")
            return

        # 2️⃣ Scheduler stalled
        if now - self.last_scheduler_tick > self.scheduler_timeout:
            logger.error("Watchdog: Scheduler stalled")
            return

        # 3️⃣ Threads dead
        if self.agent.scheduler_thread and not self.agent.scheduler_thread.is_alive():
            logger.error("Watchdog: Scheduler thread died")
            return

        if self.agent.heartbeat_thread and not self.agent.heartbeat_thread.is_alive():
            logger.error("Watchdog: Heartbeat thread died")
            return

    def check_audio_health(self):

        try:
            ac = self.agent.audio_controller
            if not ac:
                return

            if ac.is_playing:
                pos = ac.get_position_ms()
                if pos == getattr(self, "_last_pos", -1):
                    self._stuck_counter = getattr(
                        self, "_stuck_counter", 0) + 1
                else:
                    self._stuck_counter = 0

                self._last_pos = pos
                if self._stuck_counter > 6:
                    logger.error("VLC appears stuck — restarting player")

                    ac.stop()
                    ac.reinitialize_player()

                    self._stuck_counter = 0

        except Exception as e:
            logger.error(f"Audio health check failed: {e}")
