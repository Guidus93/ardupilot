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

## Done (cont. 3)
- [x] Add IMU/baro chip type + live value display. Fetches
      `INS_ACC_ID`/`INS_ACC2_ID`/`BARO1_DEVID` once via
      `PARAM_REQUEST_READ` right after connecting, decodes the
      devtype byte packed into the device ID (bus_type:3, bus:5,
      address:8, devtype:8 -- see `libraries/AP_HAL/Device.h`
      DeviceStructure) using tables mirrored from
      `Tools/scripts/decode_devid.py`. Shows chip name + live
      accelerometer magnitude (m/s², from RAW_IMU/SCALED_IMU2, already
      streaming) under IMU1/IMU2, and chip name + live pressure (hPa,
      from SCALED_PRESSURE) under Baro.

## Done (cont. 4)
- [x] Verified on a real board: INS_ACC_ID/INS_ACC2_ID/BARO1_DEVID
      round-trip via PARAM_REQUEST_READ/PARAM_VALUE and the devtype
      decode shows correctly in the GUI.

## Done (cont. 5)
- [x] QR-code-driven production flow + CSV logging. Added
      `qrcode_parse.py` (parses `PRODUCT_WWYY_SERIAL`, e.g.
      `EV0004_2426_0092`) and `test_log.py` (writes `test_log.csv` next
      to the tool, one row per serial -- re-scanning the same serial
      overwrites its row rather than appending a duplicate). The GUI's
      QR entry is always focused; a keyboard-wedge scanner just types
      the code + Enter into it. A valid scan triggers Scan+Connect
      automatically (no button presses), then every poll checks
      whether all 5 LEDs are green -- PASS if so, FAIL if
      TEST_TIMEOUT_S (8s) elapses first or the board never shows up /
      the boot window itself times out. Either way the full snapshot
      (all sensor types + values) is logged and the QR field
      re-enables after a 3s PASS/FAIL banner. Manual Scan/Connect
      buttons still work standalone for debugging; a QR scan against
      an already-connected board rides along on that connection
      instead of erroring. Unit-tested (QR parsing, CSV
      append/overwrite, and the full GUI flow with a fake monitor for
      both PASS and no-board-found FAIL) -- not yet tested against a
      real board end-to-end.

## Next (QR/CSV)
- [ ] Test the full QR-to-CSV flow on the bench with a real scanner
      and a real board: confirm TEST_TIMEOUT_S (8s) is comfortably
      long enough once boot has actually completed (it's separate from
      the 15s BOOT_WAIT_S), and sanity-check the CSV in Excel.

## Done (cont. 6)
- [x] Fixed `setup.bat` failing on a factory PC (Python 3.14.6) with
      `did not find executable at 'C:\Python.exe'`. Cause: a stale `py`
      launcher registration pointed at a nonexistent path; `setup.bat`
      only checked `where py` (exists on PATH) not whether it actually
      runs, so it never fell back to the working plain `python`. Now
      checks with `py -3 --version` instead, and self-heals an
      existing `.venv` whose `python.exe` doesn't run (e.g. created
      earlier by the broken launcher) by wiping and recreating it. See
      lessons.md. Confirmed pymavlink/pyserial/lxml/future all import
      cleanly on Python 3.14 once the interpreter itself is right --
      this was a launcher issue, not a dependency compatibility issue.

## Done (cont. 7)
- [x] Fixed two factory-floor QR papercuts, both from the PC's Windows
      input language being set to Chinese instead of English:
      (1) the scanner's trailing Enter keystroke sometimes got eaten by
      IME composition instead of reaching the entry, so `_on_qr_scanned`
      never fired -- fixed with an idle-debounce auto-submit
      (`QR_IDLE_SUBMIT_MS`, 400ms of no new keystrokes triggers submit
      on its own, Enter is now a nice-to-have not a requirement); (2) an
      IME can also emit full-width characters (e.g. `ａ` instead of
      `a`, full-width `＿` for `_`) which broke the QR regex outright --
      fixed in `qrcode_parse.parse_qr` with `unicodedata.normalize
      NFKC`, which folds full-width ASCII back to plain ASCII before
      matching (and the stored `raw` is the normalized form too, so
      logs/display show clean ASCII).
      Also fixed the separate "still need to press Scan manually"
      report: `port_scan.find_candidate_ports()` (backed by
      `serial.tools.list_ports.comports()`) can return a stale/empty
      result on the very first call right after a QR scan even with
      the board already plugged in and enumerated -- a manual re-click
      moments later always found it, which pointed at a one-shot-scan
      timing issue rather than a real detection failure. Added
      `_scan_for_qr_retry`, which retries every
      `QR_SCAN_RETRY_INTERVAL_MS` (300ms) for up to `QR_SCAN_RETRY_S`
      (3s) before giving up and logging a FAIL.
      Unit-tested: fullwidth-IME QR parsing, idle-submit firing without
      Enter, and scan-retry recovering from a scripted flaky
      `find_candidate_ports` (fails N times then succeeds).
