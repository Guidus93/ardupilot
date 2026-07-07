# GiPSy Autopilot Tester

Small desktop tool to check a freshly flashed GiPSy / GiPSy-mini /
PatrionicPH7X board over USB before it leaves the bench: connects
over the virtual COM port, detects bootloader-vs-app mode, and shows
5 status LEDs (MAVLink heartbeat, IMU1, IMU2, Baro, VBAT). Production
use is QR-driven: scan a unit's QR code and the tool connects, tests,
shows PASS/FAIL, and logs the result to a CSV -- see "Production
testing with a QR scanner" below.

## Setup and run (Windows, no command line needed)

1. **Double-click `setup.bat`** once. It creates a local `.venv` and
   installs the pinned dependencies. (Needs Python 3 installed from
   [python.org](https://www.python.org/downloads/) with "Add to PATH"
   ticked — `setup.bat` tells you if it's missing.)
2. **Double-click `run.bat`** to start the tool. Run it any time; it
   reuses the environment `setup.bat` created.

No PyInstaller `.exe` is shipped on purpose: unsigned one-file exes
built from Python get false-flagged by Windows Defender/SmartScreen.
The two plain-text batch files avoid that and are easy to inspect.

### Manual alternative (if you prefer a shell)

```
cd Tools/GiPSy_tester
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## Production testing with a QR scanner

1. Plug in the board over USB.
2. Click into the **Scan QR code** field (it's focused automatically
   on startup and after every test). Scan the unit's QR code with a
   USB keyboard-wedge scanner — it types the code followed by Enter,
   same as a keyboard, no drivers or extra hardware needed.
   - Expected format: `PRODUCT_WWYY_SERIAL`, e.g. `EV0004_2426_0092`
     is product `EV0004`, week 24 of year 2026, serial `0092`. An
     unrecognized format is rejected with an on-screen error and
     nothing is logged.
3. A valid scan automatically scans for the port and connects — no
   button presses. It then waits (same boot-window patience as
   before) for all 5 LEDs to go green.
   - **All 5 green** within 8s of connecting -> **PASS**.
   - Board never found, boot window times out, or 8s pass without all
     5 LEDs green -> **FAIL**.
   - Either way the full sensor snapshot (chip types, live values,
     voltage) is written as one row to `test_log.csv` next to the
     tool — re-scanning the same serial (e.g. re-testing after a fix)
     overwrites its row rather than adding a duplicate.
4. The PASS/FAIL result is shown for 3 seconds, then the QR field
   clears and refocuses automatically — scan the next unit right away.

## Manual controls (for debugging)

The Port dropdown, **Scan**, and **Connect** buttons below the QR
field work independently for troubleshooting a single board without
going through the QR flow. Scanning a QR while already connected this
way just attaches the pass/fail test to that existing connection
instead of erroring.

1. Plug in the board over USB.
2. Click **Scan**. The tool auto-selects the port matching ArduPilot's
   USB VID:PID `1209:5741`, so you don't need to know the COM number.
   With **Auto-connect on scan** ticked (the default) it also starts
   connecting immediately — plug in, click Scan, done. If no port
   matches the exact USB ID, it falls back to a description-based best
   guess and leaves connecting to you.
3. Select the port, click **Connect**. You can click it right away —
   no need to wait or count seconds yourself.
   - After flashing or a power-up the board sits in its bootloader for
     ~5s before it boots the firmware on its own (this is normal — see
     [ArduPilot's docs](https://ardupilot.org/copter/docs/common-loading-firmware-onto-pixhawk.html)).
     The tool knows this: it shows a **"waiting for board to boot
     (Ns left)"** countdown and keeps retrying for ~15s, so **don't
     unplug the board during the countdown**.
   - It also re-scans ports while waiting, because the USB COM number
     can change when the board jumps from bootloader to application.
   - Once a heartbeat arrives, the LEDs turn green as HEARTBEAT /
     RAW_IMU / SCALED_IMU2 / SCALED_PRESSURE / SYS_STATUS messages
     arrive, and stay green as long as they keep arriving within ~2.5s.
   - The IMU1/IMU2 LEDs show the detected chip (from `INS_ACC_ID` /
     `INS_ACC2_ID`, fetched once via `PARAM_REQUEST_READ` right after
     connecting) and the live accelerometer magnitude in m/s² — near
     9.8 m/s² at rest, regardless of orientation. The Baro LED shows
     its chip (`BARO1_DEVID`) and live absolute pressure in hPa.
   - The VBAT LED also shows the live battery voltage underneath it
     and only goes green when the reading is fresh **and** between
     12.8V and 13.5V.
   - Only if the whole ~15s window passes with no MAVLink does the tool
     probe the bootloader once and tell you either to flash firmware
     (still in bootloader) or to check firmware/power (no response).

## Why 2 IMU LEDs but no per-instance MAVLink health field

ArduPilot's `SYS_STATUS` MAVLink message only reports one combined
"all IMUs healthy" bit (ANDed across instances — see
`GCS::update_sensor_status_flags` in
`libraries/GCS_MAVLink/GCS.cpp`), same for baro. There's no
dedicated "IMU2 healthy" bit. This tool instead treats each IMU/baro
LED as healthy when that instance's own message
(`RAW_IMU`/`SCALED_IMU2`/`SCALED_PRESSURE`) is arriving recently with
plausible (non-zero, non-NaN) values — a liveness/plausibility
check, not ArduPilot's internal calibration-aware health verdict.

## Windows COM port buildup

Each board reports a USB serial number derived from its STM32 CPU UID
(`%SERIAL%` in the hwdef, expanded from `UDID_START` — see
`libraries/AP_HAL_ChibiOS/hwdef/common/usbcfg_common.c`). That serial
is stable for a given board across replugs and across the
bootloader↔app jump, so **the same board always gets the same COM
number** — you don't need to manage it, and the tool auto-selects it
by VID:PID regardless. What *does* accumulate is one permanent COM
entry per *distinct* board you've ever plugged into this PC (each has a
different UID), which clutters Device Manager over a long bench
session.

`scripts/cleanup_com_ports.ps1` lists and (with `-Remove`, from an
elevated PowerShell) removes ArduPilot serial device entries that are
**not currently present** — it never touches a plugged-in device. Run
it manually and periodically; the app itself does not modify Windows
device state (an unprivileged app can't reclaim COM numbers, and
closing a port on Disconnect frees nothing while the board is still
attached).

## Not covered by this tool

- Flashing firmware itself — use your external STM32 programmer as
  before.
- ArduPilot's own calibration-aware sensor health (would require
  reading `SYS_STATUS` / prearm STATUSTEXT, which is combined across
  instances — see above).
