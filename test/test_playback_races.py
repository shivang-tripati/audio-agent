"""
Playback concurrency regression tests.

Reproduces the log sequence from 2026-10-13 13:49:40-13:49:44 where a playlist
request was rejected ("same priority already playing"), the previous track
reported completion, and the next track was requested again — with two
"Now playing" callbacks 51 ms apart.

Fakes the VLC player entirely (see testhelpers) so the races are deterministic.
"""

import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from testhelpers import (  # noqa: E402
    FakeState, import_audio_controller, import_playlist_engine, make_track,
    wait_until,
)

ac_module = import_audio_controller()
pe_module = import_playlist_engine()


class _RecordingAudio:
    """Records start/end/error callbacks."""

    def __init__(self):
        self.started = []
        self.ended = []
        self.errors = []

    def on_start(self, name):
        self.started.append((name, time.time()))

    def on_end(self, name):
        self.ended.append((name, time.time()))

    def on_error(self, name, err):
        self.errors.append((name, err))


def _make_controller(events):
    tmp = tempfile.mkdtemp(prefix="audio-agent-test-")
    path = os.path.join(tmp, "track.mp3")
    with open(path, "wb") as f:
        f.write(b"x")
    controller = ac_module.AudioController(
        cache_dir=tmp,
        on_playback_start=events.on_start,
        on_playback_end=events.on_end,
        on_playback_error=events.on_error,
    )
    return controller, path


class AudioControllerSessionTest(unittest.TestCase):
    """Stale completion callbacks must not touch a newer session."""

    def setUp(self):
        self.events = _RecordingAudio()
        self.ac, self.path = _make_controller(self.events)

    def tearDown(self):
        for thread in list(self.ac.player.frozen_threads):
            self.ac.player.release_thread(thread)
        self.ac.stop()

    def test_stop_always_stops_the_player_even_when_state_is_stale(self):
        """
        stop() used to be a no-op when is_playing was False. play() calls
        stop() before swapping media, so a stale False let the old track keep
        playing underneath the new one.
        """
        self.ac.is_playing = False
        self.ac.player.set_state(FakeState.Playing)
        before = self.ac.player.stop_calls

        self.ac.stop()

        self.assertEqual(self.ac.player.stop_calls, before + 1,
                         "stop() must always stop the underlying player")

    def test_stale_monitor_cannot_end_a_newer_session(self):
        """
        Old monitor thread survives stop()'s join timeout, play() resets
        stop_monitoring/_suppress_end_cb for the new session, and the old
        thread then reports completion of the *new* session under the old
        track name. Reproduced from agent.log 13:49:43.936 / .985.
        """
        self.ac.player.set_state(FakeState.Playing)
        self.ac.player.freeze_next_monitor = True
        self.assertTrue(self.ac.play(self.path, "track-A"))

        stale_monitor = self.ac.monitor_thread
        self.assertTrue(wait_until(
            lambda: stale_monitor in self.ac.player.frozen_threads, timeout=3),
            "monitor thread should have been frozen for this race")

        # stop() cannot join the frozen monitor and gives up after its timeout.
        stopped = threading.Event()

        def stopper():
            self.ac.stop()
            stopped.set()

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        self.assertTrue(stopped.wait(timeout=15),
                        "stop() must return even when the monitor is frozen")

        # A new session starts while the old monitor thread is still frozen.
        self.assertTrue(self.ac.play(self.path, "track-B"))
        self.assertEqual(self.ac.current_audio_name, "track-B")
        self.ac.player.set_state(FakeState.Ended)

        self.ac.player.release_thread(stale_monitor)
        wait_until(lambda: not stale_monitor.is_alive(), timeout=10)
        wait_until(lambda: len(self.events.ended) >= 1, timeout=5)
        time.sleep(0.3)

        self.assertEqual([name for name, _ in self.events.ended], ["track-B"],
                         "only the current session may report completion")
        self.assertEqual(self.events.started[-1][0], "track-B")

    def test_duplicate_completion_callback_is_delivered_once(self):
        self.ac.player.set_state(FakeState.Playing)
        self.assertTrue(self.ac.play(self.path, "track-A"))
        self.ac.player.set_state(FakeState.Ended)
        wait_until(lambda: len(self.events.ended) >= 1, timeout=3)
        time.sleep(0.8)
        self.assertEqual(len(self.events.ended), 1,
                         "on_playback_end must fire exactly once per session")

    def test_stop_during_playback_fires_no_completion_callback(self):
        self.ac.player.set_state(FakeState.Playing)
        self.assertTrue(self.ac.play(self.path, "track-A"))
        self.ac.stop()
        time.sleep(0.8)
        self.assertEqual(self.events.ended, [],
                         "an explicit stop must not report playback completion")
        self.assertFalse(self.ac.is_playing)

    def test_sequential_sessions_do_not_overlap(self):
        self.ac.player.set_state(FakeState.Playing)
        self.assertTrue(self.ac.play(self.path, "track-A"))
        self.ac.stop()
        self.assertTrue(self.ac.play(self.path, "track-B"))
        self.assertFalse(self.ac.is_playing is False,
                         "second session must be the live one")
        self.assertEqual(self.ac.current_audio_name, "track-B")
        self.ac.stop()


class _FakePlaybackController:
    """Records playlist_play calls and can reject the first N of them."""

    def __init__(self):
        self.calls = []
        self.reject_until = 0

    def playlist_play(self, path, title, seek_ms=0):
        if len(self.calls) < self.reject_until:
            self.calls.append((title, False))
            return False
        self.calls.append((title, True))
        return True


class _FakePlayer:
    def __init__(self):
        self._state = FakeState.Playing

    def get_state(self):
        return self._state

    def stop(self):
        self._state = FakeState.Stopped


class _FakeAudioController:
    def __init__(self, tracks):
        self.tracks = tracks
        self.is_playing = False
        self.current_audio_name = None
        self.play_calls = []
        self.stop_calls = 0
        self.player = _FakePlayer()

    def get_cached_audio(self, audio_id):
        return self.tracks.get(str(audio_id))

    def download_audio(self, url, audio_id):
        return None

    def play(self, path, title, seek_ms=0):
        self.play_calls.append((title, seek_ms))
        self.is_playing = True
        self.current_audio_name = title
        return True

    def stop(self):
        self.stop_calls += 1
        self.is_playing = False
        self.current_audio_name = None

    def get_position_ms(self):
        return 0


class PlaylistLoopTest(unittest.TestCase):
    """A playlist engine must drive exactly one play loop."""

    def setUp(self):
        self.tracks = {str(i): "path-%d" % i for i in range(1, 5)}
        self.audio = _FakeAudioController(self.tracks)
        self.playback = _FakePlaybackController()
        self.started_tracks = []
        self.engine = pe_module.PlaylistEngine(
            playback_controller=self.playback,
            audio_controller=self.audio,
            config_manager=None,
            on_track_start=self.started_tracks.append,
        )
        self.engine._sleep_scale = 0.0

    def tearDown(self):
        self.engine.stop()

    def _raw(self, index):
        raw = make_track(index, title="t", order_index=index)
        return pe_module.PlaylistTrack(**raw)

    def test_repeated_start_calls_create_one_loop(self):
        self.engine._playlist = [self._raw(i) for i in range(1, 4)]

        loops = []
        original_loop = self.engine._play_loop

        def counting_loop():
            loops.append(threading.current_thread())
            original_loop()

        self.engine._play_loop = counting_loop

        barrier = threading.Barrier(8)

        def starter():
            barrier.wait()
            self.engine.start()

        threads = [threading.Thread(target=starter) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        wait_until(lambda: len(loops) >= 1, timeout=3)
        time.sleep(0.5)  # give a second loop time to appear if it exists

        self.assertTrue(self.engine._is_running)
        self.assertEqual(len(loops), 1,
                         "concurrent start() calls must produce a single play loop")
        self.assertEqual(len({t.name for t in loops}), 1)

    def test_start_then_stop_then_start_keeps_one_loop(self):
        self.engine._playlist = [self._raw(i) for i in range(1, 4)]
        self.engine.start()
        first_thread = self.engine._thread
        self.engine.stop()
        self.assertFalse(first_thread.is_alive(),
                         "stop() must join the play loop")
        self.engine.start()
        self.assertIsNot(self.engine._thread, first_thread)
        wait_until(lambda: self.engine._thread.is_alive(), timeout=2)

    def test_rejected_request_retries_after_completion(self):
        """
        The 13:49:40 sequence: request rejected while the previous session is
        still playing, previous session completes, retry succeeds — and only
        one session is ever live.
        """
        self.engine._playlist = [self._raw(1)]
        self.playback.reject_until = 1
        self.engine._skip_event.set()  # stop the loop after the retry

        self.engine._is_running = True
        t = threading.Thread(target=self.engine._play_loop, daemon=True)
        t.start()
        t.join(timeout=10)

        titles = [title for title, _ in self.playback.calls]
        self.assertGreaterEqual(len(titles), 2,
                                "the rejected request must be retried")
        self.assertEqual(titles[1], titles[0],
                         "the retry must target the same track")
        self.assertFalse(self.playback.calls[0][1], "first attempt rejected")
        self.assertTrue(self.playback.calls[-1][1], "retry must succeed")


class PlaybackControllerPriorityTest(unittest.TestCase):
    """request_play() must be atomic and honour priority semantics."""

    class _Audio:
        def __init__(self):
            self.is_playing = False
            self.starts = []
            self.stops = 0
            self.lock = threading.Lock()

        def play(self, path, title, seek_ms=0):
            with self.lock:
                self.starts.append(title)
                self.is_playing = True
            return True

        def stop(self):
            self.stops += 1
            self.is_playing = False

    def setUp(self):
        from agent.playback_controller import PlaybackController
        self.audio = self._Audio()
        self.controller = PlaybackController(self.audio)

    def _concurrent(self, titles, mode="PLAYLIST"):
        results = []
        barrier = threading.Barrier(len(titles))

        def worker(title):
            barrier.wait()
            results.append(self.controller.request_play(
                "path", title, mode=mode))

        threads = [threading.Thread(target=worker, args=(t,)) for t in titles]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        return results

    def test_concurrent_same_track_starts_one_session(self):
        results = self._concurrent(["same"] * 8)
        self.assertEqual(len([r for r in results if r]), 1,
                         "only one session may start for concurrent identical requests")
        self.assertEqual(self.audio.starts, ["same"])

    def test_concurrent_different_tracks_start_at_most_one(self):
        results = self._concurrent([f"track-{i}" for i in range(8)])
        self.assertLessEqual(len([r for r in results if r]), 1,
                             "same-priority concurrency must not open many sessions")

    def test_lower_priority_is_rejected(self):
        self.assertTrue(self.controller.request_play("p", "playlist", mode="PLAYLIST"))
        self.assertFalse(self.controller.request_play("p", "playlist2", mode="PLAYLIST"))
        self.assertEqual(self.audio.starts, ["playlist"])


if __name__ == "__main__":
    unittest.main(verbosity=2)