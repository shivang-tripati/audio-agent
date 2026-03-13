"""
Audio Controller - Audio Playback Management
Uses VLC for reliable audio playback (Windows-safe)
"""

import ctypes
import logging
import re
import threading
import time
import requests
from pathlib import Path
import sys
import os


logger = logging.getLogger(__name__)

# -----------------------------------------
# Resolve VLC runtime path
# -----------------------------------------

if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

vlc_dir = os.path.join(base_dir, "vlc")
if not os.path.exists(os.path.join(vlc_dir, "libvlc.dll")):
    vlc_dir = os.path.join(base_dir, "_internal", "vlc")
libvlc_path = os.path.join(vlc_dir, "libvlc.dll")
plugins_path = os.path.join(vlc_dir, "plugins")

if not os.path.isfile(libvlc_path):
    raise RuntimeError(f"libvlc.dll not found at: {libvlc_path}")

# -----------------------------------------
# Configure environment
# -----------------------------------------

os.environ["VLC_PLUGIN_PATH"] = plugins_path
os.environ["VLC_PLUGIN_CACHE"] = os.path.join(vlc_dir, "plugins.dat")
os.environ["PATH"] = vlc_dir + os.pathsep + os.environ.get("PATH", "")

# preload the DLL explicitly
ctypes.CDLL(libvlc_path)

# -----------------------------------------
# import python-vlc after environment setup
# -----------------------------------------

import vlc  # noqa: E402


class AudioController:
    """Manages audio playback using VLC"""

    def __init__(self, cache_dir, on_playback_start=None, on_playback_end=None, on_playback_error=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Callbacks
        self.on_playback_start = on_playback_start
        self.on_playback_end = on_playback_end
        self.on_playback_error = on_playback_error

        self.last_vlc_restart = time.time()
        self.vlc_restart_interval = 6 * 60 * 60  # every 6 hours

        self._init_audio_for_service()

        # VLC instance
        try:
            self.instance = vlc.Instance(
                "--plugin-path=" + plugins_path,
                "--no-video",
                "--quiet",
                "--aout=directsound",
                "--file-caching=1000",
                "--network-caching=1000"
            )
            self.player = self.instance.media_player_new()
        except Exception as e:
            logger.error(f"VLC initialization failed: {e}")
            raise RuntimeError("VLC initialization failed.")

        # State
        self.is_playing = False
        self.current_audio_name = None

        # --------------------------------------------------
        # FIX #4: Two flags to prevent race condition
        #
        # stop_monitoring  → tells monitor thread to exit its loop
        # _suppress_end_cb → tells monitor thread NOT to fire
        #                    on_playback_end even if it already
        #                    detected Ended/Stopped state.
        #
        # Why both? Because stop_monitoring may be set AFTER the
        # thread already read the VLC state as Ended and is about
        # to call the callback. _suppress_end_cb catches that gap.
        # --------------------------------------------------
        self.stop_monitoring = False
        self._suppress_end_cb = False

        self.monitor_thread = None

        logger.info(f"Audio controller initialized. Cache dir: {self.cache_dir}")

    def _init_audio_for_service(self):
        """Initialize audio for service mode (session 0)"""
        try:
            import psutil
            process = psutil.Process()
            if process.session_id() == 0:
                logger.info("Running in session 0 (service mode)")
                os.environ['PULSE_SERVER'] = '127.0.0.1'
                import ctypes
                ctypes.windll.ole32.CoInitializeEx(0)
        except Exception:
            pass

    # --------------------------------------------------
    # Downloading
    # --------------------------------------------------

    def download_audio(self, url, audio_name):
        """
        Download audio file to cache.
        Uses a per-filename lock to prevent two threads downloading
        the same file simultaneously — which caused WinError 32
        (file in use) when playlist engine and precache thread raced.
        """
        # Per-file lock — only one download per audio_name at a time
        if not hasattr(self, '_download_locks'):
            self._download_locks = {}
            self._download_locks_lock = threading.Lock()

        with self._download_locks_lock:
            if audio_name not in self._download_locks:
                self._download_locks[audio_name] = threading.Lock()
            file_lock = self._download_locks[audio_name]

        with file_lock:
            # Check again inside lock — another thread may have
            # already downloaded it while we were waiting
            existing = self.get_cached_audio(audio_name)
            if existing:
                logger.debug(f"Already cached (downloaded by another thread): {audio_name}")
                return existing

            try:
                clean_url = re.sub(r'([^:])//+', r'\1/', url)
                logger.info(f"Downloading from cleaned URL: {clean_url}")

                extension = Path(clean_url).suffix or ".mp3"
                final_path = self.cache_dir / f"{audio_name}{extension}"
                temp_path = final_path.with_suffix(".tmp")

                with requests.get(clean_url, stream=True, timeout=60) as response:
                    response.raise_for_status()
                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)

                temp_path.replace(final_path)
                logger.info(f"Audio downloaded: {final_path}")
                return final_path

            except Exception as e:
                logger.error(f"Failed to download audio {audio_name}: {e}")
                try:
                    if temp_path.exists():
                        temp_path.unlink()
                except Exception:
                    pass
                return None

    def get_cached_audio(self, audio_name):
        for ext in [".mp3", ".wav", ".ogg", ".m4a"]:
            path = self.cache_dir / f"{audio_name}{ext}"
            if path.exists():
                return path
        return None

    def _restart_vlc_instance(self):
        try:
            logger.info("Restarting VLC instance for stability")

            if self.player:
                try:
                    self.player.stop()
                    self.player.release()
                except Exception:
                    pass

            if self.instance:
                try:
                    self.instance.release()
                except Exception:
                    pass

            self.instance = vlc.Instance(
                "--plugin-path=" + plugins_path,
                "--no-video",
                "--quiet",
                "--aout=directsound",
                "--file-caching=1000"
            )
            self.player = self.instance.media_player_new()
            self.last_vlc_restart = time.time()
            logger.info("VLC instance restarted successfully")

        except Exception as e:
            logger.error(f"Failed to restart VLC instance: {e}")

    # --------------------------------------------------
    # Playback
    # --------------------------------------------------

    def play(self, audio_path, audio_name, seek_ms: int = 0):
        """
        Play audio file.
        seek_ms: start playback from this position (milliseconds).
        """
        if time.time() - self.last_vlc_restart > self.vlc_restart_interval:
            self._restart_vlc_instance()

        try:
            self.stop()

            audio_path = Path(audio_path)
            if not audio_path.exists():
                raise FileNotFoundError(audio_path)

            logger.info(f"Playing: {audio_name}" +
                        (f" from {seek_ms}ms" if seek_ms > 0 else ""))

            media = self.instance.media_new(str(audio_path))
            self.player.set_media(media)
            self.player.play()

            # Allow VLC to transition state
            time.sleep(0.3)
            state = self.player.get_state()

            if state in (vlc.State.Playing, vlc.State.Opening):
                if seek_ms > 0:
                    for _ in range(20):
                        if self.player.get_state() == vlc.State.Playing:
                            self.player.set_time(seek_ms)
                            break
                        time.sleep(0.2)
                    self.player.set_time(seek_ms)
                    logger.info(f"Seeked to {seek_ms}ms for audio: {audio_name}")

                self.is_playing = True
                self.current_audio_name = audio_name

                if self.on_playback_start:
                    self.on_playback_start(audio_name)

                self._start_monitoring(audio_name)
                return True

            raise RuntimeError(f"VLC failed to start, state={state}")

        except Exception as e:
            logger.error(f"Playback error: {e}")
            if self.on_playback_error:
                self.on_playback_error(audio_name, str(e))
            return False

    def stop(self):
        """
        Stop current playback.

        FIX #4: We set _suppress_end_cb BEFORE stopping VLC.
        This ensures that even if the monitor thread is mid-execution
        and already read State.Ended, it will NOT fire on_playback_end.

        Order matters:
          1. suppress flag ON
          2. stop_monitoring ON
          3. VLC stop
          4. join thread
          5. reset state
          6. suppress flag OFF  ← only after thread is fully dead
        """
        if self.is_playing:
            logger.info(f"Stopping playback: {self.current_audio_name}")

            # Step 1 & 2: Set flags BEFORE stopping VLC
            self._suppress_end_cb = True
            self.stop_monitoring = True

            # Step 3: Stop VLC
            try:
                self.player.stop()
            except Exception:
                pass

            # Step 4: Wait for monitor thread to fully exit
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=2)
                if self.monitor_thread.is_alive():
                    logger.warning("Monitor thread did not exit in time")

            # Step 5: Reset state
            self.is_playing = False
            self.current_audio_name = None

            # Step 6: Clear suppress flag AFTER thread is dead
            self._suppress_end_cb = False

    def set_volume(self, volume_percent):
        volume_percent = max(0, min(100, volume_percent))
        try:
            if self.player:
                self.player.audio_set_volume(volume_percent)
        except Exception as e:
            logger.error(f"VLC volume set failed: {e}")

    def pause(self):
        if self.is_playing:
            self.player.pause()
            logger.info(f"Playback paused: {self.current_audio_name}")

    def resume(self):
        self.player.play()
        logger.info(f"Playback resumed: {self.current_audio_name}")

    def get_position_ms(self) -> int:
        try:
            return self.player.get_time()
        except Exception as e:
            logger.error(f"Failed to get playback position: {e}")
            return 0

    def get_duration_ms(self) -> int:
        try:
            return self.player.get_length()
        except Exception as e:
            logger.error(f"Failed to get media duration: {e}")
            return 0

    # --------------------------------------------------
    # Monitoring
    # --------------------------------------------------

    def _start_monitoring(self, audio_name):
        self.stop_monitoring = False
        self._suppress_end_cb = False  # always clear before starting fresh
        self.monitor_thread = threading.Thread(
            target=self._monitor_playback,
            args=(audio_name,),
            daemon=True
        )
        self.monitor_thread.start()

    def _monitor_playback(self, audio_name):
        while not self.stop_monitoring:
            try:
                state = self.player.get_state()

                if state in (vlc.State.Ended, vlc.State.Stopped):
                    logger.info(f"Playback completed: {audio_name}")
                    self.is_playing = False

                    # FIX #4: Only fire callback if stop() didn't suppress it.
                    # Without this check, a stop() call that arrives just as
                    # VLC reaches Ended state would fire on_playback_end AND
                    # then stop() would also run downstream cleanup — double
                    # state change, mode flips to IDLE mid-schedule.
                    if not self._suppress_end_cb and self.on_playback_end:
                        self.on_playback_end(audio_name)
                    elif self._suppress_end_cb:
                        logger.debug(
                            f"[Monitor] on_playback_end suppressed for: {audio_name}"
                        )
                    return

                if state == vlc.State.Error:
                    raise RuntimeError("VLC playback error")

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Playback monitor error: {e}")
                self.is_playing = False
                if not self._suppress_end_cb and self.on_playback_error:
                    self.on_playback_error(audio_name, str(e))
                return

    # --------------------------------------------------
    # Status
    # --------------------------------------------------

    def get_status(self):
        return {
            "is_playing": self.is_playing,
            "current_audio": self.current_audio_name,
            "position_ms": self.get_position_ms(),
            "state": str(self.player.get_state())
        }

    # --------------------------------------------------
    # Schedule Sync
    # --------------------------------------------------

    def sync_schedule_files(self, schedules, server_url):
        downloaded_count = 0
        failed_count = 0
        skipped_count = 0

        for item in schedules:
            audio = item.get('audio')
            if not audio:
                continue

            audio_id = audio.get('id')
            audio_title = audio.get('title')
            relative_url = audio.get('file_url')

            if relative_url.startswith('http'):
                full_url = relative_url
            else:
                full_url = f"{server_url.rstrip('/')}/{relative_url.lstrip('/')}"

            cached_path = self.get_cached_audio(str(audio_id))
            if cached_path:
                logger.debug(f"Audio already cached: {audio_title} (ID: {audio_id})")
                skipped_count += 1
                continue

            logger.info(f"Missing file detected for: {audio_title}. Starting download...")
            result = self.download_audio(full_url, str(audio_id))

            if result:
                downloaded_count += 1
            else:
                failed_count += 1

        logger.info(
            f"Sync Complete: Downloaded={downloaded_count}, "
            f"Failed={failed_count}, Skipped={skipped_count}"
        )
        return failed_count == 0

    def is_stuck(self):
        try:
            if not self.is_playing:
                return False

            state = self.player.get_state()
            if state == vlc.State.Playing:
                pos1 = self.player.get_time()
                time.sleep(1)
                pos2 = self.player.get_time()
                if pos1 == pos2:
                    logger.warning("VLC playback stuck detected")
                    return True

            return False

        except Exception:
            return False