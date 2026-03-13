from utils.logger import setup_logging
import time
import logging
import threading
from pathlib import Path
from datetime import datetime
import sys
import traceback
import multiprocessing

from agent.watchdog import Watchdog
from agent.audio_controller import AudioController
from volume_controller_factory import get_volume_controller
from utils.vlc_checker import check_vlc_installed
from utils.startup import add_to_startup
from playlist.playlist_engine import PlaylistEngine, PlaylistState
from agent.server_client import ServerClient
from agent.scheduler import AudioScheduler
from config_manager import ConfigManager
from agent.device_identity import get_device_identity
from agent.playback_controller import PlaybackController
from api.local_agent_api import LocalAgentAPI

multiprocessing.freeze_support()

setup_logging("agent")
logger = logging.getLogger(__name__)


def handle_exception(exc_type, exc_value, exc_traceback):
    logger.error("Uncaught exception", exc_info=(
        exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception


class AudioAgent:
    """Main application controller"""

    def __init__(self):
        self.running = False
        self.system_ready = False
        self.start_time = time.time()

        self.watchdog = None

        self.config = None
        self.audio_controller = None
        self.volume_controller = None
        self.server_client = None
        self.scheduler = None
        self.playlist_engine = None
        self.local_api = None

        # Heartbeat
        self.heartbeat_interval = 45
        self.last_heartbeat = 0

        # Playback state
        self.current_status = "IDLE"
        self.current_audio = None
        self.final_volume = 0

        # Mode
        self._mode = "IDLE"  # "PLAYLIST" | "SCHEDULE" | "IDLE"
        self._schedule_lock = threading.Lock()
        self._schedule_playing = False
        self._saved_playlist_state: PlaylistState = None

        # FIX #8: Use threading.Lock() instead of manual acquire/locked checks.
        # The old code used a raw Lock with manual .locked() checks and
        # .acquire() calls but NEVER called .release() in _precache_playlist.
        # Result: after the first playlist update the lock was permanently held
        # and all subsequent playlist updates silently skipped precaching.
        self._precache_lock = threading.Lock()

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
            if not check_vlc_installed():
                logger.error("VLC missing. Exiting.")
                return False

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

            self.volume_controller = get_volume_controller()
            logger.info("Volume controller initialized")

            self.playback_controller = PlaybackController(
                self.audio_controller)

            self.playlist_engine = PlaylistEngine(
                playback_controller=self.playback_controller,
                audio_controller=self.audio_controller,
                config_manager=self.config,
                on_track_start=self._on_playlist_track_start,
                on_state_change=self._on_playlist_state_change
            )

            self.local_api = LocalAgentAPI(self)
            logger.info("Local API initialized")
            self.local_api.start()

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

            if not self.server_client.connect():
                logger.warning(
                    "Initial server connection failed. Will retry in background.")

            identity = get_device_identity()
            logger.info(f"Device Identity: {identity}")

            self.scheduler = AudioScheduler(
                on_scheduled_play=self._on_scheduled_play
            )
            logger.info("Scheduler initialized")

            saved_schedule = self.config.load_schedule()
            if saved_schedule:
                logger.info("Loaded offline schedule from disk")
                if self.scheduler:
                    self.scheduler.update_schedule(saved_schedule)

            self._apply_volume(
                self.config.master_volume,
                self.config.branch_volume
            )

            self.system_ready = True

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

        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True)
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True)
        self.reconnect_thread = threading.Thread(
            target=self._connection_loop, daemon=True)

        self.heartbeat_thread.start()
        self.scheduler_thread.start()
        self.reconnect_thread.start()

        self.watchdog = Watchdog(self)
        self.watchdog.start()

        try:
            while self.running:
                time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            self.stop()

    def stop(self):
        logger.info("Stopping Audio Agent...")
        self.running = False

        if self.playlist_engine:
            self.playlist_engine.stop()

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
            time.sleep(5)

    def _connection_loop(self):
        while self.running:
            try:
                if self.server_client and not self.server_client.is_connected():
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
        if not self.system_ready:
            return

        mode = self._mode
        audio_id = None
        position_ms = 0

        if mode == "PLAYLIST" and self.playlist_engine:
            state = self.playlist_engine.get_current_state()
            audio_id = state.get("audio_id")
            position_ms = state.get("position_ms", 0)
        elif mode == "SCHEDULE":
            audio_id = self.current_audio

        actual_volume = 0
        if self.volume_controller:
            try:
                actual_volume = self.volume_controller.get_volume()
            except Exception as e:
                logger.error(f"Failed to get actual volume: {e}")

        self.final_volume = actual_volume

        if self.server_client:
            self.server_client.send_heartbeat(
                status=self.current_status,
                current_audio=self.current_audio,
                volume=actual_volume,
                mode=mode,
                audio_id=audio_id,
                position_ms=position_ms
            )

    # --------------------------------------------------
    # Volume
    # --------------------------------------------------

    def _on_volume_update(self, master_volume, branch_volume):
        self._apply_volume(master_volume, branch_volume)
        self.config.update_volumes(master_volume, branch_volume)

    def _apply_volume(self, master_volume, branch_volume):
        final_volume = int((master_volume * branch_volume) / 100)
        if self.audio_controller:
            self.audio_controller.set_volume(final_volume)

    # --------------------------------------------------
    # Playlist callbacks
    # --------------------------------------------------

    def _on_playlist_update(self, playlist: list):
        """
        Received PLAYLIST_UPDATE from server.
        FIX #8: Use non_blocking acquire() so we never deadlock if a
        precache is already in progress. If locked, the new playlist
        still gets sent to the engine immediately — only the background
        download is skipped until the current one finishes.
        """
        logger.info(
            f"[FM Radio] Received playlist update — {len(playlist)} tracks")

        # Update engine immediately regardless of cache state
        if self.playlist_engine:
            self.playlist_engine.update_playlist(playlist)

        # FIX #8: non_blocking=True means we skip spawning a new download
        # thread if one is already running. No deadlock, no silent skip.
        acquired = self._precache_lock.acquire(blocking=False)
        if acquired:
            threading.Thread(
                target=self._precache_playlist,
                args=(playlist,),
                daemon=True
            ).start()
        else:
            logger.info(
                "[Cache] Precache already in progress — skipping duplicate download"
            )

    def _precache_playlist(self, playlist: list):
        """
        Download any playlist tracks not yet cached.
        FIX #8: Always releases lock in finally block so subsequent
        playlist updates can trigger downloads again.
        """
        try:
            for item in playlist:
                audio_id = str(item['audio_id'])
                cached = self.audio_controller.get_cached_audio(audio_id)
                if not cached:
                    logger.info(
                        f"[Cache] Downloading playlist track: {item['title']}")
                    self.audio_controller.download_audio(
                        item['file_url'], audio_id)
        except Exception as e:
            logger.error(f"[Cache] Precache error: {e}")
        finally:
            # FIX #8: This was completely missing before.
            # Without this, the lock was held forever after the first
            # playlist update and all future downloads were silently skipped.
            self._precache_lock.release()
            logger.debug("[Cache] Precache lock released")

    def _on_playlist_track_start(self, track):
        logger.info(f"[Agent] Now playing playlist track: {track.title}")
        self._apply_volume(self.config.master_volume,
                           self.config.branch_volume)
        self.current_status = "PLAYING"
        self.current_audio = track.title
        self._mode = "PLAYLIST"
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
            self.playback_controller.manual_play(path, audio_name)

    def _on_stop_command(self):
        if self.playlist_engine:
            self.playlist_engine.stop()
        self.playback_controller.stop()
        self._mode = "IDLE"
        self.current_status = "IDLE"

    def _on_schedule_update(self, schedule_data):
        logger.info("Received schedule update from server.")
        self.audio_controller.sync_schedule_files(
            schedule_data, self.config.server_url)
        if self.scheduler:
            self.scheduler.update_schedule(schedule_data)
        self.config.save_schedule(schedule_data)

    def _on_audio_download(self, audio_info):
        if audio_info.get("url"):
            self.audio_controller.download_audio(
                audio_info["url"],
                audio_info.get("name")
            )

    # --------------------------------------------------
    # Scheduler handling
    # --------------------------------------------------

    def _on_scheduled_play(self, schedule_item):
        with self._schedule_lock:
            if self._schedule_playing:
                logger.info(
                    "[Schedule] Already playing a schedule — skipping")
                return
            self._schedule_playing = True

        audio_data = schedule_item.get("audio", {})
        play_count = int(schedule_item.get("play_count", 1))
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
                if self.playlist_engine and self.playlist_engine._is_running:
                    saved_state = self.playlist_engine.pause_for_schedule()
                    logger.info(
                        f"[Schedule] Playlist paused — saved state: {saved_state}")

                self._mode = "SCHEDULE"
                self.current_status = "PLAYING"
                self.current_audio = audio_title
                self._send_heartbeat()

                for i in range(play_count):
                    logger.info(
                        f"[Schedule] ▶ {audio_title} ({i+1}/{play_count})")
                    started = self.playback_controller.interrupt_for_schedule(
                        path, audio_title)
                    if not started:
                        logger.error(
                            f"[Schedule] Failed to play {audio_title} — aborting")
                        break
                    self.wait_for_playback_completion(audio_title)

                logger.info(f"[Schedule] ✅ Finished: {audio_title}")

            except Exception as e:
                logger.error(f"[Schedule] Playback error: {e}")

            finally:
                with self._schedule_lock:
                    self._schedule_playing = False

                if self.playback_controller:
                    self.playback_controller.clear_interrupt()

                if saved_state and self.playlist_engine:
                    self.playlist_engine.resume_from_schedule(saved_state)
                    time.sleep(0.4)
                    self._mode = "PLAYLIST"
                    self.current_status = "PLAYING"

                elif self.playlist_engine and self.playlist_engine.get_playlist():
                    self.playlist_engine.start()
                    time.sleep(0.3)
                    self._mode = "PLAYLIST"
                    self.current_status = "PLAYING"

                else:
                    self._mode = "IDLE"
                    self.current_status = "IDLE"

                self.current_audio = None
                self._send_heartbeat()

        threading.Thread(target=schedule_worker, daemon=True).start()

    # --------------------------------------------------
    # Playback callbacks
    # --------------------------------------------------

    def _on_playback_start(self, audio_name):
        self.current_status = "PLAYING"
        self.current_audio = audio_name
        self._send_heartbeat()

    def _on_playback_end(self, audio_name):
        logger.info(f"[Agent] Playback ended: {audio_name}")

        if self._mode == "SCHEDULE":
            logger.info(
                "[Agent] Schedule playback ended — scheduler will resume playlist")
            return

        if self._mode == "PLAYLIST":
            logger.debug(
                "[Agent] Playlist track ended — playlist engine advancing")
            return

        self.current_status = "IDLE"
        self.current_audio = None
        self._send_heartbeat()

    def _on_playback_error(self, audio_name, error):
        logger.error(f"Playback error for {audio_name}: {error}")
        if self._mode != "PLAYLIST":
            self.current_status = "IDLE"
            self.current_audio = None
        self._send_heartbeat()

    def wait_for_playback_completion(self, audio_name, timeout=3600):
        start = time.time()
        while self.running and self.audio_controller.is_playing:
            if time.time() - start > timeout:
                logger.warning(
                    f"[Schedule] Timeout waiting for playback: {audio_name}")
                break
            time.sleep(0.2)
        logger.info(f"[Schedule] ✅ Schedule completed: {audio_name}")


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def main():
    logger.info("Audio Agent Starting")

    while True:
        try:
            agent = AudioAgent()
            agent.start()
        except Exception as e:
            logger.error(f"Agent crashed: {e}")
            time.sleep(5)
