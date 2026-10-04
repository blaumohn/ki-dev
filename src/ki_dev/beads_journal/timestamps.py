"""RFC-3339-Zeitpunkte ohne Verlust der Sekundenbruchteile."""

import re
from datetime import datetime
from decimal import Decimal

TIMESTAMP_PATTERN = (
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})"
)


def timestamp(value: str) -> tuple[datetime, Decimal]:
    match = re.fullmatch(TIMESTAMP_PATTERN, value)
    if match is None:
        raise ValueError("ungültiger Zeitstempel")
    zone = match[2]
    if zone != "Z" and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
        raise ValueError("ungültige Zeitzone")
    seconds = datetime.fromisoformat(value[:19] + zone)
    return seconds, Decimal("0." + (match[1] or "0"))
