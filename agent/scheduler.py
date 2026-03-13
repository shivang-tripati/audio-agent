"""
Audio Scheduler - Offline-capable scheduling system
Manages scheduled audio playback with local persistence
"""

import logging
from datetime import datetime, timedelta
import threading
import time

logger = logging.getLogger(__name__)


class AudioScheduler:
    """Manages scheduled audio playback"""

    def __init__(self, on_scheduled_play=None):
        self.on_scheduled_play = on_scheduled_play
        self.schedule = []
        self.executed_items = set()
        self._lock = threading.Lock()

        logger.info("Audio scheduler initialized")

    def update_schedule(self, schedule_data):
        """
        Update schedule from server.
        Clears executed items so updated schedule fires fresh.
        """
        try:
            with self._lock:
                self.schedule = schedule_data
                self.executed_items.clear()
            logger.info(f"Schedule updated: {len(schedule_data)} items")
        except Exception as e:
            logger.error(f"Failed to update schedule: {e}")

    def check_and_execute(self):
        """
        Check schedule and execute due items.

        FIX #6: The old code had a `for count in range(play_count)` loop
        here that called on_scheduled_play() multiple times in one tick.
        But on_scheduled_play() in main.py already spawns a thread that
        loops play_count times internally. So play_count=3 would spawn
        3 threads all fighting over the audio controller at once.

        Fix: fire on_scheduled_play ONCE per schedule item per tick.
        The play_count value is passed inside the item dict and handled
        by the schedule_worker thread in main.py.
        """
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")
        current_weekday = now.weekday()

        logger.debug(
            f"[SCHEDULER] tick {now.strftime('%H:%M:%S')} "
            f"schedule_count={len(self.schedule)}"
        )

        with self._lock:
            schedule_snapshot = list(self.schedule)

        for item in schedule_snapshot:
            try:
                if not item.get('enabled', True):
                    continue

                item_id = item.get('schedule_id')

                # FIX #6: One execution key per item per minute.
                # No play_count loop here — play_count is the
                # responsibility of schedule_worker in main.py.
                execution_key = f"{item_id}_{current_date}_{current_time}"

                with self._lock:
                    if execution_key in self.executed_items:
                        continue

                if self._should_play(item, now, current_time, current_date, current_weekday):
                    audio_title = item.get('audio', {}).get('title', 'Unknown')
                    logger.info(f"Triggering scheduled item: {audio_title}")

                    # Mark as executed BEFORE firing callback
                    # so a slow callback can't cause a double-fire
                    with self._lock:
                        self.executed_items.add(execution_key)

                    # Fire once — schedule_worker handles play_count loop
                    if self.on_scheduled_play:
                        self.on_scheduled_play(item)

                    self._cleanup_executed_items(current_date)

            except Exception as e:
                logger.error(f"Error processing schedule item: {e}")

    def _should_play(self, item, now, current_time, current_date, current_weekday):
        """
        Determine if schedule item should play now.
        """
        scheduled_time_raw = item.get('play_time', '00:00:00')
        scheduled_time = ":".join(scheduled_time_raw.split(":")[:2])

        if not self._time_matches(current_time, scheduled_time):
            return False

        return True

    def _time_matches(self, current_time, scheduled_time):
        """
        Check if current time matches scheduled time.
        Allows 1-minute tolerance to avoid missing due to timing.
        """
        try:
            current_hour, current_minute = map(int, current_time.split(':'))
            scheduled_hour, scheduled_minute = map(int, scheduled_time.split(':'))

            if current_hour == scheduled_hour and current_minute == scheduled_minute:
                return True

            current_total = current_hour * 60 + current_minute
            scheduled_total = scheduled_hour * 60 + scheduled_minute

            return abs(current_total - scheduled_total) <= 1

        except Exception as e:
            logger.error(f"Time comparison error: {e}")
            return False

    def _cleanup_executed_items(self, current_date):
        """Remove executed items from previous days"""
        with self._lock:
            self.executed_items = {
                key for key in self.executed_items
                if current_date in key
            }

    def get_next_scheduled_items(self, hours=24):
        with self._lock:
            return list(self.schedule)

    def get_schedule_summary(self):
        with self._lock:
            total = len(self.schedule)
            enabled = sum(1 for item in self.schedule if item.get('enabled', True))
            executed_today = len(self.executed_items)

        disabled = total - enabled

        by_type = {}
        for item in self.schedule:
            schedule_type = item.get('schedule_type', 'unknown')
            by_type[schedule_type] = by_type.get(schedule_type, 0) + 1

        return {
            "total": total,
            "enabled": enabled,
            "disabled": disabled,
            "by_type": by_type,
            "executed_today": executed_today
        }