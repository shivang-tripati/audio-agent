# Duplicate Audio Playback — Findings, Fix and Deployment Report

**Scope:** intermittent overlapping playback on a branch PC (same or different tracks audible
simultaneously, offset by a few seconds).
**Status:** root cause confirmed and fixed; 24 regression tests pass; **runtime verification is
pending until the rebuilt binaries are installed on the target machine.**

Evidence base: `C:\ProgramData\AudioAgent\logs\{agent,service}\*.log` (2026-10-13) plus live
process/service inspection on the target machine.

---

## 1. Confirmed root causes

### 1.1 The single-instance mutex never executed (primary cause)

`utils/single_instance.py` checked for a duplicate with:

```python
try:
    existing = win32event.OpenMutex(win32con.MUTEX_ALL_ACCESS, False, mutex_name)
    ...
except Exception:
    pass
```

`win32con` (pywin32) has **no** `MUTEX_ALL_ACCESS` attribute — verified at runtime:

```
win32con.MUTEX_ALL_ACCESS  : ABSENT
win32event.MUTEX_ALL_ACCESS: ABSENT
AttributeError: module 'win32con' has no attribute 'MUTEX_ALL_ACCESS'
```

The `AttributeError` was swallowed by `except Exception: pass`, so the duplicate check **never
ran**. Execution then reached `CreateMutex(...)`, which on an existing name returns a valid
handle and reports `ERROR_ALREADY_EXISTS` via `GetLastError()` — a value the code never
inspected (the UI path `_init_ui_mutex` *did* check it; that is why only the UI was protected):

```
1st CreateMutex -> GetLastError = 0
2nd CreateMutex -> GetLastError = 183 (ERROR_ALREADY_EXISTS, no exception raised)
```

Consequence: **every worker "acquired" `Global\AudioAgent_Worker` and became a playback owner.**
This matches the production log, where every worker start is followed by
`Mutex created: Global\AudioAgent_Worker` and never by a duplicate rejection.

A second, related exposure: the mutex DACL grants access only to SYSTEM/Administrators, so a
worker running under any other account gets `ERROR_ACCESS_DENIED` on the existing object. That
was previously ignored (`critical=False` → "continuing without it"), i.e. no protection at all.

### 1.2 No service-level ownership

`service/windows_service.py` never acquired `Global\AudioAgent_Service` (the module was only
listed in `WindowsService.spec` hidden imports with a "← MISSING" comment). Nothing stopped a
second service instance from spawning its own worker. `service.log` shows five service instance
starts — 11:38:49, 13:46:21, 13:46:48, 13:50:06, 14:08:45 — with no `SvcStop` in between, and
`sc qc/qfailure` confirms `FAILURE_ACTIONS: RESTART -- Delay = 5000`, so a force-killed service
is restarted by the SCM within 5 s.

### 1.3 Exit code 0 was treated as restartable

`worker_main` logs "Device not activated — worker will not restart" and exits 0; both the
service monitor and `supervisor.py` respawned it anyway (~100 worker launches between 11:39 and
12:14, a new PID every ~6 s). A rejected duplicate also exited 0, so the same loop would have
occurred once the mutex was fixed naively.

### 1.4 Two VLC instances played simultaneously (log proof)

| Time (2026-10-13) | Event |
|---|---|
| 13:46:25.779 | worker PID **7428** starts, mutex "created" |
| 13:46:46.942 | 7428 starts track *Tujhko Pa liya…* |
| 13:46:49.460 | worker PID **15100** starts, mutex "created" again — no rejection |
| 13:46:50.014 | 15100 starts the **same track**, 3 s later |
| 13:49:40.935 | *Tujhko* completes — 2 m 54 s after **7428**'s start |
| 13:49:43.936 | next track *Vraj Jan Man* requested (7428's loop) |
| 13:49:43.985 | *Tujhko* completes — 2 m 54 s after **15100**'s start |
| 13:49:43.986/.987 | *Vraj Jan Man* requested a second time (15100's loop) |
| 13:49:44.238/.289 | two `Now playing playlist track` callbacks, 51 ms apart |

Two independent agents, each with its own `AudioController` (its own `vlc.Instance`) and its own
`PlaylistEngine`, playing on the same output device. The `13:49:40` "same priority already
playing" rejection and its 3-second retry are **correct** behaviour — that is the guard working;
the defect is that a second loop existed to do the retrying.

### 1.5 Playback races inside one process (independently confirmed)

- **Stale monitor callback.** `stop()` joins the monitor thread with a 2 s timeout;
  `_start_monitoring()` then resets the shared `stop_monitoring`/`_suppress_end_cb` flags for
  the new session. A surviving old monitor keeps polling the *same shared player* and fires
  `on_playback_end(old_track)` mid-new-session. Reproduced deterministically: pre-fix
  `ended=[('B'), ('A')]`, post-fix `ended=[('B')]`.
- **Conditional player stop.** `stop()` only touched the player `if self.is_playing`, and
  `play()` calls `stop()` before swapping media — a stale `False` left the old track audible
  under the new one.
- **Orphaned playlist loop.** `PlaylistEngine.start()` tested `_is_running` outside the lock and
  `stop()` never joined the loop thread, so `stop()` → `start()` (schedule resume,
  `POST /playlist/start`, `update_playlist`) left two loops driving one player.
- **Agent restart loop.** `worker_main` built a new `AudioAgent` after a failure without stopping
  the previous one (heartbeat/socket/local-API threads still alive → a second VLC instance in the
  same process).

---

## 2. Files changed and why

| File | Change |
|---|---|
| `utils/single_instance.py` | Duplicate detection now uses `CreateMutex` + `GetLastError() == ERROR_ALREADY_EXISTS` (atomic, no TOCTOU). `ERROR_ACCESS_DENIED` is treated as duplicate (SYSTEM-only DACL). `DUPLICATE_EXIT_CODE = 3`. Added `wait=`/`stop_check=` handover, `mutex_name` override (tests), `acquired` flag. Worker mutex is now **critical** — no mutex means no playback. |
| `service/windows_service.py` | Acquires `Global\AudioAgent_Service` **before** spawning a worker (waits/hands over if another instance owns it); releases it in `SvcDoRun`'s `finally`. `SvcStop` signals the stop event **before** terminating the worker (was respawning one mid-teardown, leaving orphans). Exit-code contract: duplicate → no restart; clean (0) → 60 s standby; crash → 5 s restart. Logs PIDs. |
| `supervisor.py` | Same ownership + exit-code contract. This path matters because the installer puts a desktop shortcut to `AudioAgent.exe`, which runs the supervisor — a second spawner outside the service. |
| `worker_main.py` | `agent.stop()` runs before a replacement `AudioAgent` is constructed; logs if the device mutex was not acquired. |
| `agent/audio_controller.py` | Monotonic session id; monitor threads carry their session and bail out when stale, so a stale callback cannot clear `is_playing` or fire `on_playback_end` for a newer session. `stop()` always stops the player. `_restart_vlc_instance()` invalidates the session. |
| `playlist/playlist_engine.py` | `start()` does its `_is_running` check under the lock; `stop()` joins the play-loop thread before returning. |
| `agent_app.py` | `stop()` also stops `playback_controller` and `local_api` (the HTTP server used to survive shutdown and hold the port). |

Playback order, priority semantics, schedule behaviour and per-device independence are unchanged.
New tests: `test/test_worker_lifecycle.py`, `test/test_playback_races.py`, `test/testhelpers.py`
(fake VLC module + fake player; no libvlc, audio device, or real VLC process required).

---

## 3. Tests

```
24 passed in ~21 s
  test/test_worker_lifecycle.py  13   mutex acquisition, duplicate rejection (cross-process),
                                      cross-account access denied, handover/takeover, worker
                                      shutdown ordering, service startup ordering, exit-code
                                      restart contract
  test/test_playback_races.py    11   stale/duplicate completion callbacks, conditional stop,
                                      repeated & concurrent start(), rejection→completion→retry,
                                      concurrent same/different track requests, priority
```

Runs with either runner (no new project dependency):
`python -m pytest test/test_worker_lifecycle.py test/test_playback_races.py`
`python -m unittest discover -s test -p "test_worker_lifecycle.py"`

**Pre-fix failure evidence** (run against a pristine `git worktree` of `9396c3d`):

```
3 failed, 8 passed
  AudioControllerSessionTest::test_stale_monitor_cannot_end_a_newer_session
  AudioControllerSessionTest::test_stop_always_stops_the_player_even_when_state_is_stale
  PlaylistLoopTest::test_start_then_stop_then_start_keeps_one_loop
```

Restart-policy probe (real service monitor, worker exits 0):

```
pre-fix : spawns in 12s after a clean worker exit: 1     (and it repeats forever)
post-fix: spawns in 12s after a clean worker exit: 0     (60 s standby instead)
```

No pre-existing automated suite exists — `test/test_backend.py` is a manual Flask helper that
needs `flask`/`flask_sock`, so it was not run.

---

## 4. Build and installer workflow

### 4.1 Documented commands are stale — do not use `build.bat`

`build.bat` and `README.md` document `pyinstaller --onefile main.py`. That contradicts the
repository: `build.bat` **deletes `AudioAgent.spec`** and produces a single-file exe without the
VLC binaries or the required hidden imports. The real artifacts are the three committed spec
files plus an Inno Setup installer, and the existing `dist\` layout proves it:

```
dist\AudioAgent\            <- AudioAgent.spec      (EXE + COLLECT -> _internal\)
dist\AudioAgentService.exe  <- WindowsService.spec  (EXE only)
dist\AudioAgentUI.exe       <- Ui.spec              (EXE only)
AudioAgentInstaller\dist\AudioAgent\   <- staging folder consumed by installer.iss
AudioAgentInstaller\output\AudioAgentSetup_2.1.0.exe
```

`installer.iss` resolves `Source:` paths relative to `AudioAgentInstaller\`, so it reads that
staging folder, which must contain all three exes **and** `_internal\` (including
`_internal\vlc\libvlc.dll`, which is also copied to `%ProgramData%\AudioAgent\vlc`).

### 4.2 Correct build sequence (derived from the repo's spec files and artifact layout)

Run from the repository root in a shell with `venv\Scripts` on `PATH`:

```bat
:: 1. Worker/supervisor exe (one-dir; contains _internal\ with libvlc)
pyinstaller --noconfirm --clean AudioAgent.spec

:: 2. Windows service exe
pyinstaller --noconfirm --clean WindowsService.spec

:: 3. Tray UI exe
pyinstaller --noconfirm --clean Ui.spec

:: 4. Stage all three exes next to the worker's _internal\ folder
copy /Y dist\AudioAgentService.exe dist\AudioAgent\
copy /Y dist\AudioAgentUI.exe      dist\AudioAgent\
mkdir AudioAgentInstaller\dist\AudioAgent
copy /Y dist\AudioAgent\* AudioAgentInstaller\dist\AudioAgent\ /E /Y

:: 5. Compile the installer (Inno Setup 6)
::    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" AudioAgentInstaller\installer.iss
::    -> AudioAgentInstaller\output\AudioAgentSetup_2.1.0.exe
```

Bump `#define MyAppVersion` in `installer.iss` when cutting a release; the output name and
`AppVersion` are derived from it.

### 4.3 The installer does **not** reliably stop the running service (confirmed)

`AudioAgentInstaller\installer.iss` `InitializeSetup()` and `[Run]` both `taskkill /F` the three
processes. Consequences:

- The service is **killed, not stopped** — no `sc stop`, no wait for `STOPPED`.
- `sc failure … restart/5000` is already armed from the previous install (verified on the target:
  `FAILURE_ACTIONS: RESTART -- Delay = 5000`), so the **SCM restarts the service ~5 s after the
  kill** — plausibly the source of the 13:46:48 and 13:50:06 service instances, and of the
  second worker.
- The `[Run]` `taskkill` block runs **after** `[Files]` has already replaced the binaries, so an
  SCM-restarted instance can be running from a partially replaced folder.
- `AudioAgentService.exe start` at the end has no exit-code check, so if the SCM already
  auto-restarted the service the installer silently continues and the machine runs the **old**
  worker — the fix would appear not to work.

Live confirmation on the target machine: **two** `AudioAgentService.exe` processes (PIDs 4352 and
5724) and one `AudioAgent.exe` (PID 7484) — i.e. two service instances, one worker.

**Recommendation (operational, no code change in this fix):** stop the service explicitly before
running the installer (`sc stop AudioAgentService`, wait for `STOPPED`, confirm no
`AudioAgent.exe`/`AudioAgentService.exe` remains), then start it explicitly afterwards. A
follow-up (not part of this change) should make the installer call `sc stop` before `[Files]` and
verify the start, and/or clear `sc failure` for the duration of the install.

---

## 5. Deployment checklist

Config lives in `%ProgramData%\AudioAgent\config`, logs in `%ProgramData%\AudioAgent\logs`,
cached audio in `%ProgramData%\AudioAgent\audio_cache`, binaries in `%ProgramFiles%\AudioAgent`.

1. **Back up** (nothing is deleted by these steps):
   `xcopy /E /I /Y "%ProgramData%\AudioAgent\config" "%BACKUP%\config"`
   `xcopy /E /I /Y "%ProgramData%\AudioAgent\logs" "%BACKUP%\logs"`
2. **Stop cleanly:** `sc stop AudioAgentService`, wait until `sc query AudioAgentService`
   reports `STOPPED`. Exit the tray (`AudioAgentUI.exe`) if running.
3. **Confirm nothing is left:** `tasklist /FI "IMAGENAME eq AudioAgent.exe"` and
   `tasklist /FI "IMAGENAME eq AudioAgentService.exe"` must return no rows. Also check no
   `AudioAgentUI.exe`. Do **not** kill unrelated processes; re-run `sc stop`/`sc query` first if
   something persists.
4. **Install:** run `AudioAgentInstaller\output\AudioAgentSetup_<version>.exe` elevated. It
   re-registers the service, re-arms `sc failure`, starts the service and launches the tray.
   Verify the worker binary timestamp in `%ProgramFiles%\AudioAgent\AudioAgent.exe` matches the
   new build (guards against the SCM-restart-on-old-binary case in §4.3).
5. **Start and verify ownership:**
   `sc query AudioAgentService` → `RUNNING`, note the service PID (`tasklist /FI "PID eq <pid>"`).
   Expect exactly **one** `AudioAgentService.exe` and exactly **one** `AudioAgent.exe`.
   `C:\ProgramData\AudioAgent\logs\worker\worker_debug.txt` records each worker launch.
6. **Mutex enforcement:** `logs\agent\agent.log` must show `Mutex acquired: Global\AudioAgent_Worker`
   once per worker start and `Mutex acquired: Global\AudioAgent_Service` once per service start.
   To confirm rejection, launch a second supervisor by hand
   (`AudioAgent.exe` with no `--worker`): it must log "Another instance already holds mutex …
   Waiting." and must **not** start a worker or produce audio.
7. **Playback checks:** let a playlist run across a track boundary and confirm one track at a
   time; push several playlist updates in quick succession from the Admin Portal and confirm one
   "Now playing playlist track" per track and no duplicate audio; confirm the rejection+retry
   path (`[Playlist] playback rejected - retrying`) still resolves to a single continuing session.
8. **Restart + connectivity:** `sc stop` / `sc start AudioAgentService` → exactly one worker
   returns and audio resumes. Pull the network cable briefly → agent logs "Disconnected from
   backend", keeps playing the cached playlist, and reconnects without a second worker or a
   second socket session.
9. **Admin Portal:** device shows ONLINE with the correct status, track and position; volume
   matches the internal (Windows audio session) volume; no flapping between two devices or two
   heartbeats. Compare the tray's `/status` (`http://127.0.0.1:57821/status`) with the portal.

Rollback: restore the backed-up `config`/`logs` and reinstall the previous installer version.
Device activation/token state lives only in `%ProgramData%\AudioAgent\config`, so do not delete
that folder during rollback.

---

## 6. Follow-up: installer upgrade path and build workflow

Closed the two open items from §6 (installer force-kill, stale build docs).

**`AudioAgentInstaller/installer.iss`** — the upgrade path no longer force-kills the service:

1. `InitializeSetup` (silent) / `CurPageChanged(wpSelectDir)` (interactive, so the wait is
   visible) call `StopServiceForUpgrade`, which asks the SCM to stop the service
   (`sc stop`), waits up to 120 s for `STOPPED`, then waits up to 30 s for the
   `AudioAgent.exe` worker to exit. Only then does `[Files]` copy anything.
2. On failure it aborts with a diagnostic (`MsgBox` / `RaiseException`) telling the user to
   stop the service manually — it never kills it. Killing it is what the SCM records as a
   service *failure*, which is what armed the `restart/5000` recovery that produced the second
   service instance.
3. `CurStepChanged(ssPostInstall)` re-applies the intended recovery policy
   (`sc failure ... reset= 0 actions= restart/5000`) on **both** paths, starts the service,
   verifies it reaches `RUNNING` (120 s) and only then launches the tray. A start failure
   aborts the installation with a diagnostic.
4. Uninstall stops the same way (`CurUninstallStepChanged(usUninstall)`); the `taskkill` lines
   that remain in `[UninstallRun]` are last-resort cleanup after `sc delete`.
5. Activation config, cached audio and logs are untouched (`[UninstallDelete]` only removes
   `%ProgramData%\AudioAgent\vlc`).

**`ui/tray_app.py`** — `_do_restart` had the same lifecycle defect: `sc stop`, `sleep(3)`,
`sc start`. `sc stop` is asynchronous, so the new instance could start while the old one was
still alive. It now queries the SCM state, waits (bounded) for `STOPPED` **before** starting,
then verifies `RUNNING`, and refuses to start a second instance if the stop does not complete.
Helpers: `query_service_state`, `wait_for_service_state`, `control_service`.

**`build.bat` / `README.md`** — now use the repository's actual three-spec workflow
(`AudioAgent.spec` → one-dir worker + `_internal\`, `WindowsService.spec`, `Ui.spec`), stage the
service and tray executables into `dist\AudioAgent\`, mirror that folder into
`AudioAgentInstaller\dist\AudioAgent\`, verify the payload (including
`_internal\vlc\libvlc.dll`), and compile the installer with `ISCC.exe`. The committed `.spec`
files are never deleted or regenerated, and the build never writes to `%ProgramData%\AudioAgent`.
If Inno Setup is absent the binaries are still built and the script says so explicitly.

Tests: `test/test_installer_upgrade.py` (26) asserts the lifecycle contract of the installer
script, the build script, the README and the tray restart — no force-kill in the upgrade path,
bounded waits, abort-on-failure, recovery policy restored on every path, tray after service,
three-spec build, staging, mirror, exit-code checks. 24 of them fail against the previous
installer/build/tray code.

`test/conftest.py` keeps `test/test_backend.py` (a manual Flask helper needing `flask`) out of
pytest collection; `python -m unittest discover -s test` still tries to import it, so use
pytest or name the file explicitly.

## 7. Tray playback controls and the observed process tree

### 7.1 Two `AudioAgentService.exe` processes — explained, not a bug

`WindowsService.spec` and `Ui.spec` contain an `EXE(...)` with **no `COLLECT(...)`**, i.e. they
are PyInstaller **one-file** builds: the bootloader starts a child that runs the script, so one
logical application shows up as two processes with the same image name. `AudioAgent.spec` has
both `EXE(...)` and `COLLECT(...)` (one-directory), so the worker is a single process.

That matches the observed tree exactly:

```
services.exe (1264)
└─ AudioAgentService.exe (4212)   PyInstaller bootloader parent
   └─ AudioAgentService.exe (15032)  child: calls StartServiceCtrlDispatcher -> SvcDoRun
      └─ AudioAgent.exe (14896)      the one playback worker
AudioAgentUI.exe (15288)
└─ AudioAgentUI.exe (13220)       same one-file parent/child pair, one logical tray UI
```

Running `AudioAgentService.exe` by hand fails with
`pywintypes.error: (1063, 'StartServiceCtrlDispatcher', ...)` **by design** — `service\windows_service.py`
only enters the SCM dispatcher when `len(sys.argv) == 1`; with arguments it runs
`HandleCommandLine` (install/remove/start/stop). It is not a GUI program and must not be started
interactively.

Consequences that were real bugs and are now fixed: killing the parent (the old installer's
`taskkill /F`) left the child running, which is how two service instances used to overlap; and the
tray's `sc stop` + `sleep(3)` + `sc start` could start a new instance before the old one stopped.
Single ownership is enforced by the mutexes, not by the process count.

### 7.2 Tray playback controls

The tray's single `⏹ Stop Audio` item is replaced by a state-aware action driven by the last
successful `/status` response:

| Reported state | Menu item | Endpoint |
|---|---|---|
| `PLAYING` | ⏸ Pause Audio | `POST /pause` |
| `PAUSED` | ▶ Resume Audio | `POST /resume` |
| `IDLE` | ▶ Start Playback | `POST /playlist/start` |
| offline/unknown | ⏹ Playback unavailable (disabled) | none — no worker is started from the tray |

`Open Panel`, `⏹ Stop Audio` (kept as a separate control) and `↻ Restart Service` are unchanged.
Commands run on their own thread, are serialised by a lock (rapid clicks collapse into one), are
logged with previous state and API result, and are **confirmed with a fresh `GET /status`** — a
200 alone is never treated as proof. `pystray.MenuItem.text` is read-only, so the menu is rebuilt
when the action changes.

`/pause` and `/resume` keep VLC paused in place, so the position is preserved;
`PlaylistEngine.get_state_name()` is now the source of truth for `/status`, `/pause`, `/resume`
and `/playlist/start` instead of hard-coded `PLAYING`/`PAUSED` strings.

Tests: `test/test_tray_playback.py` (17) and `test/test_single_instance_and_processes.py` (9).

## 8. Confirmed vs unresolved

**Confirmed (evidence-backed, fixed):** ineffective worker mutex; absent service mutex;
restart-on-exit-0; simultaneous dual-worker playback; stale monitor callback; conditional player
stop; orphaned playlist loop; agent restart building a second agent without stopping the first.

**Unresolved / open questions:**
- Which trigger started each extra service instance (installer `taskkill` + SCM failure-recovery
  restart is the strongest candidate, but a tray "Restart Service" (`sc stop` + `sc start` 3 s
  later) is also possible — `sc stop` is asynchronous and the old instance may still be alive).
  Both paths are now fixed (installer stops the service gracefully; the tray waits for `STOPPED`),
  but the historical trigger was not reproduced, only closed off.
- Socket callbacks (socketio thread), the local HTTP API and the schedule thread remain
  cross-thread entry points into `PlaybackController`. They are correct now that exactly one agent
  exists per device and the controller holds a re-entrant lock, but the lock is not a substitute
  for the process-level ownership enforced above.
- The installer changes were **not compiled** (no Inno Setup on the build machine) and have not
  been run against a machine with the service installed. The build script itself was executed
  end-to-end and produced all three executables plus the staged payload.
- The rebuilt binaries have not been exercised on the target machine; everything above about the
  running service is from code and logs, not from a live post-fix run.