"""
Playback Controller
Single authority for all audio playback.

Ensures:
- No race conditions
- Priority handling
- Only ONE component can play audio
"""

import threading
import logging

logger = logging.getLogger(__name__)


class PlaybackController:

    PRIORITY = {
        "PLAYLIST": 1,
        "SCHEDULE": 2,
        "MANUAL": 3,
        "EMERGENCY": 4
    }

    def __init__(self, audio_controller):
        self.audio_controller = audio_controller
        self.lock = threading.RLock()

        self.current_mode = "IDLE"
        self.current_priority = 0
        self.current_audio = None

    # --------------------------------------------------
    # Core playback
    # --------------------------------------------------

    def request_play(self, path, title, mode="PLAYLIST", seek_ms=0):
        """
        Unified playback entry point.
        """

        with self.lock:

            new_priority = self.PRIORITY.get(mode, 1)

            logger.info(
                f"[PlaybackController] request_play mode={mode} title={title}"
            )

            # Reject lower priority playback
            if new_priority < self.current_priority:
                logger.info(
                    f"[PlaybackController] Ignored due to lower priority (current={self.current_mode})"
                )
                return False

            if new_priority == self.current_priority and self.audio_controller.is_playing:
                logger.info(
                    f"[PlaybackController] Ignored due to same priority already playing (current={self.current_mode})"
                )
                return False

            # Stop current playback if needed
            if self.audio_controller.is_playing:
                logger.info(
                    f"[PlaybackController] Stopping current audio: {self.current_audio}"
                )
                self.audio_controller.stop()

            started = self.audio_controller.play(path, title, seek_ms)

            if started:
                self.current_mode = mode
                self.current_priority = new_priority
                self.current_audio = title

            return started

    # --------------------------------------------------
    # Stop playback
    # --------------------------------------------------

    def stop(self):

        with self.lock:

            if self.audio_controller.is_playing:
                logger.info(
                    f"[PlaybackController] stop() audio={self.current_audio}"
                )
                self.audio_controller.stop()

            self.current_mode = "IDLE"
            self.current_priority = 0
            self.current_audio = None

    def clear_interrupt(self):
        with self.lock:
            logger.info("[PlaybackController] Clearing interrupt state")

            self.current_mode = "IDLE"
            self.current_priority = 0
            self.current_audio = None

    # --------------------------------------------------
    # Schedule interrupt
    # --------------------------------------------------

    def interrupt_for_schedule(self, path, title):
        """
        Schedule has higher priority than playlist.
        """

        return self.request_play(
            path=path,
            title=title,
            mode="SCHEDULE",
            seek_ms=0
        )

    # --------------------------------------------------
    # Emergency playback
    # --------------------------------------------------

    def emergency_play(self, path, title):

        return self.request_play(
            path=path,
            title=title,
            mode="EMERGENCY",
            seek_ms=0
        )

    # --------------------------------------------------
    # Playlist playback
    # --------------------------------------------------

    def playlist_play(self, path, title, seek_ms=0):

        return self.request_play(
            path=path,
            title=title,
            mode="PLAYLIST",
            seek_ms=seek_ms
        )

    # --------------------------------------------------
    # Manual playback (server PLAY)
    # --------------------------------------------------

    def manual_play(self, path, title):

        return self.request_play(
            path=path,
            title=title,
            mode="MANUAL"
        )

    # --------------------------------------------------
    # State
    # --------------------------------------------------

    def get_state(self):

        return {
            "mode": self.current_mode,
            "audio": self.current_audio,
            "priority": self.current_priority
        }
