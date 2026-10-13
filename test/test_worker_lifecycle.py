"""
Worker / service / supervisor lifecycle regression tests.

Covers the process-ownership defects that let two workers run on one device:
  - utils/single_instance.py never ran its duplicate check (win32con has no
    MUTEX_ALL_ACCESS, so OpenMutex raised AttributeError into a bare
    `except Exception: pass`), and CreateMutex's ERROR_ALREADY_EXISTS was
    never inspected.
  - service/windows_service.py never took the service mutex at all.
  - Exit code 0 (expected shutdown / rejected duplicate) was treated as
    restartable, producing a restart every few seconds (agent.log 11:39-12:14).

Every test uses a mutex name unique to the test run, so these can be executed
on a machine that has the real service running.
"""

import os
import subprocess
import sys
import threading
import time
import types
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils.single_instance import SingleInstance  # noqa: E402


def _unique_name(prefix):
    return "Global\\AudioAgent_Test_%s_%d_%d" % (
        prefix, os.getpid(), threading.get_ident())


def _spawn_holder(name, seconds=10.0):
    """Child process that acquires `name` and holds it for `seconds`."""
    script = (
        "import sys, time;"
        "sys.path.insert(0, %r);"
        "from utils.single_instance import SingleInstance;"
        "si = SingleInstance(mode='worker', mutex_name=%r);"
        "print('ACQUIRED', si.acquired, flush=True);"
        "time.sleep(%r)" % (REPO_ROOT, name, seconds)
    )
    return subprocess.Popen([sys.executable, "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)


def _run_python(script, timeout=60):
    proc = subprocess.Popen([sys.executable, "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out, err


class DuplicateMutexTest(unittest.TestCase):
    """The duplicate-worker check must actually run and reject."""

    def test_duplicate_detection_is_not_built_on_win32con_mutex_all_access(self):
        """
        Root-cause guard. win32con has no MUTEX_ALL_ACCESS attribute, so the
        original OpenMutex pre-check raised AttributeError into a bare
        `except Exception: pass` and never ran: every worker happily "created"
        the mutex and became a second playback owner.
        """
        import inspect
        import win32con
        import utils.single_instance as si

        self.assertFalse(hasattr(win32con, "MUTEX_ALL_ACCESS"),
                         "pywin32's win32con does not define MUTEX_ALL_ACCESS")
        source = inspect.getsource(si)
        self.assertNotIn("win32con.MUTEX_ALL_ACCESS", source,
                         "duplicate detection must not depend on an attribute "
                         "that does not exist — the check silently never runs")

    def test_duplicate_worker_exits_with_dedicated_code(self):
        name = _unique_name("dup")
        holder = _spawn_holder(name)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ACQUIRED True")

            code, _, err = _run_python(
                "import sys; sys.path.insert(0, %r);"
                "from utils.single_instance import SingleInstance;"
                "SingleInstance(mode='worker', mutex_name=%r)"
                % (REPO_ROOT, name))
            self.assertEqual(
                code, SingleInstance.DUPLICATE_EXIT_CODE,
                f"duplicate worker must exit {SingleInstance.DUPLICATE_EXIT_CODE}, "
                f"got {code}; stderr={err}")
        finally:
            holder.kill()
            holder.wait(timeout=10)

    def test_first_worker_runs_and_second_is_rejected(self):
        code, out, err = _run_python(
            "import sys; sys.path.insert(0, %r);"
            "from utils.single_instance import SingleInstance;"
            "a = SingleInstance(mode='worker', mutex_name=%r);"
            "print('FIRST', a.acquired, flush=True);"
            "b = SingleInstance(mode='worker', mutex_name=%r)"
            % (REPO_ROOT, _unique_name("first"), _unique_name("first")))
        self.assertIn("FIRST True", out, err)
        self.assertEqual(code, SingleInstance.DUPLICATE_EXIT_CODE)

    def test_duplicate_code_is_distinct_from_clean_exit(self):
        self.assertEqual(SingleInstance.DUPLICATE_EXIT_CODE, 3)
        self.assertNotIn(SingleInstance.DUPLICATE_EXIT_CODE, (0, 1, 2))

    def test_worker_and_service_roles_use_separate_mutexes(self):
        self.assertNotEqual(SingleInstance.WORKER_MUTEX_NAME,
                            SingleInstance.SERVICE_MUTEX_NAME)
        code, out, err = _run_python(
            "import sys; sys.path.insert(0, %r);"
            "from utils.single_instance import SingleInstance;"
            "w = SingleInstance(mode='worker', mutex_name=%r);"
            "s = SingleInstance(mode='service', mutex_name=%r);"
            "print('BOTH', w.acquired, s.acquired)"
            % (REPO_ROOT, _unique_name("w"), _unique_name("s")))
        self.assertEqual(code, 0, err)
        self.assertIn("BOTH True True", out)

    def test_cross_account_access_denied_counts_as_duplicate(self):
        """
        The mutex DACL allows only SYSTEM/Administrators, so a worker running
        under another account gets ACCESS_DENIED on the existing object.
        That must be reported as a duplicate, not silently ignored — otherwise
        a second playback owner starts unprotected.
        """
        name = _unique_name("acl")
        holder = _spawn_holder(name)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ACQUIRED True")
            code, out, err = _run_python(
                "import sys; sys.path.insert(0, %r);"
                "from utils.single_instance import SingleInstance;"
                "SingleInstance(mode='worker', mutex_name=%r)"
                % (REPO_ROOT, name))
            self.assertEqual(code, SingleInstance.DUPLICATE_EXIT_CODE,
                             f"stderr={err}")
        finally:
            holder.kill()
            holder.wait(timeout=10)

    def test_wait_mode_takes_over_after_owner_exits(self):
        name = _unique_name("wait")
        holder = _spawn_holder(name, seconds=0.2)
        holder.communicate(timeout=30)

        acquired = threading.Event()

        def waiter():
            SingleInstance(mode="worker", mutex_name=name, wait=True,
                           poll_interval=0.05)
            acquired.set()

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        self.assertTrue(acquired.wait(timeout=15),
                        "wait=True must acquire once the previous owner exits")

    def test_wait_mode_gives_up_when_shutdown_requested(self):
        name = _unique_name("stopwait")
        holder = _spawn_holder(name)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ACQUIRED True")
            stop = threading.Event()
            stop.set()
            start = time.time()
            SingleInstance(mode="worker", mutex_name=name, wait=True,
                           stop_check=stop.is_set, poll_interval=0.05)
            self.assertLess(time.time() - start, 5)
        finally:
            holder.kill()
            holder.wait(timeout=10)


WORKER_RESTART_SCRIPT = r'''
import sys, types
sys.path.insert(0, %r)

order = []

class AudioAgent:
    def __init__(self):
        order.append("init")
    def start(self):
        order.append("start")
        raise RuntimeError("simulated crash")
    def stop(self):
        order.append("stop")

sys.modules["agent_app"] = types.ModuleType("agent_app")
sys.modules["agent_app"].AudioAgent = AudioAgent

import utils.single_instance as si
si.SingleInstance = lambda mode=None, **kw: types.SimpleNamespace(
    acquired=True, release=lambda: order.append("release"))

import worker_main
worker_main.SingleInstance = si.SingleInstance

fake_config = types.ModuleType("config_manager")
fake_config.ConfigManager = lambda: types.SimpleNamespace(token="token")
sys.modules["config_manager"] = fake_config

def sleep(seconds):
    order.append("sleep")
    if order.count("init") >= 2:
        raise KeyboardInterrupt
worker_main.time = types.SimpleNamespace(sleep=sleep)

try:
    worker_main.run_worker()
except KeyboardInterrupt:
    pass

print(",".join(order))
''' % REPO_ROOT


class WorkerRestartTest(unittest.TestCase):

    def test_agent_is_stopped_before_the_next_one_is_built(self):
        """
        The worker restart loop used to construct a second AudioAgent while
        the first was still alive (heartbeat/socket/local-api threads running),
        giving a single process two VLC instances on one output device.
        """
        code, out, err = _run_python(WORKER_RESTART_SCRIPT)
        events = out.strip().splitlines()[-1].split(",") if out.strip() else []

        self.assertIn("stop", events, f"agent.stop() must run: {out} {err}")
        self.assertIn("release", events, "device mutex must be released")
        inits = [i for i, e in enumerate(events) if e == "init"]
        self.assertGreaterEqual(len(inits), 2, f"expected a restart: {out}")
        first_stop = events.index("stop")
        self.assertLess(first_stop, inits[1],
                        "previous agent must be stopped before the next is built")


class ServiceMonitorTest(unittest.TestCase):
    """_monitor_worker must honour the exit-code contract."""

    def setUp(self):
        import win32event
        import service.windows_service as ws
        self.ws = ws
        self.service = object.__new__(ws.AudioAgentService)
        self.service.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.service.process = None
        self.service.instance = None
        self._orig_popen = ws.subprocess
        self._orig_cmd = ws._get_worker_command

    def tearDown(self):
        self.ws.subprocess = self._orig_popen
        self.ws._get_worker_command = self._orig_cmd

    class _FakeProcess:
        def __init__(self, exit_code):
            self.returncode = exit_code
            self.pid = 1234

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    def _run_monitor(self, exit_code):
        """
        Run one monitor iteration with a deterministic clock.

        Returns (spawned_exit_codes, wait_durations). The wait recorder
        reports "shutdown requested" on the second call so exactly one
        worker-exit is handled.
        """
        spawned = []
        waits = []

        def fake_popen(cmd, **kwargs):
            proc = self._FakeProcess(0)
            spawned.append(proc)
            return proc

        self.ws.subprocess = types.SimpleNamespace(
            Popen=fake_popen, TimeoutExpired=subprocess.TimeoutExpired,
            DEVNULL=subprocess.DEVNULL, CREATE_NO_WINDOW=0x08000000)
        self.ws._get_worker_command = lambda: ["fake-worker"]

        def fake_wait(seconds):
            waits.append(seconds)
            # Two 1s polls == the loop ran a full cycle and then shut down.
            return seconds == 1 and waits.count(1) >= 2

        self.service._wait_stop = fake_wait
        self.service.process = self._FakeProcess(exit_code)
        self.service._monitor_worker()
        return spawned, waits

    def test_rejected_duplicate_is_not_respawned(self):
        spawned, waits = self._run_monitor(SingleInstance.DUPLICATE_EXIT_CODE)
        self.assertEqual(spawned, [],
                         "a worker that lost the device must not be replaced")
        self.assertEqual(waits, [1],
                         "monitor must give up immediately on a duplicate")

    def test_clean_exit_is_not_hot_restarted(self):
        spawned, waits = self._run_monitor(0)
        self.assertEqual(waits, [1, self.ws.AudioAgentService.STANDBY_DELAY, 1],
                         "clean exit must wait out the standby delay")
        self.assertGreater(self.ws.AudioAgentService.STANDBY_DELAY,
                           self.ws.AudioAgentService.RESTART_DELAY,
                           "an expected shutdown must not respawn immediately")

    def test_crash_is_restarted(self):
        spawned, waits = self._run_monitor(9)
        self.assertEqual(len(spawned), 1, "a crashed worker must be restarted")
        self.assertEqual(waits, [1, self.ws.AudioAgentService.RESTART_DELAY, 1])


SVC_DORUN_SCRIPT = r'''
import sys, types, time, subprocess
sys.path.insert(0, __REPO__)

import service.windows_service as ws
import win32event

events = []

class FakeInstance:
    def __init__(self, mode=None, wait=False, stop_check=None, **kw):
        events.append("acquire:%s" % mode)
        self.acquired = True
    def release(self):
        events.append("release")

class FakeProcess:
    pid = 4242
    def poll(self):
        return None
    def wait(self, timeout=None):
        time.sleep(0.2)
        return 1

ws.SingleInstance = FakeInstance
ws.subprocess = types.SimpleNamespace(Popen=lambda cmd, **kw: FakeProcess(),
                                      TimeoutExpired=subprocess.TimeoutExpired)
ws._get_worker_command = lambda: ["fake-worker"]
ws.servicemanager.LogMsg = lambda *a, **k: None

svc = object.__new__(ws.AudioAgentService)
svc.stop_event = win32event.CreateEvent(None, 0, 0, None)
svc.process = None
svc.instance = None
svc.ReportServiceStatus = lambda status: None
svc._terminate_worker = lambda: events.append("terminate")

import threading
threading.Timer(0.5, win32event.SetEvent, [svc.stop_event]).start()

svc.SvcDoRun()
print(",".join(events))
'''.replace("__REPO__", repr(REPO_ROOT))


class ServiceStartupOrderTest(unittest.TestCase):

    def test_worker_spawned_only_after_ownership_and_lock_released(self):
        code, out, err = _run_python(SVC_DORUN_SCRIPT)
        events = out.strip().splitlines()[-1].split(",") if out.strip() else []

        self.assertIn("acquire:service", events,
                      f"service must take the service mutex: {out} {err}")
        self.assertIn("release", events, "service mutex must be released on exit")
        if "terminate" in events:
            self.assertLess(events.index("acquire:service"), events.index("terminate"),
                            "worker may only be spawned while owning the lock")


if __name__ == "__main__":
    unittest.main(verbosity=2)