"""
Single-instance and process-ownership tests for the packaged applications.

Two things are pinned here:

1. AudioAgentUI.exe takes a per-user-session mutex before it creates a tray
   icon, poller thread or status panel, so a duplicate launch cannot leave
   orphaned UI threads behind.

2. The "two AudioAgentService.exe processes" seen on the installed machine are
   the PyInstaller one-file bootloader parent and its child - the same
   arrangement as AudioAgentUI.exe. These tests lock that explanation to the
   actual spec files so it cannot be "fixed" by guesswork later.
"""

import os
import re
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils.single_instance import SingleInstance  # noqa: E402


def _run(script, timeout=60):
    proc = subprocess.Popen([sys.executable, "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out, err


class DuplicateTrayLaunchTest(unittest.TestCase):
    """A second AudioAgentUI.exe must exit instead of starting a second UI."""

    def _name(self, tag):
        return "Local\\AudioAgent_Test_UI_%s_%d" % (tag, os.getpid())

    def test_duplicate_ui_launch_exits_with_duplicate_code(self):
        name = self._name("dup")
        code, out, err = _run(
            "import sys; sys.path.insert(0, %r);"
            "from utils.single_instance import SingleInstance;"
            "first = SingleInstance(mode='ui', mutex_name=%r);"
            "print('FIRST', first.acquired, flush=True);"
            "second = SingleInstance(mode='ui', mutex_name=%r)"
            % (REPO_ROOT, name, name))
        self.assertIn("FIRST True", out, err)
        self.assertEqual(code, SingleInstance.DUPLICATE_EXIT_CODE,
                         "a duplicate tray launch must exit cleanly, not start a UI")

    def test_ui_mutex_is_per_user_session(self):
        """UI scope must be session-scoped so it does not collide with the worker."""
        source = open(os.path.join(REPO_ROOT, "utils", "single_instance.py"),
                      encoding="utf-8").read()
        self.assertIn("Local\\\\AudioAgent_User_", source)
        self.assertNotEqual(SingleInstance.WORKER_MUTEX_NAME,
                            SingleInstance.SERVICE_MUTEX_NAME,
                            "worker and service need separate scopes")

    def test_tray_mutex_taken_before_any_ui_resource(self):
        """main() must acquire the mutex before the activation window or TrayApp."""
        app = open(os.path.join(REPO_ROOT, "ui", "app.py"), encoding="utf-8").read()
        body = app[app.index("def main("):]
        self.assertLess(
            body.index("SingleInstance(mode=\"ui\")"),
            body.index("TrayApp().start()"),
            "the UI mutex must be taken before the tray starts")
        self.assertLess(
            body.index("SingleInstance(mode=\"ui\")"),
            body.index("ActivationWindow()"),
            "the UI mutex must be taken before any UI is shown")

    def test_ui_mutex_released_on_every_exit_path(self):
        app = open(os.path.join(REPO_ROOT, "ui", "app.py"), encoding="utf-8").read()
        body = app[app.index("def main("):]
        self.assertIn("finally:", body)
        self.assertIn("instance.release()", body)


class ServiceProcessTreeTest(unittest.TestCase):
    """
    Two AudioAgentService.exe processes (parent bootloader + child) are the
    expected shape of a PyInstaller one-file build, not a second owner.
    """

    def _spec(self, name):
        return open(os.path.join(REPO_ROOT, name), encoding="utf-8").read()

    def test_worker_is_a_one_directory_build(self):
        """AudioAgent.exe runs as a single process, so one worker = one VLC."""
        spec = self._spec("AudioAgent.spec")
        self.assertIn("COLLECT(", spec)
        self.assertIn("name='AudioAgent'", spec)

    def test_service_and_ui_are_one_file_builds(self):
        """One-file builds spawn a bootloader parent + child with the same image
        name - this is what the two-process observation actually is."""
        for spec_name, image in (("WindowsService.spec", "AudioAgentService"),
                                 ("Ui.spec", "AudioAgentUI")):
            spec = self._spec(spec_name)
            self.assertNotIn("COLLECT(", spec,
                             f"{spec_name} is expected to be a one-file build")
            self.assertRegex(spec, r"name='%s'" % image)

    def test_service_entry_point_only_dispatches_to_scm_when_asked(self):
        """Running the exe by hand must not act like a GUI app - it is the SCM
        dispatcher that fails with 1063, which is the documented behaviour."""
        service = self._spec(os.path.join("service", "windows_service.py"))
        self.assertIn("StartServiceCtrlDispatcher", service)
        self.assertRegex(service, r"if len\(sys\.argv\) == 1:")
        # No second service entry point exists: only the dispatcher path runs it.
        self.assertEqual(service.count("StartServiceCtrlDispatcher()"), 1)

    def test_only_one_service_instance_may_own_a_worker(self):
        service = self._spec(os.path.join("service", "windows_service.py"))
        body = service[service.index("def SvcDoRun"):service.index("def _wait_stop")]
        self.assertIn('mode="service"', body,
                      "SvcDoRun must take the service mutex")
        self.assertLess(body.index('mode="service"'), body.index("subprocess.Popen"),
                        "the service mutex must be owned before a worker is spawned")

    def test_supervisor_shares_the_service_lock(self):
        """The desktop shortcut launches AudioAgent.exe as a supervisor; it must
        not become a second spawner next to the Windows service."""
        supervisor = self._spec("supervisor.py")
        self.assertIn('SingleInstance(mode="service"', supervisor)
        self.assertIn("DUPLICATE_EXIT_CODE", supervisor)


if __name__ == "__main__":
    unittest.main(verbosity=2)