"""
Windows Audio Agent - Main Application
Runs as background service, manages audio playback and volume control
"""

import time
import logging
import threading
from pathlib import Path
from datetime import datetime
import traceback

# Core modules
from watchdog import Watchdog
from audio_controller import AudioController
from volume_controller import VolumeController
from server_client import ServerClient
from scheduler import AudioScheduler
from config_manager import ConfigManager


# --------------------------------------------------
# Logging setup
# --------------------------------------------------
log_dir = Path.home() / "AudioAgent" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / f"agent_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# Audio Agent
# --------------------------------------------------
class AudioAgent:
    """Main application controller"""

    def __init__(self):
        self.running = False

        self.watchdog = None

        self.config = None
        self.audio_controller = None
        self.volume_controller = None
        self.server_client = None
        self.scheduler = None

        # Heartbeat
        self.heartbeat_interval = 45
        self.last_heartbeat = 0

        # Playback state
        self.current_status = "IDLE"
        self.current_audio = None
        self.final_volume = 0

        # Threads
        self.heartbeat_thread = None
        self.scheduler_thread = None
        self.reconnect_thread = None

    # --------------------------------------------------
    # Initialization
    # --------------------------------------------------
    def initialize(self):
        try:
            logger.info("Initializing Audio Agent...")

            # Config
            self.config = ConfigManager()
            logger.info(f"Device ID: {self.config.device_id}")
            logger.info(f"Branch ID: {self.config.branch_id}")

            # Volume controller
            self.volume_controller = VolumeController()
            logger.info("Volume controller initialized")

            # Audio controller
            self.audio_controller = AudioController(
                cache_dir=self.config.cache_dir,
                on_playback_start=self._on_playback_start,
                on_playback_end=self._on_playback_end,
                on_playback_error=self._on_playback_error
            )
            logger.info("Audio controller initialized")

            # Scheduler
            self.scheduler = AudioScheduler(
                on_scheduled_play=self._on_scheduled_play
            )
            logger.info("Scheduler initialized")

            # Load offline schedule
            saved_schedule = self.config.load_schedule()
            if saved_schedule:
                logger.info("Loaded offline schedule from disk")
                self.scheduler.update_schedule(saved_schedule)

            # Server client
            self.server_client = ServerClient(
                base_url=self.config.server_url,
                device_id=self.config.device_id,
                branch_id=self.config.branch_id,
                token=self.config.token,
                on_volume_update=self._on_volume_update,
                on_play_command=self._on_play_command,
                on_stop_command=self._on_stop_command,
                on_schedule_update=self._on_schedule_update,
                on_audio_download=self._on_audio_download
            )
            logger.info("Server client initialized")

            # Apply initial volume
            self._apply_volume(
                self.config.master_volume,
                self.config.branch_volume
            )

            logger.info("Audio Agent initialization complete")
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            logger.error(traceback.format_exc())
            return False

    # --------------------------------------------------
    # Start / Stop
    # --------------------------------------------------
    def start(self):
        if not self.initialize():
            logger.error("Initialization failed. Exiting.")
            return

        self.running = True
        logger.info("Audio Agent started")

        # Threads
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True
        )
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True
        )
        self.reconnect_thread = threading.Thread(
            target=self._connection_loop,
            daemon=True
        )

        self.heartbeat_thread.start()
        self.scheduler_thread.start()
        self.reconnect_thread.start()

        self.watchdog = Watchdog(self)
        self.watchdog.start()

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            self.stop()

    def stop(self):
        logger.info("Stopping Audio Agent...")
        self.running = False

        if self.audio_controller:
            self.audio_controller.stop()

        if self.server_client:
            self.server_client.disconnect()

        if self.watchdog:
            self.watchdog.stop()    

        logger.info("Audio Agent stopped")

    # --------------------------------------------------
    # Background loops
    # --------------------------------------------------
    def _heartbeat_loop(self):
        while self.running:
            try:
                now = time.time()
                if now - self.last_heartbeat >= self.heartbeat_interval:
                    self._send_heartbeat()
                    self.last_heartbeat = now
                time.sleep(5)
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    def _scheduler_loop(self):
        logger.info("Scheduler thread started")
        while self.running:
            try:
                self.scheduler.check_and_execute()

                if self.watchdog:
                    self.watchdog.notify_scheduler_tick()
            except Exception:
                logger.exception("Scheduler error")
            time.sleep(1)

    def _connection_loop(self):
        while self.running:
            try:
                if not self.server_client.is_connected():
                    logger.info("Connecting to server...")
                    if self.server_client.connect():
                        logger.info("Connected to server")
                        self.current_status = "IDLE"
                    else:
                        time.sleep(30)
                else:
                    time.sleep(10)
            except Exception as e:
                logger.error(f"Connection loop error: {e}")
                time.sleep(30)

    # --------------------------------------------------
    # Heartbeat
    # --------------------------------------------------
    def _send_heartbeat(self):
        payload = {
            "deviceId": self.config.device_id,
            "branchId": self.config.branch_id,
            "status": self.current_status,
            "currentAudio": self.current_audio,
            "finalVolume": self.final_volume
        }
        self.server_client.send_heartbeat(payload)

    # --------------------------------------------------
    # Volume handling
    # --------------------------------------------------
    def _on_volume_update(self, master_volume, branch_volume):
        self._apply_volume(master_volume, branch_volume)
        self.config.update_volumes(master_volume, branch_volume)

    def _apply_volume(self, master_volume, branch_volume):
        final_volume = int((master_volume * branch_volume) / 100)
        self.final_volume = final_volume
        self.volume_controller.set_volume(final_volume)

    # --------------------------------------------------
    # Server callbacks
    # --------------------------------------------------
    def _on_play_command(self, audio_info):
        audio_name = audio_info.get("name")
        audio_url = audio_info.get("url")
        priority = audio_info.get("priority", "normal")

        if priority == "emergency":
            self.audio_controller.stop()

        path = self.audio_controller.get_cached_audio(audio_name)
        if not path and audio_url:
            path = self.audio_controller.download_audio(audio_url, audio_name)

        if path:
            self.audio_controller.play(path, audio_name)

    def _on_stop_command(self):
        self.audio_controller.stop()

    def _on_schedule_update(self, schedule_data):
        self.scheduler.update_schedule(schedule_data)
        self.config.save_schedule(schedule_data)

    def _on_audio_download(self, audio_info):
        if audio_info.get("url"):
            self.audio_controller.download_audio(
                audio_info["url"],
                audio_info.get("name")
            )

    # --------------------------------------------------
    # Scheduler callback
    # --------------------------------------------------
    def _on_scheduled_play(self, schedule_item):
        if self.current_status == "PLAYING":
            return

        audio_name = schedule_item.get("audio_name")
        audio_url = schedule_item.get("audio_url")

        path = self.audio_controller.get_cached_audio(audio_name)
        if not path and audio_url:
            path = self.audio_controller.download_audio(audio_url, audio_name)

        if path:
            self.audio_controller.play(path, audio_name)

    # --------------------------------------------------
    # Playback callbacks
    # --------------------------------------------------
    def _on_playback_start(self, audio_name):
        self.current_status = "PLAYING"
        self.current_audio = audio_name
        self._send_heartbeat()

    def _on_playback_end(self, audio_name):
        self.current_status = "IDLE"
        self.current_audio = None
        self._send_heartbeat()

    def _on_playback_error(self, audio_name, error):
        logger.error(f"Playback error for {audio_name}: {error}")
        self.current_status = "IDLE"
        self.current_audio = None
        self._send_heartbeat()


# --------------------------------------------------
# Entry point
# --------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info("Windows Audio Agent Starting")
    logger.info("=" * 60)

    agent = AudioAgent()
    try:
        agent.start()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
    finally:
        agent.stop()

    logger.info("Audio Agent exited")


if __name__ == "__main__":
    main()
