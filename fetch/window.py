"""The 30-day backtest window, enumerated deterministically (T4, Stream 1 — research D5).

One module owns the window so `fetch/backfill.py`, `fetch/obs.py` and (via
`data/coverage.json`) T5 all agree on which 120 model runs are in scope. The bounds are
written into `coverage.json` so T5 **reads** them rather than recomputing and drifting.

Window definition (D5):

* `end_init` = the latest synoptic init (00/06/12/18z) **at or before `now_utc - 30 h`**.
  The 30-hour setback guarantees the 24 h lead has verified and cleared archive latency.
* 120 inits step back 6 h from `end_init` inclusive → 30 days × 4 inits.
* Leads 6/12/24 h × 4 models → **1440** work items, 360 per model, 120 per (model, lead).
* Obs bounds = `[min(valid_time) - 1 h, max(valid_time) + 1 h]`.

**SPEC §3 fixes this window at 30 days. Never widen it, shorten it, or drop a lead time
to make a coverage number look better (SPEC §10 / §9).** Coverage is a result to report.

`end_init` never reads the clock itself — it is a pure function of its argument, so the
whole enumeration is testable at fixed instants.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fetch.grib import MODELS, _as_utc

SYNOPTIC_HOURS = (0, 6, 12, 18)
LEADS_H = (6, 12, 24)
N_INITS = 120  # 30 days x 4 synoptic inits per day (SPEC §3)
SETBACK_H = 30  # 24 h lead + 6 h archive latency margin (D5)
INIT_STEP_H = 6


def end_init(now_utc: datetime) -> datetime:
    """Latest synoptic init at or before `now_utc - 30 h`, tz-aware UTC.

    Pure: takes the instant as an argument and never calls `datetime.now()`.
    A naive input is treated as UTC, never local time (`fetch/grib.py:_as_utc`).
    """
    cutoff = _as_utc(now_utc) - timedelta(hours=SETBACK_H)
    floored = cutoff.replace(minute=0, second=0, microsecond=0)
    return floored - timedelta(hours=floored.hour % INIT_STEP_H)


def init_times(end: datetime, n: int = N_INITS) -> list[datetime]:
    """`n` synoptic inits stepping back 6 h from `end` inclusive, **ascending**, UTC."""
    if n < 1:
        raise ValueError(f"n must be >= 1; got {n}")
    end_utc = _as_utc(end)
    return [end_utc - timedelta(hours=INIT_STEP_H * i) for i in range(n - 1, -1, -1)]


def work_items(
    inits: list[datetime],
    models: tuple[str, ...] = MODELS,
    leads: tuple[int, ...] = LEADS_H,
) -> list[tuple[str, datetime, int]]:
    """Every `(model, init_time, lead_h)` in the window — 1440 at the defaults."""
    return [
        (model, _as_utc(init), int(lead))
        for model in models
        for init in inits
        for lead in leads
    ]


def valid_times(inits: list[datetime], leads: tuple[int, ...] = LEADS_H) -> list[datetime]:
    """Every forecast valid time covered by the window, tz-aware UTC."""
    return [_as_utc(init) + timedelta(hours=int(lead)) for init in inits for lead in leads]


def obs_bounds(
    inits: list[datetime], leads: tuple[int, ...] = LEADS_H
) -> tuple[datetime, datetime]:
    """`(earliest valid - 1 h, latest valid + 1 h)` — the IEM request window (D5).

    The 1 h padding is so T5's ±30 min nearest join has an observation on both sides of
    every target hour. It is **not** licence to widen the forecast window.
    """
    covered = valid_times(inits, leads)
    if not covered:
        raise ValueError("no valid times: the window is empty")
    return min(covered) - timedelta(hours=1), max(covered) + timedelta(hours=1)


def default_window(
    now_utc: datetime | None = None, n_inits: int = N_INITS
) -> tuple[datetime, list[datetime]]:
    """`(end_init, inits)` for `now_utc` (defaults to the wall clock at the boundary)."""
    now = datetime.now(timezone.utc) if now_utc is None else now_utc
    end = end_init(now)
    return end, init_times(end, n_inits)
