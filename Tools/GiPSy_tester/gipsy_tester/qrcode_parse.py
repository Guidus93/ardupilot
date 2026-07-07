"""Parse GiPSy production QR codes: PRODUCT_WWYY_SERIAL, e.g.
EV0004_2426_0092 -> product EV0004, week 24 of 2026, serial 0092.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# \d matches any Unicode decimal digit, not just ASCII 0-9 -- combined
# with the NFKC normalize below (which folds full-width letters/digits
# and the full-width underscore to their ASCII forms), this makes
# parse_qr robust to a scanner emitting full-width characters because
# the PC's input language is set to e.g. Chinese instead of English.
_QR_RE = re.compile(r"^(?P<product>[^_]+)_(?P<week>\d{2})(?P<year>\d{2})_(?P<serial>\d{4})$")


@dataclass
class ParsedQr:
    raw: str
    product_code: str
    week: int
    year: int
    serial: str


def parse_qr(raw: str) -> ParsedQr:
    normalized = unicodedata.normalize("NFKC", raw.strip())
    m = _QR_RE.match(normalized)
    if not m:
        raise ValueError(f"expected PRODUCT_WWYY_SERIAL format (e.g. EV0004_2426_0092), got {raw!r}")
    week = int(m.group("week"))
    if not 1 <= week <= 53:
        raise ValueError(f"week {week:02d} out of range 01-53 in {raw!r}")
    return ParsedQr(
        raw=normalized,
        product_code=m.group("product"),
        week=week,
        year=2000 + int(m.group("year")),
        serial=m.group("serial"),
    )
