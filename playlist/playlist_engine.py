"""
Playlist Engine
Manages FM Radio-style continuous playlist playback.
Handles: play, loop, pause/resume, position tracking, dynamic updates.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class PlaylistTrack:
    playlist_item_id: int
    audio_id: int
    title: str
    file_url: str
    duration: int  # seconds
    order_index: int


@dataclass
class PlaylistState:
    """Saved state for schedule interrupt/resume"""
    index: int = 0
    position_ms: int = 0
    audio_id: Optional[int] = None


class PlaylistEngine:
    """
    Continuous looping playlist player.
    Integrates with AudioController for actual playback.
    """

    def __init__(self, audio_controller, on_track_start: Callable = None, on_state_change: Callable = None):
        logger.info("Initializing Playlist Engine")
        self.audio_controller = audio_controller
        # callback(track: PlaylistTrack)
        self.on_track_start = on_track_start
        self.on_state_change = on_state_change     # callback(mode: str)

        self._playlist: List[PlaylistTrack] = []
        self._lock = threading.Lock()

        self._current_index = 0
        self._is_running = False
        self._is_paused = False
        self._resume_position_ms = 0

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._skip_event = threading.Event()

    # ----------------------------------------------------------------
    # Playlist management
    # ----------------------------------------------------------------

    def update_playlist(self, raw_playlist: list):
        logger.info(
            f"[Playlist] Received playlist update: {len(raw_playlist)} tracks")
        """
        Called when PLAYLIST_UPDATE received from server.
        Handles: new tracks, removed tracks, reorders.
        If currently playing track was removed → skip to next.
        If playlist changes but current track still valid → continue playing.
        """
        new_tracks = [
            PlaylistTrack(
                playlist_item_id=item['playlist_item_id'],
                audio_id=item['audio_id'],
                title=item['title'],
                file_url=item['file_url'],
                duration=item['duration'],
                order_index=item['order_index']
            )
            for item in raw_playlist
        ]
        logger.info(
            f"[Playlist] Received playlist update with {len(new_tracks)} tracks")

        with self._lock:
            old_audio_id = self._current_track().audio_id if self._playlist else None
            self._playlist = new_tracks

            if not new_tracks:
                logger.info("[Playlist] Playlist cleared — stopping playback")
                self._is_running = False
                self._stop_event.set()
                return

            # Find new index for current track
            new_index = next(
                (i for i, t in enumerate(new_tracks) if t.audio_id == old_audio_id),
                None
            )

            if new_index is not None:
                self._current_index = new_index
                logger.info(
                    f"[Playlist] Updated playlist — current track still present at index {new_index}")
            else:
                # Current track removed → start from beginning
                self._current_index = 0
                logger.info(
                    "[Playlist] Current track removed — skipping to next")
                self._skip_event.set()

        if self._playlist and not self._is_running:
            self.start()

    def get_playlist(self) -> List[PlaylistTrack]:
        with self._lock:
            return list(self._playlist)

    # ----------------------------------------------------------------
    # Playback control
    # ----------------------------------------------------------------

    def start(self):
        logger.info("[Playlist] start() called")
        """Start playlist from current index"""
        if self._is_running:
            return
        with self._lock:
            if not self._playlist:
                logger.warning("[Playlist] No tracks to play")
                return

        self._is_running = True
        self._is_paused = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._thread.start()
        logger.info("[Playlist] Engine started")

        if self.on_state_change:
            self.on_state_change("PLAYLIST")

    def stop(self):
        """Full stop — used when agent shuts down"""
        self._is_running = False
        self._stop_event.set()
        self._skip_event.set()
        self.audio_controller.stop()
        logger.info("[Playlist] Engine stopped")

    def pause_for_schedule(self) -> PlaylistState:
        """
        Pause playlist for a schedule interrupt.
        Returns saved state so we can resume later.
        """
        self._is_paused = True

        position_ms = 0
        try:
            position_ms = self.audio_controller.get_position_ms()
        except Exception:
            pass

        with self._lock:
            track = self._current_track()
            state = PlaylistState(
                index=self._current_index,
                position_ms=position_ms,
                audio_id=track.audio_id if track else None
            )

        self.audio_controller.stop()
        logger.info(
            f"[Playlist] Paused for schedule — track={state.audio_id} pos={state.position_ms}ms")
        return state

    def resume_from_schedule(self, state: PlaylistState):
        """
        Resume playlist after schedule finishes.
        Seeks to saved position in the saved track.
        """
        self._is_paused = False

        with self._lock:
            if not self._playlist:
                logger.warning("[Playlist] Nothing to resume — playlist empty")
                return

            # Verify saved track still exists
            found_index = next(
                (i for i, t in enumerate(self._playlist)
                 if t.audio_id == state.audio_id),
                None
            )

            if found_index is not None:
                self._current_index = found_index
                self._resume_position_ms = state.position_ms
                logger.info(
                    f"[Playlist] Resuming track index={found_index} at {state.position_ms}ms")
            else:
                self._current_index = state.index % len(self._playlist)
                self._resume_position_ms = 0
                logger.info(
                    f"[Playlist] Saved track gone — resuming at index {self._current_index}")

        # Wake the play loop if it's sleeping
        self._skip_event.set()

        if not self._is_running:
            self.start()

    def get_current_state(self) -> dict:
        """For heartbeat reporting"""
        with self._lock:
            track = self._current_track()
        position_ms = 0
        try:
            position_ms = self.audio_controller.get_position_ms()
        except Exception:
            pass
        return {
            "mode": "PLAYLIST",
            "audio_id": track.audio_id if track else None,
            "title": track.title if track else None,
            "position_ms": position_ms,
            "index": self._current_index,
            "paused": self._is_paused
        }

    # ----------------------------------------------------------------
    # Internal loop
    # ----------------------------------------------------------------

    def _current_track(self) -> Optional[PlaylistTrack]:
        if not self._playlist:
            return None
        return self._playlist[self._current_index % len(self._playlist)]

    def _advance(self):
        with self._lock:
            if self._playlist:
                self._current_index = (
                    self._current_index + 1) % len(self._playlist)

    def _play_loop(self):
        logger.info("[Playlist] Play loop started")
        logger.info(f"[Playlist] Tracks available: {len(self._playlist)}")
        logger.info(
            f"[Playlist] stop_event={self._stop_event.is_set()} running={self._is_running}")
        while self._is_running and not self._stop_event.is_set():
            # Wait while paused (schedule is playing)
            while self._is_paused and self._is_running:
                time.sleep(0.2)

            if not self._is_running:
                break

            with self._lock:
                track = self._current_track()

            if not track:
                logger.info("[Playlist] No tracks — waiting...")
                time.sleep(2)
                continue

            # Get cached path
            path = self.audio_controller.get_cached_audio(str(track.audio_id))
            logger.debug(f"[Playlist] Cached path: {path}")
            if not path:
                logger.warning(
                    f"[Playlist] Track {track.audio_id} not cached — downloading...")
                from urllib.parse import urljoin
                path = self.audio_controller.download_audio(
                    track.file_url, str(track.audio_id))

            if not path:
                logger.error(
                    f"[Playlist] Failed to get audio for {track.title} — skipping")
                self._advance()
                continue

            if self.on_track_start:
                self.on_track_start(track)

            logger.info(
                f"[Playlist] ▶ Playing [{self._current_index}] {track.title}")

            # Play with optional seek position
            resume_pos = self._resume_position_ms
            self._resume_position_ms = 0

            self._skip_event.clear()
            started = self.audio_controller.play(
                path, track.title, seek_ms=resume_pos)

            if not started:
                logger.error(
                    f"[Playlist] AudioController.play returned False for {track.title}")
                self._advance()
                continue

            # Wait for track to finish or for a skip/stop signal
            duration_sec = track.duration if track.duration > 0 else 300
            wait_start = time.time()

            while self._is_running and not self._stop_event.is_set():
                if self._is_paused:
                    # Schedule interrupt — break out and let pause_for_schedule handle the stop
                    break

                # Check if skip was triggered (playlist update removed track)
                if self._skip_event.is_set():
                    self.audio_controller.stop()
                    break

                # Check VLC state
                if not self.audio_controller.is_playing:
                    break

                elapsed = time.time() - wait_start
                if elapsed >= duration_sec + 3:
                    # Safety timeout — track should be done
                    break

                time.sleep(0.3)

            if not self._is_paused and not self._skip_event.is_set():
                # Normal end → advance to next track
                self._advance()

        logger.info("[Playlist] Play loop ended")
        self._is_running = False
