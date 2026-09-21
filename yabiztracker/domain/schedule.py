from __future__ import annotations

from datetime import datetime, timedelta


def next_wall_clock_occurrence(
    previous: datetime | None,
    now: datetime,
    interval_hours: int,
) -> datetime:
    """Return the next scheduled occurrence strictly after ``now``.

    ``previous`` is the persisted wall-clock occurrence. If it is already
    overdue, skipped occurrences are collapsed into one future occurrence;
    missed jobs are never replayed in a burst.
    """
    hours = max(1, int(interval_hours))
    if previous is None:
        return now + timedelta(hours=hours)

    candidate = previous + timedelta(hours=hours)
    while candidate <= now:
        candidate += timedelta(hours=hours)
    return candidate
