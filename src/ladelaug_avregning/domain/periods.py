"""Calendar-month helpers for the settlement calendar.

A *period* is a local (Europe/Oslo by default) calendar month keyed ``YYYY-MM``.
Charging sessions arrive with UTC timestamps; the settlement they belong to is
decided by the *local* month of each instant, and a session that crosses a
month boundary is split there (US-405).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ladelaug_avregning import clock

_MONTH_LEN = 7  # "YYYY-MM"


def current_month(tz: str) -> str:
    d = clock.now_utc().astimezone(ZoneInfo(tz))
    return f"{d.year:04d}-{d.month:02d}"


def _parse(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso.strip())
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_dt(iso_utc: str, tz: str) -> datetime:
    return _parse(iso_utc).astimezone(ZoneInfo(tz))


def month_key(iso_utc: str, tz: str) -> str:
    d = local_dt(iso_utc, tz)
    return f"{d.year:04d}-{d.month:02d}"


def valid_month(month: str) -> bool:
    if len(month) != _MONTH_LEN or month[4] != "-":
        return False
    try:
        y, m = int(month[:4]), int(month[5:])
    except ValueError:
        return False
    return 1 <= m <= 12 and y >= 1970


def add_month(month: str, delta: int = 1) -> str:
    y, m = int(month[:4]), int(month[5:])
    idx = (y * 12 + (m - 1)) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_range(from_month: str, to_month: str) -> list[str]:
    """Inclusive list of month keys from ``from_month`` to ``to_month``."""
    out: list[str] = []
    cur = from_month
    while cur <= to_month:
        out.append(cur)
        cur = add_month(cur)
    return out


def month_bounds(month: str, tz: str) -> tuple[datetime, datetime]:
    """``[start, end)`` of the local month as UTC instants."""
    zone = ZoneInfo(tz)
    y, m = int(month[:4]), int(month[5:])
    start_local = datetime(y, m, 1, tzinfo=zone)
    end_local = datetime(*divmod_next(y, m), tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def divmod_next(year: int, month: int) -> tuple[int, int, int]:
    """(year, month, day=1) of the month after the given one."""
    return (year + 1, 1, 1) if month == 12 else (year, month + 1, 1)


def split_across_months(
    start_iso: str, end_iso: str, tz: str
) -> list[tuple[str, datetime, datetime]]:
    """Split ``[start, end)`` at local month boundaries.

    Returns ``[(month_key, part_start_utc, part_end_utc), ...]`` in order. A
    session wholly inside one month yields a single part. A zero/negative
    duration yields one part in the start month.
    """
    start = _parse(start_iso)
    end = _parse(end_iso) if end_iso else start
    if end <= start:
        return [(month_key(start_iso, tz), start, start)]

    parts: list[tuple[str, datetime, datetime]] = []
    cursor = start
    while cursor < end:
        mkey = month_key(cursor.isoformat(), tz)
        _, month_end = month_bounds(mkey, tz)
        part_end = min(end, month_end)
        parts.append((mkey, cursor, part_end))
        cursor = part_end
    return parts


def duration_seconds(a: datetime, b: datetime) -> float:
    return max((b - a) / timedelta(seconds=1), 0.0)
