"""CSV log of bench test results, one row per serial number.

Re-scanning the same serial (e.g. re-testing after a fix) overwrites
its existing row with the latest result rather than appending a
duplicate -- the log is meant to reflect each unit's current state,
not a full history of every attempt.
"""

from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass
from pathlib import Path

from .health import HealthSnapshot
from .qrcode_parse import ParsedQr

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "test_log.csv"

FIELDNAMES = [
    "timestamp",
    "qr_raw",
    "product_code",
    "week",
    "year",
    "serial",
    "result",
    "mavlink_ok",
    "imu1_ok",
    "imu1_type",
    "imu1_accel_mag",
    "imu2_ok",
    "imu2_type",
    "imu2_accel_mag",
    "baro_ok",
    "baro_type",
    "baro_pressure",
    "vbat_ok",
    "vbat_voltage",
]


@dataclass
class TestResult:
    qr: ParsedQr
    snapshot: HealthSnapshot
    passed: bool
    timestamp: datetime.datetime


def _row(result: TestResult) -> dict:
    snap = result.snapshot
    return {
        "timestamp": result.timestamp.isoformat(timespec="seconds"),
        "qr_raw": result.qr.raw,
        "product_code": result.qr.product_code,
        "week": result.qr.week,
        "year": result.qr.year,
        "serial": result.qr.serial,
        "result": "PASS" if result.passed else "FAIL",
        "mavlink_ok": snap.mavlink_ok,
        "imu1_ok": snap.imu1_ok,
        "imu1_type": snap.imu1_type,
        "imu1_accel_mag": snap.imu1_accel_mag,
        "imu2_ok": snap.imu2_ok,
        "imu2_type": snap.imu2_type,
        "imu2_accel_mag": snap.imu2_accel_mag,
        "baro_ok": snap.baro_ok,
        "baro_type": snap.baro_type,
        "baro_pressure": snap.baro_pressure,
        "vbat_ok": snap.vbat_ok,
        "vbat_voltage": snap.vbat_voltage,
    }


def append_result(result: TestResult, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """Write one row for this serial, replacing any existing row for the
    same serial (identified by product_code+week+year+serial, since the
    serial field alone resets every year/week per the QR format)."""
    key = (result.qr.product_code, result.qr.week, result.qr.year, result.qr.serial)

    rows: list[dict] = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    def row_key(r: dict) -> tuple:
        return (r["product_code"], int(r["week"]), int(r["year"]), r["serial"])

    rows = [r for r in rows if row_key(r) != key]
    rows.append(_row(result))

    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
