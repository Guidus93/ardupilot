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
    autopilot_type: str = ""
    system_id: int | None = None
    last_error: str = ""


@dataclass
class _LastSeen:
    heartbeat: float = 0.0
    raw_imu: float = 0.0
    scaled_imu2: float = 0.0
    scaled_pressure: float = 0.0


def _is_plausible(*values: float) -> bool:
    return all(v == v and math.isfinite(v) for v in values)  # v == v rejects NaN


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
                self._update_snapshot(now)
        finally:
            conn.close()

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
        elif msg_type == "SCALED_IMU2":
            if _is_plausible(msg.xacc, msg.yacc, msg.zacc):
                self._seen.scaled_imu2 = now
        elif msg_type == "SCALED_PRESSURE":
            if _is_plausible(msg.press_abs) and msg.press_abs > 0:
                self._seen.scaled_pressure = now

    def _update_snapshot(self, now: float) -> None:
        with self._lock:
            self._snapshot.mavlink_ok = (now - self._seen.heartbeat) < STALE_AFTER_S
            self._snapshot.imu1_ok = (now - self._seen.raw_imu) < STALE_AFTER_S
            self._snapshot.imu2_ok = (now - self._seen.scaled_imu2) < STALE_AFTER_S
            self._snapshot.baro_ok = (now - self._seen.scaled_pressure) < STALE_AFTER_S
