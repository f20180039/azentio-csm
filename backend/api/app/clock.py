"""Wall clock in the business time zone; tests swap in a fixed one."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import TIMEZONE


class Clock:
    def __init__(self, fixed: datetime | None = None, zone: str = TIMEZONE):
        self.zone = ZoneInfo(zone)
        self._fixed = fixed

    def now(self) -> datetime:
        """Aware datetime in the business zone."""
        base = self._fixed or datetime.now(timezone.utc)
        return base.astimezone(self.zone)

    def today(self) -> date:
        return self.now().date()

    def instant(self) -> str:
        return iso(self.now())


def iso(dt: datetime) -> str:
    """UTC ISO-8601 with a Z suffix, as Java's Instant prints it."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
