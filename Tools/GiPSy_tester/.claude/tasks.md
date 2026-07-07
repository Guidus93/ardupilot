# Tasks

## Done
- [x] Research USB VID/PID, bootloader protocol, MAVLink per-instance
      health limitations, default stream rates
- [x] Scaffold `Tools/GiPSy_tester/` package (`port_scan.py`,
      `bootloader.py`, `health.py`, `gui.py`, `run.py`)
- [x] Write README, opt-in Windows COM-port cleanup script
- [x] `.claude/CLAUDE.md`, `tasks.md`, `lessons.md`

## Done (cont.)
- [x] Test against a real GiPSy-mini board in both bootloader mode
      and app mode — sync probe correctly detects bootloader mode,
      no false positives against live MAVLink.
- [x] Fix the operator trap around the boot window. Earlier this was
      misdiagnosed as "first connect after flashing needs a full power
      cycle"; it's actually just the normal ~5s AP_Bootloader window
      (HAL_BOOTLOADER_TIMEOUT) before the board jumps to the app, made
      worse by our own up-front probe resetting that countdown via the
      bootloader's cmd_bad path. Connect is now patient: it waits out a
      15s boot window retrying a heartbeat and re-scanning ports (USB
      re-enumeration can change the COM number), and only probes the
      bootloader once, for diagnosis, if nothing boots. See lessons.md.
      NOTE: verified in code + import test; still to be re-tested on the
      physical board.

- [x] COM-port handling. Verified the COM number is stable per board
      (USB serial = CPU UID via %SERIAL%/UDID_START), so buildup is one
      node per *distinct* board, not per replug -- corrected the earlier
      "bootloader/app = separate instance" explanation in README/CLAUDE.
      Made the number a non-issue for the operator: Scan auto-selects the
      exact VID:PID match and (opt-in, default on) auto-connects. Stale
      Device Manager entries stay the cleanup script's job (an
      unprivileged app can't reclaim COM numbers).

## Next
- [ ] Confirm actual baud rate ArduPilot uses on USB CDC (currently
      assumes 57600 for the mavutil connection — USB CDC ignores the
      requested baud in practice, but pymavlink's serial connection
      path still wants a value; verify no issues in practice)
- [ ] Decide if PatrionicPH7X/GiPSy (full-size) need any per-board
      differences (assumption: no, protocol is board-agnostic)
- [x] Package for handoff to a non-Python user. Chose two double-click
      batch files (setup.bat builds .venv + installs pinned deps;
      run.bat launches via pythonw) over a PyInstaller .exe, because
      unsigned one-file exes get false-flagged by Defender/SmartScreen.
      Both tested: fresh setup works, run.bat guards a missing venv.
- [x] Add VBAT test: reads `SYS_STATUS.voltage_battery` (mV,
      `UINT16_MAX` sentinel = not sent), 5th LED + live voltage
      readout, green when 12.8-13.5V and fresh (<2.5s, same staleness
      window as the other LEDs). No extra stream request needed —
      `SYS_STATUS` is in Rover's `EXT_STAT` group, 1Hz default.

## Next (VBAT)
- [ ] Test VBAT LED against a real board on bench power at a known
      voltage to confirm the 12.8-13.5V range matches expectations
