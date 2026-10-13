"""
Shared test helpers: a fake VLC module + fake player so playback logic can be
exercised without libvlc.dll, an audio device, or a real process.

agent.audio_controller and playlist.playlist_engine both `import vlc` at module
level and agent.audio_controller loads libvlc.dll at import time, so the fake
has to be in sys.modules *before* those modules are imported.
"""

import ctypes
import os
import sys
import threading
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeState:
    # Mirrors python-vlc's State enum values.
    NothingSpecial = 0
    Opening = 1
    Buffering = 2
    Playing = 3
    Paused = 4
    Stopped = 5
    Ended = 6
    Error = 7


class FakePlayer:
    """Minimal stand-in for a libvlc media player."""

    def __init__(self, state=FakeState.Playing):
        self.state = state
        self.stop_calls = 0
        self.play_calls = 0
        self.media = None
        self.time = 0
        self.length = 1000
        self.volume = 100
        # Freeze get_state() for one thread: it reports the frozen state until
        # the thread is released, which keeps a monitor thread alive (and
        # ignorant) across stop()/play() — the real production race.
        self.frozen_threads = {}
        self.lock = threading.Lock()
        # Set before play(): the first non-main thread that polls the player
        # (i.e. the monitor thread) gets frozen on its second poll.
        self.freeze_next_monitor = False

    def block_thread(self, thread, state=FakeState.Playing):
        event = threading.Event()
        self.frozen_threads[thread] = (event, state)
        return event

    def release_thread(self, thread):
        frozen = self.frozen_threads.pop(thread, None)
        if frozen is not None:
            frozen[0].set()

    def get_state(self):
        me = threading.current_thread()
        if self.freeze_next_monitor and me is not threading.main_thread():
            self.freeze_next_monitor = False
            self.block_thread(me)
        frozen = self.frozen_threads.get(me)
        if frozen is not None and not frozen[0].is_set():
            frozen[0].wait(timeout=5)
            return frozen[1]
        with self.lock:
            return self.state

    def set_state(self, state):
        with self.lock:
            self.state = state

    def stop(self):
        self.stop_calls += 1
        self.set_state(FakeState.Stopped)

    def play(self):
        self.play_calls += 1
        self.set_state(FakeState.Playing)

    def pause(self):
        self.set_state(FakeState.Paused)

    def set_media(self, media):
        self.media = media

    def set_time(self, value):
        self.time = value

    def get_time(self):
        return self.time

    def get_length(self):
        return self.length

    def audio_set_volume(self, value):
        self.volume = value

    def release(self):
        pass


class FakeInstance:
    def __init__(self, player):
        self.player = player
        self.media = []

    def media_new(self, path):
        self.media.append(path)
        return path

    def media_player_new(self):
        return self.player

    def release(self):
        pass


def install_fake_vlc():
    """Put a fake `vlc` module in sys.modules and neutralise libvlc loading."""
    if "vlc" in sys.modules and getattr(sys.modules["vlc"], "__fake__", False):
        return sys.modules["vlc"]

    module = types.ModuleType("vlc")
    module.__fake__ = True
    module.State = FakeState

    holder = {}

    def _instance(*args, **kwargs):
        player = FakePlayer()
        holder["player"] = player
        return FakeInstance(player)

    module.Instance = _instance
    module.media_player_stop_async = lambda p: None
    sys.modules["vlc"] = module
    return module


class _FakeCtypes:
    """ctypes stand-in whose CDLL() succeeds without touching the real DLL."""

    CDLL = staticmethod(lambda *a, **k: None)
    WinDLL = staticmethod(lambda *a, **k: None)
    windll = None


def import_audio_controller():
    """Import agent.audio_controller against the fake vlc."""
    install_fake_vlc()
    real_cdll = ctypes.CDLL
    real_isfile = os.path.isfile
    ctypes.CDLL = _FakeCtypes.CDLL
    os.path.isfile = lambda path: True
    try:
        if "agent.audio_controller" in sys.modules:
            return sys.modules["agent.audio_controller"]
        sys.path.insert(0, REPO_ROOT)
        import agent.audio_controller as module
        return module
    finally:
        ctypes.CDLL = real_cdll
        os.path.isfile = real_isfile


def import_playlist_engine():
    install_fake_vlc()
    if "playlist.playlist_engine" in sys.modules:
        return sys.modules["playlist.playlist_engine"]
    sys.path.insert(0, REPO_ROOT)
    import playlist.playlist_engine as module
    return module


def make_track(audio_id, title="track", order_index=0, duration=10):
    return {
        "playlist_item_id": audio_id,
        "audio_id": audio_id,
        "title": f"{title}-{audio_id}",
        "file_url": f"http://localhost/{audio_id}.mp3",
        "duration": duration,
        "order_index": order_index,
    }


def wait_until(predicate, timeout=5.0, interval=0.01):
    """Poll predicate() until True or timeout. Returns the predicate result."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()