"""The single source of "now".

Everything that needs the current time goes through here so tests can freeze it
by monkeypatching ``now_utc`` (see the ``frozen_now`` fixture). ``today_oslo`` is
the calendar day used for effective-dated rows (Europe/Oslo).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

OSLO = "Europe/Oslo"


def now_utc() -> datetime:
    """Timezone-aware current instant in UTC."""
    return datetime.now(UTC)


def today_oslo(tz: str = OSLO) -> date:
    """Current calendar day in the given IANA zone (Europe/Oslo by default)."""
    return now_utc().astimezone(ZoneInfo(tz)).date()
