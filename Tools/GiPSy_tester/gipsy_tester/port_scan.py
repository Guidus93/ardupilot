"""Find candidate serial ports for an ArduPilot ChibiOS board.

Bootloader and application firmware both enumerate with the same
default ChibiOS USB VID:PID (see hwdef generator defaults):
    VID 0x1209
    PID 0x5741  (single CDC, the default for these boards)
    PID 0x5740  (dual CDC, only if a board sets dual_USB_enabled)

We can't tell bootloader vs. app apart from VID/PID alone -- that is
resolved later by bootloader.probe_bootloader().
"""

from __future__ import annotations

from dataclasses import dataclass

import serial.tools.list_ports

ARDUPILOT_VID = 0x1209
ARDUPILOT_PIDS = (0x5741, 0x5740)

# Fallback for boards/drivers that don't report VID/PID cleanly over
# a given Windows USB stack: match on description/manufacturer text.
DESCRIPTION_HINTS = ("ardupilot", "chibios", "gipsy", "patrionic")


@dataclass
class CandidatePort:
    device: str
    description: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    # True when matched on ArduPilot's exact USB VID:PID (high confidence);
    # False when only a description/manufacturer hint matched (a guess).
    strong_match: bool = False

    @property
    def label(self) -> str:
        return f"{self.device} ({self.description})"


def _is_vidpid_match(info) -> bool:
    return info.vid == ARDUPILOT_VID and info.pid in ARDUPILOT_PIDS


def _matches(info) -> bool:
    if _is_vidpid_match(info):
        return True
    text = f"{info.description or ''} {info.manufacturer or ''}".lower()
    return any(hint in text for hint in DESCRIPTION_HINTS)


def find_candidate_ports() -> list[CandidatePort]:
    """Return likely ArduPilot ports, VID/PID matches first."""
    ports = list(serial.tools.list_ports.comports())
    matched = [p for p in ports if _matches(p)]
    others = [p for p in ports if p not in matched]

    ordered = matched + others
    return [
        CandidatePort(
            device=p.device,
            description=p.description or "",
            vid=p.vid,
            pid=p.pid,
            serial_number=p.serial_number,
            strong_match=_is_vidpid_match(p),
        )
        for p in ordered
    ]
