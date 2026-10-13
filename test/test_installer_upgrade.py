"""
Validation for the installer upgrade sequence, the build script and the tray
service-restart race.

The installer is Pascal Script that cannot be exercised without Inno Setup and
a Windows service, so these checks assert the lifecycle *contract* of the script
rather than running it. The failure they exist to prevent: the upgrade path
falling back to "taskkill the service", which makes the SCM's failure-recovery
policy restart the old instance while binaries are being replaced.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INSTALLER = os.path.join(REPO_ROOT, "AudioAgentInstaller", "installer.iss")
BUILD_BAT = os.path.join(REPO_ROOT, "build.bat")
TRAY = os.path.join(REPO_ROOT, "ui", "tray_app.py")
README = os.path.join(REPO_ROOT, "README.md")


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def installer_section(text, name):
    """Return the body of an Inno Setup [Section]."""
    match = re.search(r"^\[%s\]\s*$(.*?)(?=^\[|\Z)" % re.escape(name),
                      text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def installer_function(text, name):
    """Return the body of a Pascal Script function/procedure."""
    match = re.search(
        r"^(?:function|procedure)\s+%s\b.*?;$(.*?)^end;" % re.escape(name),
        text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else ""


class InstallerUpgradeSequenceTest(unittest.TestCase):

    def setUp(self):
        self.text = read(INSTALLER)
        self.lower = self.text.lower()
        self.code = installer_section(self.text, "Code")
        self.run = installer_section(self.text, "Run")

    def test_run_section_does_not_force_kill_the_service(self):
        """
        Force-killing the service is what triggers the SCM recovery restart.
        It must not be part of the upgrade path; in [UninstallRun] it may only
        survive as last-resort cleanup after a graceful stop.
        """
        for line in self.run.splitlines():
            if "taskkill" in line.lower():
                image = line.lower().split("/im ")[-1]
                self.assertNotIn("audioagentservice", image,
                                 "[Run] must not force-kill the service")
                self.assertNotIn("audioagent.exe", image,
                                 "[Run] must not force-kill the worker")

        uninstall = installer_section(self.text, "UninstallRun").lower()
        if "audioagentservice.exe" in uninstall:
            self.assertGreaterEqual(uninstall.find("sc delete"), 0)

    def test_uninstall_stops_the_service_before_any_kill(self):
        lines = installer_section(self.text, "UninstallRun").splitlines()
        delete_pos = next((i for i, l in enumerate(lines)
                           if "sc delete" in l.lower()), None)
        self.assertIsNotNone(delete_pos, "the uninstaller must delete the service")
        for i, line in enumerate(lines):
            if "taskkill" in line.lower() and "audioagentservice" in line.lower():
                self.assertLess(
                    delete_pos, i,
                    "last-resort kill must come after sc delete, and the "
                    "graceful stop happens earlier in CurUninstallStepChanged")

    def test_service_stop_is_graceful_and_bounded(self):
        stop = installer_function(self.code, "StopServiceForUpgrade")
        self.assertIn("'stop ' + AgentServiceName", stop,
                      "must use sc stop, not a kill")
        self.assertIn("WaitForServiceState(ServiceStopped, StopTimeoutMs)", stop,
                      "must wait (bounded) for the service to reach STOPPED")

        self.assertRegex(self.code, r"StopTimeoutMs\s*=\s*\d+",
                         "the stop wait must have an explicit timeout")

    def test_worker_exit_is_awaited_before_files_are_replaced(self):
        stop = installer_function(self.code, "StopServiceForUpgrade")
        self.assertIn("WaitForWorkerExit(WorkerExitTimeoutMs)", stop,
                      "the worker process must be gone before binaries change")
        self.assertIn("AgentWorkerImage", stop)

    def test_stop_failure_aborts_instead_of_killing(self):
        """Interactive and silent installs must both abort, with a diagnostic."""
        self.assertIn("StopServiceForUpgrade", installer_function(self.code, "CurPageChanged"))
        self.assertIn("RaiseException(StopFailureMessage)",
                      installer_function(self.code, "CurPageChanged"))

        init = installer_function(self.code, "InitializeSetup")
        self.assertIn("StopServiceForUpgrade", init)
        self.assertIn("StopFailureMessage", init)

        message = installer_function(self.code, "StopFailureMessage")
        self.assertIn("sc stop", message,
                      "the diagnostic must tell the user how to stop the service")

    def test_stop_happens_before_files_are_copied(self):
        """The shutdown hook must run before [Files], not after."""
        self.assertIn("CurPageChanged", self.code,
                      "a pre-copy shutdown hook must exist")
        hook = installer_function(self.code, "CurPageChanged")
        self.assertIn("StopServiceForUpgrade", hook)
        self.assertNotIn("ssPostInstall", hook)
        self.assertNotIn("ssInstall", hook)

    def test_service_start_is_verified_and_can_abort(self):
        start = installer_function(self.code, "StartServiceAndVerify")
        self.assertIn("'start ' + AgentServiceName", start)
        self.assertIn("WaitForServiceState(ServiceRunning, StartTimeoutMs)", start)

        post = installer_function(self.code, "CurStepChanged")
        self.assertIn("StartServiceAndVerify", post)
        self.assertIn("RaiseException(StartFailureMessage)", post)

    def test_recovery_policy_is_restored_on_every_path(self):
        """Recovery must not be left disabled by the installer."""
        restore = installer_function(self.code, "RestoreRecoveryPolicy")
        self.assertIn("'failure ' + AgentServiceName", restore)
        self.assertIn("restart/5000", restore,
                      "the intended policy is the one this installer configures")

        post = installer_function(self.code, "CurStepChanged")
        self.assertGreaterEqual(
            post.count("RestoreRecoveryPolicy"), 2,
            "policy must be restored on both the success and the failure path")

    def test_tray_is_launched_only_after_the_service_serves(self):
        post = installer_function(self.code, "CurStepChanged")
        start_pos = post.index("StartServiceAndVerify")
        tray_pos = post.index("AudioAgentUI.exe")
        self.assertLess(start_pos, tray_pos,
                        "the tray must start after the service is verified")

    def test_uninstall_stops_the_service_gracefully(self):
        self.assertIn("StopServiceForUpgrade",
                      installer_function(self.code, "CurUninstallStepChanged"))
        body = installer_section(self.text, "UninstallRun")
        self.assertNotIn('Parameters: "stop"',
                         "the stop is handled in code with a bounded wait")

    def test_user_data_is_never_deleted(self):
        for line in installer_section(self.text, "UninstallDelete").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                continue  # commented-out entry - not active
            for protected in ("\\config", "\\audio_cache", "\\logs"):
                self.assertNotIn(
                    protected, stripped,
                    "the installer must not delete user configuration or logs")


class BuildScriptTest(unittest.TestCase):

    def setUp(self):
        self.text = read(BUILD_BAT)
        self.lower = self.text.lower()
        self.upper = self.text.upper()

    def test_builds_all_three_committed_specs(self):
        for spec in ("AudioAgent.spec", "WindowsService.spec", "Ui.spec"):
            self.assertIn(spec, self.text, f"{spec} must be built")
            self.assertRegex(
                self.text,
                r"%PYINSTALLER%\s+--noconfirm\s+--clean\s+" + re.escape(spec),
                f"{spec} must be passed to pyinstaller")

    def test_never_deletes_spec_files(self):
        self.assertNotIn("del audiosagent.spec", self.lower)
        for line in self.text.splitlines():
            lowered = line.lower()
            if lowered.strip().startswith("rem") or lowered.strip().startswith(";"):
                continue
            if "del " in lowered or "rmdir" in lowered or "rd " in lowered:
                self.assertNotIn(".spec", lowered,
                                 "the build must not remove committed .spec files")

    def test_preserves_worker_onedir_layout_and_vlc(self):
        self.assertIn("dist\\AudioAgent\\_internal", self.text)
        self.assertIn("_internal\\vlc\\libvlc.dll", self.text,
                      "the VLC runtime must be verified in the payload")

    def test_stages_service_and_ui_next_to_worker_payload(self):
        self.assertIn('copy /Y "dist\\AudioAgentService.exe" "dist\\AudioAgent\\"', self.text)
        self.assertIn('copy /Y "dist\\AudioAgentUI.exe" "dist\\AudioAgent\\"', self.text)
        self.assertIn("AudioAgentInstaller\\dist\\AudioAgent", self.text)

    def test_mirrors_staging_dir(self):
        self.assertIn('xcopy "dist\\AudioAgent\\*" "%STAGE%\\"', self.text)

    def test_checks_exit_codes(self):
        checks = self.lower.count("if errorlevel 1")
        self.assertGreaterEqual(checks, 6,
                                "every build/compile step must be error-checked")

    def test_compiles_installer_with_iscc_and_reports_when_missing(self):
        self.assertIn("ISCC", self.upper)
        self.assertIn("installer.iss", self.text)
        self.assertIn("Inno Setup 6", self.text,
                      "a missing compiler must be called out explicitly")

    def test_does_not_touch_user_configuration(self):
        for line in self.text.splitlines():
            lowered = line.lower()
            if "programdata" in lowered and not lowered.strip().startswith("rem"):
                self.fail(f"build must not write to user data: {line}")

    def test_output_paths_match_installer_expectations(self):
        self.assertIn("AudioAgentInstaller\\output", self.text)
        installer = read(INSTALLER)
        self.assertIn('Source: "dist\\AudioAgent\\AudioAgent.exe"', installer)
        self.assertIn('Source: "dist\\AudioAgent\\AudioAgentService.exe"', installer)
        self.assertIn('Source: "dist\\AudioAgent\\AudioAgentUI.exe"', installer)
        self.assertIn('Source: "dist\\AudioAgent\\_internal\\*"', installer)


class ReadmeBuildDocsTest(unittest.TestCase):

    def setUp(self):
        self.text = read(README)

    def test_no_longer_documents_onefile_main(self):
        self.assertNotIn("pyinstaller --onefile --noconsole --name AudioAgent main.py",
                         self.text,
                         "the obsolete single-file flow must not be documented")

    def test_documents_the_three_spec_workflow(self):
        for spec in ("AudioAgent.spec", "WindowsService.spec", "Ui.spec"):
            self.assertIn(spec, self.text)
        self.assertIn("build.bat", self.text)
        self.assertIn("Inno Setup 6", self.text)


class TrayRestartTest(unittest.TestCase):
    """The tray must not start a new instance while the old one is stopping."""

    def setUp(self):
        self.text = read(TRAY)

    def test_restart_waits_for_stopped_before_starting(self):
        body = self.text[self.text.index("def _do_restart"):]
        body = body[:body.index("\n    def ", 5)] if "\n    def " in body[5:] else body
        stop_wait = body.index('wait_for_service_state("STOPPED"')
        start_call = body.index('control_service("start")')
        self.assertLess(stop_wait, start_call,
                        "sc start must not be issued before the service is STOPPED")

    def test_restart_does_not_use_a_fixed_sleep_as_a_barrier(self):
        body = self.text[self.text.index("def _do_restart"):]
        self.assertNotIn("time.sleep(3)", body,
                         "a fixed sleep is not a stop barrier")

    def test_verifies_running_after_start(self):
        self.assertIn('wait_for_service_state("RUNNING"', self.text)

    def test_helpers_exist_and_parse_state(self):
        self.assertIn("def query_service_state", self.text)
        self.assertIn(r"STATE\s+:\s+\d+\s+(\w+)", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)