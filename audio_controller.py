"""
Audio Controller - Audio Playback Management
Uses VLC for reliable audio playback (Windows-safe)
"""

import logging
import threading
import time
import requests
from pathlib import Path
import vlc

logger = logging.getLogger(__name__)


class AudioController:
    """Manages audio playback using VLC"""

    def __init__(self, cache_dir, on_playback_start=None, on_playback_end=None, on_playback_error=None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Callbacks
        self.on_playback_start = on_playback_start
        self.on_playback_end = on_playback_end
        self.on_playback_error = on_playback_error

        # VLC instance (Windows-safe flags)
        self.instance = vlc.Instance(
            "--no-video",
            "--quiet",
            "--no-xlib",
            "--no-sub-autodetect-file"
        )
        self.player = self.instance.media_player_new()

        # State
        self.is_playing = False
        self.current_audio_name = None
        self.stop_monitoring = False
        self.monitor_thread = None

        logger.info(f"Audio controller initialized. Cache dir: {self.cache_dir}")

    # --------------------------------------------------
    # Downloading
    # --------------------------------------------------
    def download_audio(self, url, audio_name):
        try:
            logger.info(f"Downloading audio: {audio_name}")

            extension = Path(url).suffix or ".mp3"
            final_path = self.cache_dir / f"{audio_name}{extension}"
            temp_path = final_path.with_suffix(".tmp")

            with requests.get(url, stream=True, timeout=60) as response:
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
            return None

    def get_cached_audio(self, audio_name):
        for ext in [".mp3", ".wav", ".ogg", ".m4a"]:
            path = self.cache_dir / f"{audio_name}{ext}"
            if path.exists():
                return path
        return None

    # --------------------------------------------------
    # Playback
    # --------------------------------------------------
    def play(self, audio_path, audio_name):
        try:
            self.stop()

            audio_path = Path(audio_path)
            if not audio_path.exists():
                raise FileNotFoundError(audio_path)

            logger.info(f"Playing audio: {audio_name}")

            media = self.instance.media_new(str(audio_path))
            self.player.set_media(media)
            self.player.play()

            # Allow VLC to transition state
            time.sleep(0.3)
            state = self.player.get_state()

            if state in (vlc.State.Playing, vlc.State.Opening):
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
        if self.is_playing:
            logger.info(f"Stopping playback: {self.current_audio_name}")
            self.stop_monitoring = True
            self.player.stop()
            self.is_playing = False
            self.current_audio_name = None

    # --------------------------------------------------
    # Monitoring
    # --------------------------------------------------
    def _start_monitoring(self, audio_name):
        self.stop_monitoring = False
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
                    if self.on_playback_end:
                        self.on_playback_end(audio_name)
                    return

                if state == vlc.State.Error:
                    raise RuntimeError("VLC playback error")

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Playback monitor error: {e}")
                self.is_playing = False
                if self.on_playback_error:
                    self.on_playback_error(audio_name, str(e))
                return

    # --------------------------------------------------
    # Status
    # --------------------------------------------------
    def get_status(self):
        return {
            "is_playing": self.is_playing,
            "current_audio": self.current_audio_name,
            "state": str(self.player.get_state())
        }
