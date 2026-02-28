"""
Windows Audio Agent - Main Application
Runs as background service, manages audio playback and volume control
"""

import time
import logging
import threading
from pathlib import Path
from datetime import datetime

# Core modules
from watchdog import Watchdog
from audio_controller import AudioController
from volume_controller_factory import get_volume_controller
from utils.vlc_checker import check_vlc_installed
from utils.startup import add_to_startup
from playlist.playlist_engine import PlaylistEngine, PlaylistState
from server_client import ServerClient
from scheduler import AudioScheduler
from config_manager import ConfigManager
from agent.device_identity import get_device_identity


# --------------------------------------------------
# Logging setup
# --------------------------------------------------
log_dir = Path("C:/ProgramData/AudioAgent/logs")
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
        self.playlist_engine = None

        # Heartbeat
        self.heartbeat_interval = 45
        self.last_heartbeat = 0

        # Playback state
        self.current_status = "IDLE"
        self.current_audio = None
        self.final_volume = 0

        # FM Radio state
        self._mode = "IDLE"  # "PLAYLIST" | "SCHEDULE" | "IDLE"
        self._schedule_lock = threading.Lock()
        self._schedule_playing = False
        self._saved_playlist_state: PlaylistState = None

        # Threads
        self.heartbeat_thread = None
        self.scheduler_thread = None
        self.reconnect_thread = None

        from system_tray import SystemTray
        self.tray = SystemTray(on_exit=self.stop)

    # --------------------------------------------------
    # Initialization
    # --------------------------------------------------

    def initialize(self):
        try:
            logger.info("Initializing Audio Agent...")
            if not check_vlc_installed():
                logger.error("VLC missing. Exiting.")
                return False

            # 1️⃣ Load config first
            self.config = ConfigManager()

            # 2️⃣ If no token → launch activation UI
            if not self.config.token:
                from ui.activation import ActivationWindow
                ActivationWindow().run()

            # Reload config after activation
            self.config = ConfigManager()

            if not self.config.token:
                logger.error("Activation failed or cancelled.")
                return False

            self.audio_controller = AudioController(
                cache_dir=self.config.cache_dir,
                on_playback_start=self._on_playback_start,
                on_playback_end=self._on_playback_end,
                on_playback_error=self._on_playback_error
            )
            logger.info("Audio controller initialized")

            # NEW: Initialize playlist engine
            self.playlist_engine = PlaylistEngine(
                audio_controller=self.audio_controller,
                on_track_start=self._on_playlist_track_start,
                on_state_change=self._on_playlist_state_change
            )

            # 3️⃣ Now create server client (token guaranteed)
            self.server_client = ServerClient(
                base_url=self.config.server_url,
                token=self.config.token,
                on_volume_update=self._on_volume_update,
                on_play_command=self._on_play_command,
                on_stop_command=self._on_stop_command,
                on_schedule_update=self._on_schedule_update,
                on_audio_download=self._on_audio_download,
                on_playlist_update=self._on_playlist_update
            )
            logger.info("Server client initialized")

            # 4️⃣ Connect to backend
            if not self.server_client.connect():
                logger.warning(
                    "Initial server connection failed. Will retry in background.")

            # 5️⃣ Continue rest of initialization
            identity = get_device_identity()
            logger.info(f"Device Identity: {identity}")

            self.volume_controller = get_volume_controller()
            logger.info("Volume controller initialized")

            self.scheduler = AudioScheduler(
                on_scheduled_play=self._on_scheduled_play
            )
            logger.info("Scheduler initialized")

            saved_schedule = self.config.load_schedule()
            if saved_schedule:
                logger.info("Loaded offline schedule from disk")
                self.scheduler.update_schedule(saved_schedule)

            self._apply_volume(
                self.config.master_volume,
                self.config.branch_volume
            )

            logger.info("Audio Agent initialization complete")
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            logger.exception(e)
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

        if self.tray:
            self.tray.stop()

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
        mode = self._mode
        audio_id = None
        position_ms = 0

        if mode == "PLAYLIST" and self.playlist_engine:
            state = self.playlist_engine.get_current_state()
            audio_id = state.get("audio_id")
            position_ms = state.get("position_ms", 0)
        elif mode == "SCHEDULE":
            audio_id = self.current_audio

        self.server_client.send_heartbeat(
            status=self.current_status,
            current_audio=self.current_audio,
            volume=self.final_volume,
            mode=mode,
            audio_id=audio_id,
            position_ms=position_ms
        )

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
    # NEW: Playlist callbacks
    # --------------------------------------------------

    def _on_playlist_update(self, playlist: list):
        """
        Received PLAYLIST_UPDATE from server.
        Pre-cache all audio files then update engine.
        """
        logger.info(
            f"[FM Radio] Received playlist update — {len(playlist)} tracks")

        # Download any missing tracks in background
        threading.Thread(target=self._precache_playlist,
                         args=(playlist,), daemon=True).start()

        # Update engine immediately with new playlist (will play cached tracks and skip missing ones, which will be added when download completes)
        self.playlist_engine.update_playlist(playlist)

    def _precache_playlist(self, playlist: list):
        """Download any playlist tracks not yet cached"""
        for item in playlist:
            audio_id = str(item['audio_id'])
            cached = self.audio_controller.get_cached_audio(audio_id)
            if not cached:
                logger.info(
                    f"[Cache] Downloading playlist track: {item['title']}")
                self.audio_controller.download_audio(
                    item['file_url'], audio_id)

    def _on_playlist_track_start(self, track):
        logger.info(f"[Agent] Now playing playlist track: {track.title}")
        self.current_status = "PLAYING"
        self.current_audio = track.title
        self._mode = "PLAYLIST"
        if self.tray:
            self.tray.update_status("PLAYING", track.title)
        self._send_heartbeat()

    def _on_playlist_state_change(self, mode: str):
        self._mode = mode

    # --------------------------------------------------
    # Server callbacks
    # --------------------------------------------------

    def _on_play_command(self, audio_info):
        audio_name = audio_info.get("name")
        audio_url = audio_info.get("url")
        priority = audio_info.get("priority", "normal")

        if priority == "emergency":
            if self.playlist_engine:
                self.playlist_engine.stop()
            self.audio_controller.stop()

        path = self.audio_controller.get_cached_audio(audio_name)
        if not path and audio_url:
            path = self.audio_controller.download_audio(audio_url, audio_name)

        if path:
            self.audio_controller.play(path, audio_name)

    def _on_stop_command(self):
        if self.playlist_engine:
            self.playlist_engine.stop()
        self.audio_controller.stop()
        self._mode = "IDLE"
        self.current_status = "IDLE"

    def _on_schedule_update(self, schedule_data):
        logger.info("Received schedule update from server.")
        self.audio_controller.sync_schedule_files(
            schedule_data, self.config.server_url)
        self.scheduler.update_schedule(schedule_data)
        self.config.save_schedule(schedule_data)

    def _on_audio_download(self, audio_info):
        if audio_info.get("url"):
            self.audio_controller.download_audio(
                audio_info["url"],
                audio_info.get("name")
            )

    # --------------------------------------------------
    # Scheduler handling (enhanced with playlist interrupt)
    # --------------------------------------------------
    def _on_scheduled_play(self, schedule_item):
        """
        Schedule interrupt handler.
        Priority: Schedule > Playlist
        Flow:
          1. Pause playlist (save state)
          2. Play scheduled audio (full duration × play_count)
          3. Resume playlist from saved state
        """
        with self._schedule_lock:
            if self._schedule_playing:
                logger.info(
                    "[Schedule] Already playing a schedule — queuing not supported, skipping")
                return
            self._schedule_playing = True

        # Extract data from your newly fixed JSON
        audio_data = schedule_item.get("audio", {})
        play_count = int(schedule_item.get("play_count", 1))
        duration = int(audio_data.get("duration_seconds", 0))
        audio_id = str(audio_data.get("id"))
        audio_title = audio_data.get("title")

        path = self.audio_controller.get_cached_audio(audio_id)
        if not path:
            logger.error(
                f"[Schedule] Audio {audio_id} not cached — cannot play")
            with self._schedule_lock:
                self._schedule_playing = False
            return

        def schedule_worker():
            saved_state = None
            try:
                # Step 1: Pause playlist
                if self.playlist_engine and self.playlist_engine._is_running:
                    saved_state = self.playlist_engine.pause_for_schedule()
                    logger.info(
                        f"[Schedule] Playlist paused — saved state: {saved_state}")

                 # STEP 2: Set schedule mode
                self._mode = "SCHEDULE"
                self.current_status = "PLAYING"
                self.current_audio = audio_title
                self._send_heartbeat()

                # Step 3: Play schedule audio play_count times
                for i in range(play_count):
                    logger.info(
                        f"[Schedule] ▶ {audio_title} ({i+1}/{play_count})")
                    self.audio_controller.play(path, audio_title)
                    time.sleep(duration + 1.5)

                logger.info(f"[Schedule] ✅ Finished: {audio_title}")

            except Exception as e:
                logger.error(f"[Schedule] Playback error: {e}")

            finally:
                with self._schedule_lock:
                    self._schedule_playing = False

                self.current_status = "IDLE"
                self.current_audio = None

                # Step 3: Resume playlist
                if saved_state and self.playlist_engine:
                    logger.info(
                        f"[Schedule] Resuming playlist from saved state")
                    self.playlist_engine.resume_from_schedule(saved_state)
                elif self.playlist_engine and self.playlist_engine.get_playlist():
                    # Edge case: no saved state but playlist exists
                    self.playlist_engine.start()

                self._send_heartbeat()

        threading.Thread(target=schedule_worker, daemon=True).start()

    # --------------------------------------------------
    # Playback callbacks (from AudioController)
    # --------------------------------------------------
    def _on_playback_start(self, audio_name):
        self.current_status = "PLAYING"
        self.current_audio = audio_name
        if self.tray:
            self.tray.update_status("PLAYING", audio_name)
        self._send_heartbeat()

    def _on_playback_end(self, audio_name):
        # Only reset to IDLE if not in playlist mode (playlist engine manages its own state)
        if self._mode != "PLAYLIST":
            self.current_status = "IDLE"
            self.current_audio = None
            if self.tray:
                self.tray.update_status("IDLE")
        self._send_heartbeat()

    def _on_playback_error(self, audio_name, error):
        logger.error(f"Playback error for {audio_name}: {error}")
        if self._mode != "PLAYLIST":
            self.current_status = "IDLE"
            self.current_audio = None
            if self.tray:
                self.tray.update_status("IDLE")
        self._send_heartbeat()


# --------------------------------------------------
# Entry point
# --------------------------------------------------
def main():
    logger.info("Audio Agent Starting")

    config = ConfigManager()

    # FIRST RUN
    if not config.token:
        from ui.activation import ActivationWindow
        ActivationWindow().run()

        config = ConfigManager()
        if not config.token:
            logger.info("Activation cancelled. Exiting.")
            return

        # ✅ Register auto-start ONLY after success
        add_to_startup()

    while True:
        try:
            agent = AudioAgent()
            agent.start()
        except Exception as e:
            logger.error(f"Agent crashed: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
