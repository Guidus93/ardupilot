"""Background MAVLink listener that tracks per-message freshness.

Rover's default SR0_RAW_SENS stream rate is 1 Hz (see
Rover/GCS_Mavlink.cpp, GCS_MAVLINK_Parameters::var_info,
"RAW_SENS" AP_GROUPINFO default = 1), so RAW_IMU / SCALED_IMU2 /
SCALED_PRESSURE stream automatically once a MAVLink connection is
established -- no explicit REQUEST_DATA_STREAM or
MAV_CMD_SET_MESSAGE_INTERVAL is required from this tool.

ArduPilot's own SYS_STATUS sensor-health bits are ANDed across all
IMU/baro instances (see GCS::update_sensor_status_flags in
libraries/GCS_MAVLink/GCS.cpp), so there is no per-instance health
bit for IMU2 or a second baro. We approximate per-instance health as
"message received recently, with plausible (non-zero, non-NaN)
values" instead.

Connect is deliberately patient. After flashing or a power-up the
AP_Bootloader sits in its sync loop for HAL_BOOTLOADER_TIMEOUT (5s
default, see Tools/AP_Bootloader/AP_Bootloader.cpp) and then jumps to
the app on its own -- ArduPilot's own docs say to wait a few seconds
before pressing CONNECT. So instead of probing the bootloader up
front (a mistimed probe hits the bootloader's cmd_bad path and resets
its 5s countdown, keeping the board *in* the bootloader longer -- see
bl_protocol.cpp), we just retry a heartbeat for BOOT_WAIT_S, re-scanning
ports each attempt because the USB CDC port can re-enumerate to a
different COM number across the bootloader->app jump. Only if the whole
window elapses with no heartbeat do we probe the bootloader once, for
diagnosis.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from pymavlink import mavutil

from . import bootloader, port_scan

STALE_AFTER_S = 2.5  # 2.5x the 1 Hz default stream period

# Long enough to cover the 5s bootloader window plus USB re-enumeration
# after the bootloader->app jump, with margin.
BOOT_WAIT_S = 15.0
# Per-attempt heartbeat wait; a miss just means "not booted yet, retry".
HEARTBEAT_TIMEOUT_S = 2.0

VBAT_MIN_V = 12.8
VBAT_MAX_V = 13.5
VBAT_NOT_SENT = 65535  # SYS_STATUS.voltage_battery UINT16_MAX sentinel

# RAW_IMU/SCALED_IMU2 accel fields are in mG (1000 == 1 standard gravity) --
# see send_raw_imu()/send_scaled_imu() in libraries/GCS_MAVLink/GCS_Common.cpp.
GRAVITY_MSS = 9.80665

# devtype -> chip name, read off INS_ACC_ID / INS_ACC2_ID / BARO1_DEVID param
# values (bus_type:3, bus:5, address:8, devtype:8 packed into the low 24 bits
# -- see libraries/AP_HAL/Device.h DeviceStructure). Mirrors the tables in
# Tools/scripts/decode_devid.py; duplicated (not imported) so this tool stays
# usable outside a full ArduPilot checkout.
_INS_DEVTYPES = {
    0x09: "BMI160", 0x10: "L3G4200D", 0x11: "LSM303D", 0x12: "BMA180",
    0x13: "MPU6000", 0x16: "MPU9250", 0x17: "IIS328DQ", 0x21: "MPU6000",
    0x22: "L3GD20", 0x24: "MPU9250", 0x25: "I3G4250D", 0x26: "LSM9DS1",
    0x27: "ICM20789", 0x28: "ICM20689", 0x29: "BMI055", 0x2A: "SITL",
    0x2B: "BMI088", 0x2C: "ICM20948", 0x2D: "ICM20648", 0x2E: "ICM20649",
    0x2F: "ICM20602", 0x30: "ICM20601", 0x31: "ADIS1647x", 0x32: "SERIAL",
    0x33: "ICM40609", 0x34: "ICM42688", 0x35: "ICM42605", 0x36: "ICM40605",
    0x37: "IIM42652", 0x38: "BMI270", 0x39: "BMI085", 0x3A: "ICM42670",
    0x3B: "ICM45686",
}
_BARO_DEVTYPES = {
    0x01: "SITL", 0x02: "BMP085", 0x03: "BMP280", 0x04: "BMP388",
    0x05: "DPS280", 0x06: "DPS310", 0x07: "FBM320", 0x08: "ICM20789",
    0x09: "KELLERLD", 0x0A: "LPS2XH", 0x0B: "MS5611", 0x0C: "SPL06",
    0x0D: "DroneCAN", 0x0E: "MSP", 0x0F: "ICP101XX", 0x10: "ICP201XX",
    0x11: "MS5607", 0x12: "MS5837", 0x13: "MS5637", 0x14: "BMP390",
    0x15: "BMP581",
}

# Params carrying each sensor's device ID; fetched once right after
# connecting so the type name can be shown alongside the liveness LEDs.
_DEVID_PARAMS = {
    "INS_ACC_ID": ("imu1_type", _INS_DEVTYPES),
    "INS_ACC2_ID": ("imu2_type", _INS_DEVTYPES),
    "BARO1_DEVID": ("baro_type", _BARO_DEVTYPES),
}

# PARAM_REQUEST_READ is fire-and-forget -- if its PARAM_VALUE reply gets
# dropped (packet loss, board still busy right after boot), nothing
# else ever asks again and the type field is stuck blank forever even
# though the sensor's own streamed messages (which don't need a reply)
# keep the LED green and the live value updating. Re-request on this
# interval for any devid param whose type hasn't arrived yet.
DEVID_RETRY_INTERVAL_S = 1.5


@dataclass
class HealthSnapshot:
    # phase: "waiting" while retrying for the first heartbeat, "connected"
    # once it arrives, "failed" if the boot window elapsed with none.
    phase: str = "waiting"
    boot_wait_remaining: float = 0.0
    mavlink_ok: bool = False
    imu1_ok: bool = False
    imu2_ok: bool = False
    baro_ok: bool = False
    vbat_ok: bool = False
    vbat_voltage: float | None = None
    imu1_type: str = ""
    imu1_accel_mag: float | None = None
    imu2_type: str = ""
    imu2_accel_mag: float | None = None
    baro_type: str = ""
    baro_pressure: float | None = None
    autopilot_type: str = ""
    system_id: int | None = None
    last_error: str = ""


@dataclass
class _LastSeen:
    heartbeat: float = 0.0
    raw_imu: float = 0.0
    scaled_imu2: float = 0.0
    scaled_pressure: float = 0.0
    sys_status: float = 0.0


def _is_plausible(*values: float) -> bool:
    return all(v == v and math.isfinite(v) for v in values)  # v == v rejects NaN


def _accel_magnitude(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z) * GRAVITY_MSS / 1000.0


def _decode_devtype(dev_id: int, table: dict[int, str]) -> str:
    devtype = (dev_id >> 16) & 0xFF
    return table.get(devtype, f"unknown(0x{devtype:02x})")


class MavlinkHealthMonitor:
    """Owns a pymavlink connection on a background thread."""

    def __init__(self, port_name: str, baud: int = 57600):
        self._port_name = port_name
        self._baud = baud
        self._lock = threading.Lock()
        self._seen = _LastSeen()
        self._snapshot = HealthSnapshot()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # devid params whose PARAM_VALUE reply hasn't arrived yet -- see
        # _retry_missing_devid_params for why these need re-requesting.
        self._devid_pending: set[str] = set(_DEVID_PARAMS)
        self._devid_last_request = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def snapshot(self) -> HealthSnapshot:
        with self._lock:
            return HealthSnapshot(**self._snapshot.__dict__)

    def _run(self) -> None:
        conn = self._connect_and_wait()
        if conn is None:
            return

        try:
            while not self._stop_event.is_set():
                msg = conn.recv_match(blocking=True, timeout=0.5)
                now = time.monotonic()
                if msg is not None:
                    self._handle_message(msg, now)
                self._retry_missing_devid_params(conn, now)
                self._update_snapshot(now)
        finally:
            conn.close()

    def _retry_missing_devid_params(self, conn, now: float) -> None:
        if not self._devid_pending:
            return
        if now - self._devid_last_request < DEVID_RETRY_INTERVAL_S:
            return
        self._devid_last_request = now
        for param_name in self._devid_pending:
            conn.param_fetch_one(param_name)

    def _connect_and_wait(self):
        """Retry a heartbeat until the boot window elapses.

        Re-scans ports each pass because the USB CDC port can come back
        on a different COM number after the bootloader->app jump. Returns
        an open connection positioned just after the first heartbeat, or
        None (setting a diagnostic snapshot) if nothing booted in time.
        """
        deadline = time.monotonic() + BOOT_WAIT_S
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            with self._lock:
                self._snapshot.phase = "waiting"
                self._snapshot.boot_wait_remaining = max(0.0, remaining)
            if remaining <= 0:
                break

            for device in self._candidate_devices():
                if self._stop_event.is_set():
                    return None
                conn = self._try_heartbeat(device)
                if conn is not None:
                    return conn

        self._diagnose_no_heartbeat()
        return None

    def _candidate_devices(self) -> list[str]:
        # Keep the originally selected port first, then any other current
        # ArduPilot-looking ports (the port may have re-enumerated).
        devices = [self._port_name]
        try:
            for p in port_scan.find_candidate_ports():
                if p.device not in devices:
                    devices.append(p.device)
        except Exception:  # noqa: BLE001 - scanning must never abort the wait loop
            pass
        return devices

    def _try_heartbeat(self, device: str):
        """Open device and wait one short heartbeat window. On success
        record identity and return the open connection; else close and
        return None. Never writes to the port, so it can't disturb a
        board still counting down in the bootloader."""
        try:
            conn = mavutil.mavlink_connection(device, baud=self._baud)
        except Exception:  # noqa: BLE001 - port may not exist yet mid-reenumeration
            return None

        hb = conn.wait_heartbeat(timeout=HEARTBEAT_TIMEOUT_S)
        if hb is None:
            conn.close()
            return None

        self._port_name = device
        now = time.monotonic()
        self._seen.heartbeat = now
        with self._lock:
            self._snapshot.phase = "connected"
            self._snapshot.boot_wait_remaining = 0.0
            self._snapshot.system_id = conn.target_system
            self._snapshot.autopilot_type = mavutil.mavlink.enums["MAV_AUTOPILOT"].get(
                hb.autopilot, mavutil.mavlink.enums["MAV_AUTOPILOT"][0]
            ).name
        # Initial devid fetch happens here; _retry_missing_devid_params in
        # the main loop re-requests any that never get a reply.
        for param_name in _DEVID_PARAMS:
            conn.param_fetch_one(param_name)
        self._devid_last_request = now
        return conn

    def _diagnose_no_heartbeat(self) -> None:
        # Only now -- after the whole boot window elapsed with no MAVLink
        # -- is it safe to poke the bootloader sync probe: the board is
        # clearly not going to boot on its own, so resetting its timeout
        # no longer matters.
        for device in self._candidate_devices():
            if bootloader.probe_bootloader(device):
                msg = (
                    f"{device}: still in BOOTLOADER after {BOOT_WAIT_S:.0f}s. "
                    "Flash application firmware, then unplug/replug USB."
                )
                break
        else:
            msg = (
                f"No MAVLink heartbeat within {BOOT_WAIT_S:.0f}s. "
                "Check that firmware is flashed and the board is powered."
            )
        with self._lock:
            self._snapshot.phase = "failed"
            self._snapshot.boot_wait_remaining = 0.0
            self._snapshot.last_error = msg

    def _handle_message(self, msg, now: float) -> None:
        msg_type = msg.get_type()
        if msg_type == "HEARTBEAT":
            self._seen.heartbeat = now
        elif msg_type == "RAW_IMU":
            if _is_plausible(msg.xacc, msg.yacc, msg.zacc):
                self._seen.raw_imu = now
                with self._lock:
                    self._snapshot.imu1_accel_mag = _accel_magnitude(msg.xacc, msg.yacc, msg.zacc)
        elif msg_type == "SCALED_IMU2":
            if _is_plausible(msg.xacc, msg.yacc, msg.zacc):
                self._seen.scaled_imu2 = now
                with self._lock:
                    self._snapshot.imu2_accel_mag = _accel_magnitude(msg.xacc, msg.yacc, msg.zacc)
        elif msg_type == "SCALED_PRESSURE":
            if _is_plausible(msg.press_abs) and msg.press_abs > 0:
                self._seen.scaled_pressure = now
                with self._lock:
                    self._snapshot.baro_pressure = msg.press_abs
        elif msg_type == "SYS_STATUS":
            if msg.voltage_battery != VBAT_NOT_SENT:
                self._seen.sys_status = now
                with self._lock:
                    self._snapshot.vbat_voltage = msg.voltage_battery / 1000.0
        elif msg_type == "PARAM_VALUE":
            field = _DEVID_PARAMS.get(msg.param_id)
            if field is not None:
                self._devid_pending.discard(msg.param_id)
                attr, table = field
                dev_id = int(msg.param_value)
                with self._lock:
                    setattr(self._snapshot, attr, _decode_devtype(dev_id, table) if dev_id else "none")

    def _update_snapshot(self, now: float) -> None:
        with self._lock:
            self._snapshot.mavlink_ok = (now - self._seen.heartbeat) < STALE_AFTER_S
            self._snapshot.imu1_ok = (now - self._seen.raw_imu) < STALE_AFTER_S
            self._snapshot.imu2_ok = (now - self._seen.scaled_imu2) < STALE_AFTER_S
            self._snapshot.baro_ok = (now - self._seen.scaled_pressure) < STALE_AFTER_S

            vbat_fresh = (now - self._seen.sys_status) < STALE_AFTER_S
            self._snapshot.vbat_ok = (
                vbat_fresh
                and self._snapshot.vbat_voltage is not None
                and VBAT_MIN_V <= self._snapshot.vbat_voltage <= VBAT_MAX_V
            )
