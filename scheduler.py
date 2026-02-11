
"""
Audio Scheduler - Offline-capable scheduling system
Manages scheduled audio playback with local persistence
"""

import logging
from datetime import datetime, timedelta
import json
import threading
import time

logger = logging.getLogger(__name__)


class AudioScheduler:
    """Manages scheduled audio playback"""
    
    def __init__(self, on_scheduled_play=None):
        self.on_scheduled_play = on_scheduled_play
        self.schedule = []
        self.executed_items = set()  # Track executed schedule IDs
        
        logger.info("Audio scheduler initialized")
    
    def update_schedule(self, schedule_data):
        """
        Update schedule from server
        
        Args:
            schedule_data (list): List of schedule items
            
        Schedule item format:
        {
            "id": "schedule_item_id",
            "audio_name": "morning_announcement",
            "audio_url": "https://...",
            "schedule_type": "daily" | "weekly" | "once",
            "time": "09:00",  # HH:MM format
            "days": [0, 1, 2, 3, 4],  # For weekly: 0=Monday, 6=Sunday
            "date": "2026-01-20",  # For once: specific date
            "enabled": true
        }
        """
        try:
            self.schedule = schedule_data
            logger.info(f"Schedule updated: {len(schedule_data)} items")
            
            # Clear executed items when schedule updates
            self.executed_items.clear()
            
        except Exception as e:
            logger.error(f"Failed to update schedule: {e}")
    
    def check_and_execute(self):
        """Check schedule and execute due items"""
        
        logger.debug(f"[SCHEDULER] tick {datetime.now().strftime('%H:%M:%S')} schedule_count={len(self.schedule)}")

        if not self.schedule:
            return
        
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")
        current_weekday = now.weekday()  # 0=Monday, 6=Sunday
        
        for item in self.schedule:
            try:
                # Skip if disabled
                if not item.get('enabled', True):
                    continue

                play_count = int(item.get("play_count", 1))
                
                # Check if already executed (prevent duplicate plays)
                item_id = item.get('id')
                for count in range(play_count):
                    execution_key = f"{item_id}_{current_date}_{count}"

                    if execution_key in self.executed_items:
                        continue
                
                    # Check if should play now
                    if self._should_play(item, now, current_time, current_date, current_weekday):
                        
                        audio_title = item.get('audio', {}).get('title', 'Unknown')
                        logger.info(f"Triggering scheduled item: {audio_title}")
                        
                        # Mark as executed
                        self.executed_items.add(execution_key)
                    
                        # Trigger callback
                        if self.on_scheduled_play:
                            self.on_scheduled_play(item)
                    
                        # Clean old execution keys (keep only today's)
                        self._cleanup_executed_items(current_date)
                    
            except Exception as e:
                logger.error(f"Error processing schedule item: {e}")
    
    def _should_play(self, item, now, current_time, current_date, current_weekday):
        """
        Determine if schedule item should play now
        
        Args:
            item (dict): Schedule item
            now (datetime): Current datetime
            current_time (str): Current time HH:MM
            current_date (str): Current date YYYY-MM-DD
            current_weekday (int): Current weekday (0=Monday)
            
        Returns:
            bool: True if should play now
        """
        schedule_type = item.get('schedule_type', 'once')
        scheduled_time_raw = item.get('play_time', '00:00:00')
        scheduled_time = ":".join(scheduled_time_raw.split(":")[:2])
        
        # Time must match (with 1-minute tolerance)
        if not self._time_matches(current_time, scheduled_time):
            return False
        
        # # Check based on schedule type
        # if schedule_type == 'daily':
        #     return True
        
        # elif schedule_type == 'weekly':
        #     days = item.get('days', [])
        #     return current_weekday in days
        
        # elif schedule_type == 'once':
        #     scheduled_date = item.get('date', '')
        #     if not scheduled_date:
        #         # Assume today if date missing
        #         return True
        #     return current_date == scheduled_date
        
        return True
    
    def _time_matches(self, current_time, scheduled_time):
        """
        Check if current time matches scheduled time
        Allows 1-minute tolerance to avoid missing due to timing
        
        Args:
            current_time (str): Current time HH:MM
            scheduled_time (str): Scheduled time HH:MM
            
        Returns:
            bool: True if times match
        """
        try:
            # Parse times
            current_hour, current_minute = map(int, current_time.split(':'))
            scheduled_hour, scheduled_minute = map(int, scheduled_time.split(':'))
            
            # Exact match
            if current_hour == scheduled_hour and current_minute == scheduled_minute:
                return True
            
            # Allow 1-minute tolerance (in case check happens at :00:30)
            current_total = current_hour * 60 + current_minute
            scheduled_total = scheduled_hour * 60 + scheduled_minute
            
            return abs(current_total - scheduled_total) <= 1
            
        except Exception as e:
            logger.error(f"Time comparison error: {e}")
            return False
    
    def _cleanup_executed_items(self, current_date):
        """
        Remove old executed items (keep only today's)
        
        Args:
            current_date (str): Current date YYYY-MM-DD
        """
        self.executed_items = {
            key for key in self.executed_items
            if current_date in key
        }
    
    def get_next_scheduled_items(self, hours=24):
        """
        Get upcoming scheduled items
        
        Args:
            hours (int): Look ahead hours
            
        Returns:
            list: Upcoming schedule items
        """
        upcoming = []
        now = datetime.now()
        end_time = now + timedelta(hours=hours)
        
        for item in self.schedule:
            if not item.get('enabled', True):
                continue
            
            # Simple check - this could be enhanced
            upcoming.append(item)
        
        return upcoming
    
    def get_schedule_summary(self):
        """
        Get schedule summary
        
        Returns:
            dict: Schedule statistics
        """
        total = len(self.schedule)
        enabled = sum(1 for item in self.schedule if item.get('enabled', True))
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
            "executed_today": len(self.executed_items)
        }


# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    def on_play(item):
        print(f"PLAY: {item.get('audio_name')} at {item.get('time')}")
    
    print("Testing Audio Scheduler...")
    scheduler = AudioScheduler(on_scheduled_play=on_play)
    
    # Test schedule
    test_schedule = [
        {
            "id": "item1",
            "audio_name": "morning_announcement",
            "audio_url": "https://example.com/morning.mp3",
            "schedule_type": "daily",
            "time": datetime.now().strftime("%H:%M"),
            "enabled": True
        }
    ]
    
    scheduler.update_schedule(test_schedule)
    print(f"Schedule summary: {scheduler.get_schedule_summary()}")
    
    # Check execution
    scheduler.check_and_execute()