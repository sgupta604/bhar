"""Synoptic cycle selection, the fallback ladder, age and staleness (F2, Stream 2).

FORECAST-SPEC §5.2 and §9 rule 11.

**This module is pure by construction: no network, no file I/O, and no wall clock.**
Every instant it works with is passed in as an argument, so the whole of the cycle
ladder — the boundary between 06z and 12z, the day rollover, the 9-hour staleness
threshold — is exercisable at frozen instants with no mocking and no fixtures. That
matters because this is *all* of F2's risky logic and *none* of F2's risky I/O: the
network, the disk cache and the thread pool live next door in `forecast/live.py`, and
they can be tested with an injected fetcher precisely because the arithmetic they drive
was settled here.

It is the direct twin of `fetch/window.py`, which does the same job for the 30-day
backtest window with a 30 h setback instead of 4 h.

Conventions:

* **UTC everywhere** (SPEC §2). A naive datetime is UTC, never local time.
* **No bare `assert`** — `python -O` strips them, so every guard raises a real exception
  whose message cites the clause it enforces (TR7).
"""

from __future__ import annotations

from datetime import datetime, timedelta

# `_as_utc` is imported across the package deliberately: SPEC §2's naive-is-UTC rule must
# have exactly ONE implementation, and `fetch/grib.py` owns it. `fetch/window.py:26` sets
# the precedent. Reimplementing it here is how the two halves of the project quietly drift.
from fetch.grib import _as_utc

# --- constants ---------------------------------------------------------------------------

SYNOPTIC_HOURS: tuple[int, ...] = (0, 6, 12, 18)
SETBACK_H = 4  # §5.2 archive-latency margin: the target cycle is at least 4 h old.
INIT_STEP_H = 6  # synoptic inits are 6 h apart.
MAX_CYCLES_BACK = 3  # §5.2: at most 3 fallbacks, so 4 candidates spanning 18 h.
STALE_AGE_MIN = 540  # §5.2 nine hours. §9 rule 11 is `age_minutes > 540`, strictly.


# --- cycle selection ---------------------------------------------------------------------


def target_cycle(now_utc: datetime) -> datetime:
    """Latest synoptic init **at or before** `now_utc - 4 h`, tz-aware UTC (§5.2).

    "At or before" is inclusive: 16:00Z minus the setback is exactly 12:00Z, and 12z is
    therefore the target — not 06z.

    Pure: the instant is an argument, never read from the clock. A naive `now_utc` is
    treated as UTC (`fetch/grib.py:_as_utc`), never as local time.
    """
    cutoff = _as_utc(now_utc) - timedelta(hours=SETBACK_H)
    floored = cutoff.replace(minute=0, second=0, microsecond=0)
    return floored - timedelta(hours=floored.hour % INIT_STEP_H)


def candidate_cycles(target: datetime) -> tuple[datetime, ...]:
    """The fallback ladder: `target` then 3 earlier inits, descending, 6 h apart (§5.2).

    Four entries spanning 18 h. `candidate_cycles(t)[0] is` the target itself, so a caller
    that walks the ladder tries the target first and counts fallbacks by index.
    """
    init = _as_utc(target)
    if init.hour not in SYNOPTIC_HOURS:
        raise ValueError(
            f"FORECAST-SPEC §5.2: a cycle init must be one of {SYNOPTIC_HOURS} UTC; "
            f"got hour={init.hour} from {target!r}."
        )
    if (init.minute, init.second, init.microsecond) != (0, 0, 0):
        raise ValueError(
            f"FORECAST-SPEC §5.2: a cycle init must fall exactly on the hour; got {target!r}."
        )
    return tuple(
        init - timedelta(hours=INIT_STEP_H * i) for i in range(MAX_CYCLES_BACK + 1)
    )


def run_label(init: datetime) -> str:
    """The human label for a cycle: `"00z"`, `"06z"`, `"12z"`, `"18z"` (§9).

    Zero-padded, lowercase `z`. The hour is read in UTC, so a `+02:00` instant labels by
    its UTC hour rather than its local one.
    """
    return f"{_as_utc(init).hour:02d}z"


# --- age and staleness -------------------------------------------------------------------


def age_minutes(init: datetime, now: datetime) -> int:
    """Whole minutes elapsed from `init` to `now`, **floored** (§9 `meta.cycle.age_minutes`).

    Floor, not round: a minute that has not fully elapsed has not elapsed. Both instants
    are coerced to UTC first, so a naive one is UTC and an offset one is compared correctly.
    """
    delta = _as_utc(now) - _as_utc(init)
    return int(delta.total_seconds() // 60)


def staleness(cycles_fallen_back: int, age_minutes: int) -> tuple[bool, str | None]:
    """`(is_stale, stale_reason)` for a served cycle (§5.2, §9 rule 11).

    Stale **iff** the ladder fell back at all (`cycles_fallen_back > 0`) **or** the cycle is
    older than `STALE_AGE_MIN` minutes — strictly greater, so 540 is fresh and 541 is not.

    §9 rule 11: `stale_reason` is non-null **exactly when** `is_stale` is true, and it names
    **every** cause that fired, because a banner that says "stale" without saying why sends
    the reader hunting. Note that the age cause is reachable with no fallback at all: a
    target cycle's own age lives in [4 h, 10 h), which straddles the 9 h threshold.
    """
    if cycles_fallen_back < 0:
        raise ValueError(
            f"FORECAST-SPEC §5.2: cycles_fallen_back cannot be negative; "
            f"got {cycles_fallen_back}."
        )
    if age_minutes < 0:
        raise ValueError(
            f"FORECAST-SPEC §5.2: a cycle cannot be younger than its init; "
            f"got age_minutes={age_minutes}."
        )

    causes: list[str] = []
    if cycles_fallen_back > 0:
        causes.append(
            f"fallback: served {cycles_fallen_back} cycle(s) behind the target init"
        )
    if age_minutes > STALE_AGE_MIN:
        causes.append(f"age: {age_minutes} min exceeds the {STALE_AGE_MIN} min limit")

    if not causes:
        return False, None
    return True, "FORECAST-SPEC §5.2 stale — " + "; ".join(causes)
