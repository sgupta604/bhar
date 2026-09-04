"""F2 Stream 2 tests — `forecast/cycle.py`, the pure clock logic.

FORECAST-SPEC §5.2 / §9 rule 11. SPEC §13: offline only. Every function under test is a
pure function of the instant handed to it, which is exactly what makes the whole cycle
ladder testable at frozen instants. **This file contains no `datetime.now()`, no file
I/O and no network** — an autouse fixture blocks sockets to keep it that way.

The staleness assertions deliberately check the *substance* of `stale_reason` (that it
names the fallback count, or the age in minutes) rather than an exact string: the wording
may be improved, but a reason that fails to say *why* is a contract violation.
"""

import socket
from datetime import datetime, timedelta, timezone

import pytest

from forecast import cycle

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §13: no test in this module may open a socket."""

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "SPEC §13 violation: tests/test_cycle.py tried to open a network socket. "
            "forecast/cycle.py is pure arithmetic over an injected instant."
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# --- T1: target_cycle boundaries ---------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # 16:53Z - 4 h = 12:53Z -> latest synoptic at or before is 12z
        (datetime(2026, 9, 4, 16, 53, tzinfo=UTC), datetime(2026, 9, 4, 12, tzinfo=UTC)),
        # 16:00Z - 4 h lands EXACTLY on 12:00Z. "At or before" is INCLUSIVE -> 12z, not 06z.
        (datetime(2026, 9, 4, 16, 0, tzinfo=UTC), datetime(2026, 9, 4, 12, tzinfo=UTC)),
        # one second past the boundary still floors to 12z
        (datetime(2026, 9, 4, 16, 0, 1, tzinfo=UTC), datetime(2026, 9, 4, 12, tzinfo=UTC)),
        # 15:59Z - 4 h = 11:59Z -> 06z
        (datetime(2026, 9, 4, 15, 59, tzinfo=UTC), datetime(2026, 9, 4, 6, tzinfo=UTC)),
        # 03:30Z - 4 h = 23:30Z the PREVIOUS day -> that day's 18z (day rollover)
        (datetime(2026, 9, 4, 3, 30, tzinfo=UTC), datetime(2026, 9, 3, 18, tzinfo=UTC)),
    ],
)
def test_target_cycle_floors_to_the_latest_synoptic_at_or_before_the_setback(
    now: datetime, expected: datetime
) -> None:
    assert cycle.target_cycle(now) == expected


def test_target_cycle_is_always_a_tz_aware_synoptic_init() -> None:
    start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    for minutes in range(0, 60 * 48, 17):
        got = cycle.target_cycle(start + timedelta(minutes=minutes))
        assert got.tzinfo is not None, f"{got!r} is not tz-aware"
        assert got.utcoffset() == timedelta(0), f"{got!r} is not UTC"
        assert got.hour in cycle.SYNOPTIC_HOURS, f"{got} is not a 00/06/12/18z init"
        assert (got.minute, got.second, got.microsecond) == (0, 0, 0)


def test_target_cycle_respects_the_four_hour_setback() -> None:
    """§5.2: the 4 h setback is the archive-latency margin."""
    assert cycle.SETBACK_H == 4
    now = datetime(2026, 9, 4, 16, 53, tzinfo=UTC)
    assert now - cycle.target_cycle(now) >= timedelta(hours=cycle.SETBACK_H)


def test_target_cycle_age_lives_in_four_to_ten_hours() -> None:
    """Why T7 is reachable with no fallback: a target cycle is 4-10 h old, and 10 h > 540 min."""
    start = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    for minutes in range(0, 60 * 30, 7):
        now = start + timedelta(minutes=minutes)
        age = cycle.age_minutes(cycle.target_cycle(now), now)
        assert 4 * 60 <= age < 10 * 60, f"age {age} min out of [240, 600) at {now}"


# --- T2: a naive instant is UTC, never local ---------------------------------------------


def test_naive_now_is_treated_as_utc_never_local() -> None:
    naive = datetime(2026, 9, 4, 16, 53)
    aware = datetime(2026, 9, 4, 16, 53, tzinfo=UTC)
    assert cycle.target_cycle(naive) == cycle.target_cycle(aware)
    assert cycle.target_cycle(naive) == datetime(2026, 9, 4, 12, tzinfo=UTC)
    assert cycle.target_cycle(naive).tzinfo is not None


def test_naive_inputs_are_utc_everywhere_else_too() -> None:
    naive_init = datetime(2026, 9, 4, 12)
    aware_init = datetime(2026, 9, 4, 12, tzinfo=UTC)
    assert cycle.candidate_cycles(naive_init) == cycle.candidate_cycles(aware_init)
    assert cycle.run_label(naive_init) == cycle.run_label(aware_init) == "12z"
    assert cycle.age_minutes(naive_init, datetime(2026, 9, 4, 16, 53)) == cycle.age_minutes(
        aware_init, datetime(2026, 9, 4, 16, 53, tzinfo=UTC)
    )


# --- T3: candidate_cycles ----------------------------------------------------------------


def test_candidate_cycles_is_four_descending_six_hourly_inits_spanning_eighteen_hours() -> None:
    target = datetime(2026, 9, 4, 12, tzinfo=UTC)
    got = cycle.candidate_cycles(target)

    assert isinstance(got, tuple)
    assert len(got) == cycle.MAX_CYCLES_BACK + 1 == 4
    assert got[0] == target, "the target itself must be the first candidate"
    assert all(c.tzinfo is not None and c.utcoffset() == timedelta(0) for c in got)
    assert all(c.hour in cycle.SYNOPTIC_HOURS for c in got)
    assert list(got) == sorted(got, reverse=True), "candidates must strictly descend"
    assert len(set(got)) == 4, "candidates must be distinct"
    deltas = [got[i] - got[i + 1] for i in range(3)]
    assert deltas == [timedelta(hours=cycle.INIT_STEP_H)] * 3
    assert got[0] - got[-1] == timedelta(hours=18)
    assert got == (
        datetime(2026, 9, 4, 12, tzinfo=UTC),
        datetime(2026, 9, 4, 6, tzinfo=UTC),
        datetime(2026, 9, 4, 0, tzinfo=UTC),
        datetime(2026, 9, 3, 18, tzinfo=UTC),
    )


def test_candidate_cycles_rolls_the_day_backwards() -> None:
    got = cycle.candidate_cycles(datetime(2026, 1, 1, 0, tzinfo=UTC))
    assert got[-1] == datetime(2025, 12, 31, 6, tzinfo=UTC)


def test_candidate_cycles_rejects_a_non_synoptic_init() -> None:
    with pytest.raises(ValueError, match="FORECAST-SPEC"):
        cycle.candidate_cycles(datetime(2026, 9, 4, 7, tzinfo=UTC))


def test_candidate_cycles_rejects_an_init_that_is_not_on_the_hour() -> None:
    with pytest.raises(ValueError, match="FORECAST-SPEC"):
        cycle.candidate_cycles(datetime(2026, 9, 4, 12, 30, tzinfo=UTC))


# --- T4: run_label -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("init", "expected"),
    [
        (datetime(2026, 9, 4, 0, tzinfo=UTC), "00z"),
        (datetime(2026, 9, 4, 6, tzinfo=UTC), "06z"),
        (datetime(2026, 9, 4, 12, tzinfo=UTC), "12z"),
        (datetime(2026, 9, 4, 18, tzinfo=UTC), "18z"),
    ],
)
def test_run_label_is_zero_padded_and_lowercase(init: datetime, expected: str) -> None:
    got = cycle.run_label(init)
    assert got == expected
    assert len(got) == 3
    assert got.endswith("z") and not got.endswith("Z")


def test_run_label_covers_every_candidate_of_every_target() -> None:
    target = cycle.target_cycle(datetime(2026, 9, 4, 3, 30, tzinfo=UTC))
    labels = {cycle.run_label(c) for c in cycle.candidate_cycles(target)}
    assert labels == {"00z", "06z", "12z", "18z"}


# --- T5: age_minutes ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("init", "now", "expected"),
    [
        (datetime(2026, 9, 4, 12, tzinfo=UTC), datetime(2026, 9, 4, 12, tzinfo=UTC), 0),
        (datetime(2026, 9, 4, 12, tzinfo=UTC), datetime(2026, 9, 4, 16, tzinfo=UTC), 240),
        (datetime(2026, 9, 4, 12, tzinfo=UTC), datetime(2026, 9, 4, 16, 53, tzinfo=UTC), 293),
        # day rollover
        (datetime(2026, 9, 3, 18, tzinfo=UTC), datetime(2026, 9, 4, 3, 30, tzinfo=UTC), 570),
    ],
)
def test_age_minutes_against_a_frozen_clock(init: datetime, now: datetime, expected: int) -> None:
    assert cycle.age_minutes(init, now) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, 0), (59, 0), (60, 1), (119, 1), (3599, 59), (3600, 60)],
)
def test_age_minutes_floors_a_non_whole_minute_delta(seconds: int, expected: int) -> None:
    """The rounding is FLOOR — an almost-elapsed minute has not elapsed."""
    init = datetime(2026, 9, 4, 12, tzinfo=UTC)
    assert cycle.age_minutes(init, init + timedelta(seconds=seconds)) == expected


def test_age_minutes_floors_sub_second_deltas_too() -> None:
    init = datetime(2026, 9, 4, 12, tzinfo=UTC)
    now = datetime(2026, 9, 4, 12, 30, 45, 999999, tzinfo=UTC)
    got = cycle.age_minutes(init, now)
    assert got == 30
    assert isinstance(got, int)


def test_age_minutes_handles_a_naive_and_an_offset_instant_identically() -> None:
    init = datetime(2026, 9, 4, 12, tzinfo=UTC)
    plus_two = timezone(timedelta(hours=2))
    assert cycle.age_minutes(init, datetime(2026, 9, 4, 18, 53, tzinfo=plus_two)) == 293


# --- T6-T9: staleness --------------------------------------------------------------------


def test_staleness_fresh_target_cycle_is_not_stale() -> None:
    is_stale, reason = cycle.staleness(0, 300)
    assert is_stale is False
    assert reason is None


def test_staleness_age_alone_makes_it_stale_and_the_reason_names_the_age() -> None:
    """T7: reachable with NO fallback — a target cycle's age lives in [240, 600) min."""
    is_stale, reason = cycle.staleness(0, 541)
    assert is_stale is True
    assert reason is not None
    assert "541" in reason, f"the reason must name the age; got {reason!r}"
    assert "age" in reason.lower(), f"the reason must say it is about age; got {reason!r}"
    assert "fallback" not in reason.lower(), f"no fallback fired; got {reason!r}"


def test_staleness_fallback_alone_makes_it_stale_and_the_reason_names_the_fallback() -> None:
    is_stale, reason = cycle.staleness(1, 300)
    assert is_stale is True
    assert reason is not None
    assert "fallback" in reason.lower(), f"the reason must name the fallback; got {reason!r}"
    assert "1" in reason, f"the reason must name the fallback count; got {reason!r}"
    assert "300" not in reason, f"the age is fine and must not be blamed; got {reason!r}"


def test_staleness_names_both_causes_when_both_fire() -> None:
    is_stale, reason = cycle.staleness(2, 600)
    assert is_stale is True
    assert reason is not None
    lowered = reason.lower()
    assert "fallback" in lowered, f"missing the fallback cause; got {reason!r}"
    assert "2" in reason, f"missing the fallback count; got {reason!r}"
    assert "age" in lowered, f"missing the age cause; got {reason!r}"
    assert "600" in reason, f"missing the age value; got {reason!r}"


# --- the 540-minute boundary -------------------------------------------------------------


def test_stale_age_threshold_is_nine_hours() -> None:
    assert cycle.STALE_AGE_MIN == 540


@pytest.mark.parametrize(
    ("age", "expected_stale"),
    [(0, False), (539, False), (540, False), (541, True), (600, True)],
)
def test_the_stale_boundary_is_strictly_greater_than_540(age: int, expected_stale: bool) -> None:
    """§9 rule 11: `age_minutes > 540`. 540 itself is NOT stale; 541 is."""
    is_stale, _ = cycle.staleness(0, age)
    assert is_stale is expected_stale


# --- T10: the §9 rule 11 invariant sweep -------------------------------------------------


@pytest.mark.parametrize("fallen_back", [0, 1, 2, 3])
@pytest.mark.parametrize("age", [0, 1, 239, 240, 300, 539, 540, 541, 599, 600, 1000])
def test_stale_reason_is_non_null_exactly_when_is_stale(fallen_back: int, age: int) -> None:
    """§9 rule 11: `stale_reason is not None` <=> `is_stale`. No exceptions, ever."""
    is_stale, reason = cycle.staleness(fallen_back, age)

    assert isinstance(is_stale, bool)
    assert (reason is not None) == is_stale, (
        f"invariant broken at (fallen_back={fallen_back}, age={age}): "
        f"is_stale={is_stale!r} reason={reason!r}"
    )
    assert is_stale == (fallen_back > 0 or age > cycle.STALE_AGE_MIN)
    if reason is not None:
        assert reason.strip(), "a non-null reason must actually say something"
        if fallen_back > 0:
            assert str(fallen_back) in reason and "fallback" in reason.lower()
        if age > cycle.STALE_AGE_MIN:
            assert str(age) in reason and "age" in reason.lower()


def test_staleness_rejects_a_negative_fallback_count() -> None:
    with pytest.raises(ValueError, match="FORECAST-SPEC"):
        cycle.staleness(-1, 300)


def test_staleness_rejects_a_negative_age() -> None:
    with pytest.raises(ValueError, match="FORECAST-SPEC"):
        cycle.staleness(0, -1)


# --- the module is clock-free by construction --------------------------------------------


def test_cycle_module_never_reads_the_wall_clock() -> None:
    """TR7 / §5.2: every instant is injected. A clock inside this module is untestable."""
    source = (__import__("pathlib").Path(cycle.__file__)).read_text(encoding="utf-8")
    assert "utcnow" not in source, "datetime.utcnow() is deprecated, naive, and forbidden here"
    assert "now()" not in source, "forecast/cycle.py must never read the wall clock"
