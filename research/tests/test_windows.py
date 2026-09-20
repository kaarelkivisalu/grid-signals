"""Property tests for the temporal contract.

Time alignment is where silent, systematic errors live: an off-by-one in the
delivery-day window shifts every target by an hour and no metric will tell you.
"""

from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import pytest
from renewable_forecast import windows

# EU daylight-saving transitions: last Sunday of March and of October.
SPRING_FORWARD_2026 = date(2026, 3, 29)
AUTUMN_BACK_2026 = date(2026, 10, 25)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 1, 15), 24),
        (date(2026, 7, 15), 24),
        (SPRING_FORWARD_2026, 23),
        (AUTUMN_BACK_2026, 25),
    ],
)
def test_delivery_day_length(day: date, expected: int) -> None:
    assert len(windows.delivery_day_starts(day)) == expected


def test_delivery_day_starts_are_utc_contiguous_and_monotonic() -> None:
    starts = windows.delivery_day_starts(AUTUMN_BACK_2026)
    assert all(s.tzinfo is UTC for s in starts)
    gaps = {b - a for a, b in pairwise(starts)}
    assert gaps == {timedelta(hours=1)}


def test_delivery_day_begins_at_local_midnight() -> None:
    starts = windows.delivery_day_starts(date(2026, 1, 15))
    local_first = starts[0].astimezone(windows.MARKET_TZ)
    assert (local_first.date(), local_first.hour) == (date(2026, 1, 15), 0)


@pytest.mark.parametrize(
    ("issue_day", "first_lead"),
    [
        (date(2026, 1, 14), 23),  # CET  -> 00:00 local is 23:00 UTC the day before
        (date(2026, 7, 14), 22),  # CEST -> 00:00 local is 22:00 UTC the day before
    ],
)
def test_lead_hours_respect_the_offset(issue_day: date, first_lead: int) -> None:
    leads = windows.lead_hours(issue_day)
    assert leads[0] == first_lead
    assert leads == list(range(leads[0], leads[0] + len(leads)))


def test_lead_hours_stay_within_the_frozen_window() -> None:
    """Interval starts span +22..+46 across the year, so the window ends at +47."""
    day = date(2026, 1, 1)
    observed = set()
    while day < date(2027, 1, 1):
        observed.update(windows.lead_hours(day))
        day += timedelta(days=1)
    assert min(observed) == 22
    assert max(observed) == 46


def test_issue_time_precedes_every_target() -> None:
    issue_day = date(2026, 7, 14)
    issued = windows.issue_time(issue_day)
    assert issued == datetime(2026, 7, 14, 9, tzinfo=UTC)
    assert all(
        issued < start
        for start in windows.delivery_day_starts(windows.delivery_day(issue_day))
    )
