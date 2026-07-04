"""Detect whether a board on a serial port is running the PX4-style
AP_Bootloader sync protocol, as opposed to application firmware
(which speaks MAVLink and never responds to this probe).

Protocol reference: Tools/scripts/uploader.py (GET_SYNC/INSYNC/OK),
which itself documents compatibility with the legacy PX4 bootloader
protocol used by Tools/AP_Bootloader.
"""

from __future__ import annotations

import time

import serial

GET_SYNC = b"\x21"
EOC = b"\x20"
INSYNC = b"\x12"
OK = b"\x10"

PROBE = GET_SYNC + EOC
EXPECTED = INSYNC + OK

# Bootloaders on these boards run at this baud rate before any
# flightstack baud switch would apply (matches uploader.py default).
BOOTLOADER_BAUD = 115200


def probe_bootloader(port_name: str, timeout: float = 0.4) -> bool:
    """Return True if the board answers the bootloader sync handshake.

    Opens and closes the port itself. Non-destructive: GET_SYNC is a
    read-only handshake, it does not erase or program anything.
    """
    try:
        with serial.Serial(port_name, BOOTLOADER_BAUD, timeout=timeout) as ser:
            ser.reset_input_buffer()
            ser.write(PROBE)
            ser.flush()
            deadline = time.monotonic() + timeout
            buf = b""
            while time.monotonic() < deadline and len(buf) < len(EXPECTED):
                chunk = ser.read(len(EXPECTED) - len(buf))
                if not chunk:
                    break
                buf += chunk
            return buf == EXPECTED
    except serial.SerialException:
        return False
