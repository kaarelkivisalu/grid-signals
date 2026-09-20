"""Temporal contract: issue times, NWP runs, delivery days and lead times.

Every other module depends on these definitions, so they live in one place and are
covered by property tests. See `research/docs/dataflow.md` section 1.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

#: Bidding-zone local time. SE1-SE4 and DE-LU both observe Central European Time.
MARKET_TZ = ZoneInfo("Europe/Stockholm")

#: Forecasts are issued at 09:00 UTC. Gate closure is 12:00 local, which is 11:00 UTC
#: under CET but 10:00 UTC under CEST -- 09:00 keeps at least an hour of slack
#: year-round.
ISSUE_HOUR_UTC = 9

#: Only the 00z run is used, named explicitly rather than "latest available".
NWP_RUN_HOUR_UTC = 0


def issue_time(issue_day: date) -> datetime:
    """Return the forecast issue instant for a given issue day."""
    return datetime(
        issue_day.year, issue_day.month, issue_day.day, ISSUE_HOUR_UTC, tzinfo=UTC
    )


def nwp_run_time(issue_day: date) -> datetime:
    """Return the NWP run instant used by a forecast issued on `issue_day`."""
    return datetime(
        issue_day.year, issue_day.month, issue_day.day, NWP_RUN_HOUR_UTC, tzinfo=UTC
    )


def delivery_day(issue_day: date) -> date:
    """Return the delivery day a forecast issued on `issue_day` targets."""
    return issue_day + timedelta(days=1)


def delivery_day_starts(
    day: date, tz: ZoneInfo = MARKET_TZ, resolution: timedelta = timedelta(hours=1)
) -> list[datetime]:
    """Return the UTC start instant of every market interval in a local delivery day.

    Yields 23, 24 or 25 hourly intervals depending on daylight-saving transitions:
    the spring-forward day is 23 hours long and the autumn-back day 25.
    """
    local_start = datetime(day.year, day.month, day.day, tzinfo=tz)
    # Aware arithmetic adds to the wall clock and keeps the zone, so this is the next
    # local midnight rather than a fixed 24 hours later.
    local_end = local_start + timedelta(days=1)

    cursor = local_start.astimezone(UTC)
    stop = local_end.astimezone(UTC)
    starts = []
    while cursor < stop:
        starts.append(cursor)
        cursor += resolution
    return starts


def lead_hours(issue_day: date, **kwargs) -> list[int]:
    """Return the lead time, in whole hours from the NWP run, of each interval start.

    Spans +22..+46 for interval starts; the covered window therefore ends at +47.
    """
    run = nwp_run_time(issue_day)
    return [
        round((start - run).total_seconds() / 3600)
        for start in delivery_day_starts(delivery_day(issue_day), **kwargs)
    ]
