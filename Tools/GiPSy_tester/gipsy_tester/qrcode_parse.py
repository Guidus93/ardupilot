"""Parse GiPSy production QR codes: PRODUCT_WWYY_SERIAL, e.g.
EV0004_2426_0092 -> product EV0004, week 24 of 2026, serial 0092.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_QR_RE = re.compile(r"^(?P<product>[^_]+)_(?P<week>\d{2})(?P<year>\d{2})_(?P<serial>\d{4})$")


@dataclass
class ParsedQr:
    raw: str
    product_code: str
    week: int
    year: int
    serial: str


def parse_qr(raw: str) -> ParsedQr:
    m = _QR_RE.match(raw)
    if not m:
        raise ValueError(f"expected PRODUCT_WWYY_SERIAL format (e.g. EV0004_2426_0092), got {raw!r}")
    week = int(m.group("week"))
    if not 1 <= week <= 53:
        raise ValueError(f"week {week:02d} out of range 01-53 in {raw!r}")
    return ParsedQr(
        raw=raw,
        product_code=m.group("product"),
        week=week,
        year=2000 + int(m.group("year")),
        serial=m.group("serial"),
    )
