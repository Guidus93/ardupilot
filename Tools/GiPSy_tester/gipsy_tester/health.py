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
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

from pymavlink import mavutil

STALE_AFTER_S = 2.5  # 2.5x the 1 Hz default stream period


@dataclass
class HealthSnapshot:
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
        try:
            conn = mavutil.mavlink_connection(self._port_name, baud=self._baud)
        except Exception as exc:  # noqa: BLE001 - surface any connection failure to the GUI
            with self._lock:
                self._snapshot.last_error = f"Could not open {self._port_name}: {exc}"
            return

        try:
            hb = conn.wait_heartbeat(timeout=3)
            if hb is None:
                with self._lock:
                    self._snapshot.last_error = "No MAVLink heartbeat received"
                return

            now = time.monotonic()
            self._seen.heartbeat = now
            with self._lock:
                self._snapshot.system_id = conn.target_system
                self._snapshot.autopilot_type = mavutil.mavlink.enums["MAV_AUTOPILOT"].get(
                    hb.autopilot, mavutil.mavlink.enums["MAV_AUTOPILOT"][0]
                ).name

            while not self._stop_event.is_set():
                msg = conn.recv_match(blocking=True, timeout=0.5)
                now = time.monotonic()
                if msg is not None:
                    self._handle_message(msg, now)
                self._update_snapshot(now)
        finally:
            conn.close()

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
