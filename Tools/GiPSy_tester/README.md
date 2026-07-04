# GiPSy Autopilot Tester

Small desktop tool to check a freshly flashed GiPSy / GiPSy-mini /
PatrionicPH7X board over USB before it leaves the bench: connects
over the virtual COM port, detects bootloader-vs-app mode, and shows
4 status LEDs (MAVLink heartbeat, IMU1, IMU2, Baro).

## Setup

```
cd Tools/GiPSy_tester
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```
python run.py
```

1. Plug in the board over USB.
2. Click **Scan** to list candidate ports (filtered by ArduPilot's
   USB VID:PID `1209:5741`, falling back to description matching).
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
   - Once a heartbeat arrives, the four LEDs turn green as HEARTBEAT /
     RAW_IMU / SCALED_IMU2 / SCALED_PRESSURE messages arrive, and stay
     green as long as they keep arriving within ~2.5s.
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

ArduPilot boards' bootloader and application firmware both use the
same USB VID:PID, but Windows treats each as its own device instance
(and remembers the COM number even after unplugging). Repeated
flash/reboot cycles create many stale COM port entries over time.

`scripts/cleanup_com_ports.ps1` lists and (with `-Remove`, from an
elevated PowerShell) removes stale ArduPilot serial device entries
— it never touches devices that are currently plugged in. Run it
manually and periodically; the app itself does not modify Windows
device state.

## Not covered by this tool

- Flashing firmware itself — use your external STM32 programmer as
  before.
- ArduPilot's own calibration-aware sensor health (would require
  reading `SYS_STATUS` / prearm STATUSTEXT, which is combined across
  instances — see above).
