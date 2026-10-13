"""
Tray playback control tests.

Covers the state-aware menu (PLAYING / PAUSED / IDLE / offline), which local API
endpoint each state maps to, the "confirm, don't trust the 200" rule and the
guard that stops rapid clicks from issuing conflicting commands.
"""

import os
import sys
import threading
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ui.tray_app as tray  # noqa: E402


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, bad_json=False):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self._bad_json = bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tray.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class _FakeRequests:
    """Records every HTTP call the tray makes."""

    def __init__(self, status_payload=None):
        self.calls = []
        self.status_payload = status_payload if status_payload is not None else {
            "status": "PLAYING", "audio": "track", "uptime": 60, "volume": 50,
        }
        self.post_delay = 0.0
        self.fail_post = False

        self.RequestException = tray.requests.RequestException
        self.HTTPError = tray.requests.HTTPError

    def post(self, url, timeout=None):
        self.calls.append(("POST", url))
        if self.fail_post:
            raise self.RequestException("connection refused")
        if self.post_delay:
            time.sleep(self.post_delay)
        return _FakeResponse({"ok": True})

    def get(self, url, timeout=None):
        self.calls.append(("GET", url))
        if self.fail_post:
            raise self.RequestException("connection refused")
        return _FakeResponse(self.status_payload)


def make_tray(fake, agent_status="PLAYING"):
    """Build an EnhancedTrayApp without touching Tk or the tray icon backend."""
    app = object.__new__(tray.EnhancedTrayApp)
    app.running = True
    app.api_url = "http://127.0.0.1:57821"
    app.last_status = None
    app.last_audio = None
    app.agent_status = agent_status
    app._playback_label = tray.OFFLINE_ACTION[0]
    app._status_update_count = 0
    app._command_lock = threading.Lock()

    menu_updates = []
    app.icon = types.SimpleNamespace(
        title="",
        update_menu=lambda: menu_updates.append(1),
        _menu_updates=menu_updates,
    )
    import pystray
    app._playback_item = pystray.MenuItem(
        app._playback_label, app._playback_action, enabled=False)
    app._build_menu = types.MethodType(
        tray.EnhancedTrayApp._build_menu, app)
    return app


class PlaybackActionMappingTest(unittest.TestCase):

    def test_playing_maps_to_pause(self):
        label, endpoint, enabled = tray.playback_action_for("PLAYING")
        self.assertEqual(endpoint, "/pause")
        self.assertEqual(label, "⏸ Pause Audio")
        self.assertTrue(enabled)

    def test_paused_maps_to_resume(self):
        label, endpoint, enabled = tray.playback_action_for("PAUSED")
        self.assertEqual(endpoint, "/resume")
        self.assertEqual(label, "▶ Resume Audio")
        self.assertTrue(enabled)

    def test_idle_maps_to_playlist_start(self):
        label, endpoint, enabled = tray.playback_action_for("IDLE")
        self.assertEqual(endpoint, "/playlist/start")
        self.assertEqual(label, "▶ Start Playback")
        self.assertTrue(enabled)

    def test_offline_is_disabled_and_sends_nothing(self):
        for status in ("OFFLINE", "UNKNOWN", None, ""):
            label, endpoint, enabled = tray.playback_action_for(status)
            self.assertIsNone(endpoint, f"{status} must not map to an endpoint")
            self.assertFalse(enabled)


class MenuSyncTest(unittest.TestCase):

    def setUp(self):
        self.fake = _FakeRequests()
        self._orig = tray.requests
        tray.requests = self.fake
        self.app = make_tray(self.fake)

    def tearDown(self):
        tray.requests = self._orig

    def test_menu_label_follows_reported_state(self):
        for status, expected in (
            ("PLAYING", "⏸ Pause Audio"),
            ("PAUSED", "▶ Resume Audio"),
            ("IDLE", "▶ Start Playback"),
            ("OFFLINE", tray.OFFLINE_ACTION[0]),
        ):
            self.app._sync_playback_menu(status)
            self.assertEqual(self.app._playback_item.text, expected)
            self.assertEqual(self.app.agent_status, status)

    def test_offline_menu_item_is_disabled(self):
        self.app._sync_playback_menu("PLAYING")
        self.assertTrue(self.app._playback_item.enabled)
        self.app._sync_playback_menu("OFFLINE")
        self.assertFalse(self.app._playback_item.enabled)

    def test_offline_action_sends_no_request(self):
        self.app._sync_playback_menu("OFFLINE")
        self.app._playback_action()
        self.assertEqual(self.fake.calls, [],
                         "the tray must not send commands while offline")


class CommandDispatchTest(unittest.TestCase):

    def setUp(self):
        self.fake = _FakeRequests()
        self._orig = tray.requests
        tray.requests = self.fake
        self.app = make_tray(self.fake)

    def tearDown(self):
        tray.requests = self._orig

    def _dispatch(self, state):
        self.app._sync_playback_menu(state)
        self.app._run_command(*self._expected(state), state)

    @staticmethod
    def _expected(state):
        label, endpoint, _ = tray.playback_action_for(state)
        return endpoint, label

    def test_pause_calls_pause_only(self):
        self._dispatch("PLAYING")
        posts = [url for method, url in self.fake.calls if method == "POST"]
        self.assertEqual(posts, ["http://127.0.0.1:57821/pause"])

    def test_resume_does_not_start_playlist_or_touch_worker(self):
        self._dispatch("PAUSED")
        posts = [url for method, url in self.fake.calls if method == "POST"]
        self.assertEqual(posts, ["http://127.0.0.1:57821/resume"])
        for url in self.fake.calls:
            self.assertNotIn("playlist/start", url[1])
            self.assertNotIn("sc ", url[1])

    def test_start_from_idle_uses_playlist_start(self):
        self._dispatch("IDLE")
        posts = [url for method, url in self.fake.calls if method == "POST"]
        self.assertEqual(posts, ["http://127.0.0.1:57821/playlist/start"])

    def test_command_confirms_state_with_status_after_the_call(self):
        self._dispatch("PLAYING")
        methods = [method for method, _ in self.fake.calls]
        self.assertEqual(methods, ["POST", "GET"],
                         "the tray must confirm with GET /status, not trust the POST")
        self.assertTrue(self.fake.calls[-1][1].endswith("/status"))

    def test_stop_is_kept_as_a_separate_operation(self):
        self.app._stop_audio()
        time.sleep(0.4)
        posts = [url for method, url in self.fake.calls if method == "POST"]
        self.assertEqual(posts, ["http://127.0.0.1:57821/stop"])

    def test_failed_command_is_logged_and_does_not_raise(self):
        self.fake.fail_post = True
        self._dispatch("PLAYING")
        self.assertIn("Offline", self.app.icon.title)

    def test_rapid_clicks_issue_only_one_command(self):
        self.fake.post_delay = 0.3
        self.app._sync_playback_menu("PLAYING")
        endpoint, label = self._expected("PLAYING")

        threads = [threading.Thread(
            target=self.app._run_command, args=(endpoint, label, "PLAYING"))
            for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        posts = [url for method, url in self.fake.calls if method == "POST"]
        self.assertEqual(len(posts), 1,
                         "concurrent clicks must collapse into one command")

    def test_commands_are_serialised_across_sequential_clicks(self):
        self.fake.post_delay = 0.2
        self.app._sync_playback_menu("PLAYING")
        for _ in range(3):
            self.app._run_command("/pause", "⏸ Pause Audio", "PLAYING")
        posts = [url for method, url in self.fake.calls if method == "POST"]
        self.assertEqual(len(posts), 3,
                         "sequential clicks must each be honoured")


class StatusApplicationTest(unittest.TestCase):

    def setUp(self):
        self.fake = _FakeRequests()
        self._orig = tray.requests
        tray.requests = self.fake
        self.app = make_tray(self.fake)

    def tearDown(self):
        tray.requests = self._orig

    def test_apply_status_updates_title_and_menu(self):
        self.app._apply_status({
            "status": "PAUSED", "audio": "morning.mp3",
            "uptime": 3600, "volume": 42,
        })
        self.assertEqual(self.app.last_status, "PAUSED")
        self.assertEqual(self.app._playback_item.text, "▶ Resume Audio")
        self.assertIn("Paused", self.app.icon.title)

    def test_offline_status_disables_the_action(self):
        self.app._apply_status({"status": "IDLE", "audio": None, "volume": 0})
        self.assertEqual(self.app._playback_item.text, "▶ Start Playback")
        self.app._apply_status({"status": "OFFLINE", "audio": None, "volume": 0})
        self.assertFalse(self.app._playback_item.enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)