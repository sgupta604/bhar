"""T4 Stream 1 tests — the D5 window enumeration.

SPEC §13: offline only. Nothing here touches the network; `end_init` is a pure function
of the instant handed to it, which is precisely what makes the window testable.

SPEC §3 fixes the window at 30 days × 4 inits × 3 leads × 4 models = 1440. These tests
pin those counts so nobody can quietly widen the window to lift a coverage number
(SPEC §10).
"""

import socket
from datetime import datetime, timedelta, timezone

import pytest

from fetch import window

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §13: no test in this module may open a socket."""

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "SPEC §13 violation: tests/test_window.py tried to open a network socket. "
            "The window enumeration is pure arithmetic."
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# --- end_init ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # now - 30 h = 2026-09-02 21:37 -> latest synoptic at or before is 18z
        (datetime(2026, 9, 4, 3, 37, tzinfo=UTC), datetime(2026, 9, 2, 18, tzinfo=UTC)),
        # now - 30 h lands exactly on 12z -> 12z itself qualifies ("at or before")
        (datetime(2026, 9, 4, 18, 0, tzinfo=UTC), datetime(2026, 9, 3, 12, tzinfo=UTC)),
        # one second past 12z still floors to 12z
        (datetime(2026, 9, 4, 18, 0, 1, tzinfo=UTC), datetime(2026, 9, 3, 12, tzinfo=UTC)),
        # one second before 12z falls back to 06z
        (datetime(2026, 9, 4, 17, 59, 59, tzinfo=UTC), datetime(2026, 9, 3, 6, tzinfo=UTC)),
        # crossing midnight backwards: 05:00 - 30 h = 2026-09-02 23:00 -> 18z
        (datetime(2026, 9, 4, 5, 0, tzinfo=UTC), datetime(2026, 9, 2, 18, tzinfo=UTC)),
    ],
)
def test_end_init_floors_to_the_latest_synoptic_at_or_before_the_setback(
    now: datetime, expected: datetime
) -> None:
    assert window.end_init(now) == expected


def test_end_init_is_always_a_synoptic_hour() -> None:
    start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    for minutes in range(0, 60 * 48, 37):
        got = window.end_init(start + timedelta(minutes=minutes))
        assert got.hour in window.SYNOPTIC_HOURS, f"{got} is not a 00/06/12/18z init"
        assert (got.minute, got.second, got.microsecond) == (0, 0, 0)


def test_end_init_respects_the_30_hour_setback() -> None:
    """D5: the setback is what guarantees the 24 h lead has verified and archived."""
    now = datetime(2026, 9, 4, 3, 37, tzinfo=UTC)
    assert now - window.end_init(now) >= timedelta(hours=window.SETBACK_H)


def test_end_init_treats_a_naive_datetime_as_utc() -> None:
    """`fetch/grib.py:_as_utc` rule — a naive datetime is UTC, never local."""
    naive = datetime(2026, 9, 4, 3, 37)
    aware = datetime(2026, 9, 4, 3, 37, tzinfo=UTC)
    assert window.end_init(naive) == window.end_init(aware)
    assert window.end_init(naive).tzinfo is not None


def test_end_init_never_reads_the_clock() -> None:
    """Pure function of its argument: same input, same answer, always."""
    now = datetime(2026, 9, 4, 3, 37, tzinfo=UTC)
    assert window.end_init(now) == window.end_init(now)


# --- init_times --------------------------------------------------------------------------


def test_init_times_has_120_slots_ascending_over_714_hours() -> None:
    end = datetime(2026, 9, 2, 18, tzinfo=UTC)
    inits = window.init_times(end)

    assert len(inits) == 120, "SPEC §3: 30 days x 4 synoptic inits = 120 (never widen this)"
    assert inits == sorted(inits), "inits must be ascending"
    assert inits[-1] == end, "the window ends at end_init inclusive"
    assert inits[-1] - inits[0] == timedelta(hours=119 * 6) == timedelta(hours=714)
    assert all(i.tzinfo is not None and i.utcoffset() == timedelta(0) for i in inits)
    assert all(i.hour in window.SYNOPTIC_HOURS for i in inits)


def test_init_times_steps_exactly_six_hours() -> None:
    inits = window.init_times(datetime(2026, 9, 2, 18, tzinfo=UTC))
    steps = {b - a for a, b in zip(inits, inits[1:], strict=False)}
    assert steps == {timedelta(hours=6)}


def test_init_times_rejects_a_non_positive_count() -> None:
    with pytest.raises(ValueError):
        window.init_times(datetime(2026, 9, 2, 18, tzinfo=UTC), n=0)


# --- work_items --------------------------------------------------------------------------


def test_work_items_is_1440_with_360_per_model_and_120_per_model_lead() -> None:
    """The coverage denominators live or die on these counts (research D4)."""
    inits = window.init_times(datetime(2026, 9, 2, 18, tzinfo=UTC))
    items = window.work_items(inits)

    assert len(items) == 1440, "30 days x 4 inits x 3 leads x 4 models"
    assert len(set(items)) == 1440, "work items must be unique — a duplicate double-counts"

    for model in ("hrrr", "gfs", "nam", "nbm"):
        per_model = [it for it in items if it[0] == model]
        assert len(per_model) == 360, f"{model}: coverage denominator is 360 (D4)"
        for lead in (6, 12, 24):
            per_lead = [it for it in per_model if it[2] == lead]
            assert len(per_lead) == 120, f"{model} f{lead:03d}: per-lead denominator is 120"


def test_work_items_are_all_tz_aware_utc_with_int_leads() -> None:
    inits = window.init_times(datetime(2026, 9, 2, 18, tzinfo=UTC), n=3)
    for model, init, lead in window.work_items(inits):
        assert isinstance(model, str)
        assert init.tzinfo is not None and init.utcoffset() == timedelta(0)
        assert isinstance(lead, int)


def test_work_items_treats_naive_inits_as_utc() -> None:
    items = window.work_items([datetime(2026, 9, 2, 18)], models=("hrrr",), leads=(6,))
    assert items[0][1] == datetime(2026, 9, 2, 18, tzinfo=UTC)


# --- obs_bounds --------------------------------------------------------------------------


def test_obs_bounds_pads_one_hour_either_side_of_the_covered_valid_times() -> None:
    inits = window.init_times(datetime(2026, 9, 2, 18, tzinfo=UTC))
    start, end = window.obs_bounds(inits)

    # earliest valid = first init + 6 h; latest valid = last init + 24 h
    assert start == inits[0] + timedelta(hours=6) - timedelta(hours=1)
    assert end == inits[-1] + timedelta(hours=24) + timedelta(hours=1)
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start < end


def test_obs_bounds_span_covers_at_least_720_hours() -> None:
    """The §8 floor's "obs cover ~720 hours" needs the request window to reach that far."""
    inits = window.init_times(datetime(2026, 9, 2, 18, tzinfo=UTC))
    start, end = window.obs_bounds(inits)
    assert (end - start) >= timedelta(hours=720)


def test_obs_bounds_rejects_an_empty_window() -> None:
    with pytest.raises(ValueError):
        window.obs_bounds([])


# --- default_window ----------------------------------------------------------------------


def test_default_window_is_end_init_plus_its_inits() -> None:
    now = datetime(2026, 9, 4, 3, 37, tzinfo=UTC)
    end, inits = window.default_window(now)
    assert end == window.end_init(now)
    assert inits == window.init_times(end)
    assert len(inits) == 120
