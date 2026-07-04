# GiPSy Autopilot Tester — project instructions

This is a standalone Python/Tkinter tool that lives inside the
ArduPilot repo (`Tools/GiPSy_tester/`) but is **not** part of the
ArduPilot build — it's a bench-test companion app for boards the
user builds custom firmware for (GiPSy, GiPSy-mini, PatrionicPH7X).

## Purpose

After flashing a board with a programmer over USB, connect this app
to verify: MAVLink is alive, IMU1/IMU2 are streaming plausible data,
and the baro is streaming plausible data. 4 LEDs, red/green.

## Facts established during design (don't re-derive, verify if stale)

- USB VID:PID for these boards is `1209:5741` (single CDC default,
  from `libraries/AP_HAL_ChibiOS/hwdef/scripts/chibios_hwdef.py`
  `get_USB_IDs()`). Identical for bootloader and app builds — no
  hwdef override sets USB_VID/USB_PID for GiPSy/GiPSy-mini/
  PatrionicPH7X.
- Bootloader mode speaks the PX4 binary sync protocol documented in
  `Tools/scripts/uploader.py` (`GET_SYNC=0x21`, `EOC=0x20`,
  `INSYNC=0x12`, `OK=0x10`). App mode never responds to this and
  instead emits MAVLink frames unprompted.
- `SYS_STATUS`'s sensor health bits are combined across all
  IMU/baro instances (see `GCS::update_sensor_status_flags` in
  `libraries/GCS_MAVLink/GCS.cpp`) — no per-instance IMU2/baro2
  health bit exists in this MAVLink dialect as used by ArduPilot.
  This tool uses message presence/rate as the per-instance proxy
  instead (see README.md).
- Rover's default `SR0_RAW_SENS` stream rate is 1 Hz
  (`Rover/GCS_Mavlink.cpp`), so `RAW_IMU`/`SCALED_IMU2`/
  `SCALED_PRESSURE` stream automatically once connected — no
  `REQUEST_DATA_STREAM`/`SET_MESSAGE_INTERVAL` needed from this
  tool.
- Windows COM port buildup is *not* from bootloader-vs-app: these
  single-CDC boards expose a USB serial derived from the STM32 CPU UID
  (`%SERIAL%` -> `UDID_START`, see `usbcfg_common.c`), which is stable
  for a board across replugs and across the bootloader<->app jump. So
  one board keeps one COM number; buildup is one permanent node per
  *distinct* board ever plugged in. Addressed with an opt-in
  `scripts/cleanup_com_ports.ps1` (removes not-present VID_1209 nodes),
  not by the app -- an unprivileged app can't reclaim COM numbers.

## Conventions for this subfolder

- Keep this tool dependency-light: `pyserial` + `pymavlink` (pip
  installed, pinned versions in `requirements.txt`) — not the
  vendored `modules/mavlink/pymavlink` submodule, since this tool
  should be usable/installable independently of a full ArduPilot
  checkout.
- No comments explaining WHAT code does — only WHY, when a fact
  isn't obvious from ArduPilot's own protocol/behavior (matches the
  facts list above).
- Update `tasks.md` as work items are completed; log any dead ends
  or surprising behavior in `lessons.md` so the next session doesn't
  re-discover them.
