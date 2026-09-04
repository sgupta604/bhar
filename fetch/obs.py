"""IEM ASOS observations for KOMA — fetch, parse, write `data/obs.parquet` (T4, Task 2.2).

**The non-negotiable rule: this module NEVER interpolates, resamples, rounds or floors an
observation timestamp.** ASOS reports at 5-minute intervals and the routine hourly
observation lands near `:52`, not `:00` (spike F5 — BRIEF §10 Q8's "METAR is on the hour"
is FALSE). T5 joins forecasts to observations with a ±30 min nearest match, which needs the
true minute resolution. Snap these timestamps to the hour and that join matches ZERO rows,
producing an empty frame that scores a perfect MAE and is entirely fictional (SPEC §4/§10).

The other invariants:

* **Missing means dropped, never filled.** IEM writes `M` for a missing `tmpf`. Those rows
  leave the dataset. No `ffill`, no `interpolate`, no synthetic value (SPEC §4).
* **Coverage is measured in distinct hours, not rows.** `distinct_hours()` is the SPEC §8
  acceptance measure. 900 rows crammed into 3 hours is a row count that passes and a
  dataset that is useless; `write_obs` checks the hours first, and says so when it fails.
* **UTC everywhere**, degrees F at the boundary. A naive datetime is UTC, never local
  (`fetch/grib.py:_as_utc`).
* **SPEC §11 R1 (Open-Meteo) is RETIRED and FORBIDDEN.** IEM is the only observation
  source. A non-200 is a SPEC §9 hard stop — there is nothing to fall back to.
"""

from __future__ import annotations

import argparse
import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from fetch.grib import _as_utc
from fetch.schema import OBS_SCHEMA, write_parquet_checked
from fetch.window import default_window, obs_bounds

# --- constants ---------------------------------------------------------------------------

# Spike F4 verified: station OMA = OMAHA/EPPLEY, [-95.89917, 41.31028], correct for KOMA.
# BRIEF §11's "verify the IEM station id" is resolved — do not re-probe it.
IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
STATION = "OMA"

MISSING = "M"  # IEM's missing sentinel. Dropped, never filled (SPEC §4).
COLUMNS = ["valid_time", "temp_f"]  # SPEC §6 obs.parquet column order, exactly.

DEFAULT_OUT = "data/obs.parquet"
MIN_ROWS = 700
MIN_DISTINCT_HOURS = 700  # SPEC §8: 720 hours in the window; a few genuine gaps are fine.

_TIMEOUT = 120

# Pinned dtypes so an empty result still carries the schema T5 expects.
_TIME_DTYPE = "datetime64[us, UTC]"
_TEMP_DTYPE = "float64"


# --- urls --------------------------------------------------------------------------------


def build_url(start: datetime, end: datetime, station: str = STATION) -> str:
    """Spike F4's verified IEM ASOS request URL for `[start, end]`, in UTC.

    Month and day are written unpadded (`month1=9&day1=1`), matching the probe in
    `fetch/capture_iem_fixture.py` that verified HTTP 200. A naive datetime is UTC.
    """
    first = _as_utc(start)
    last = _as_utc(end)
    return (
        f"{IEM_URL}?station={station}&data=tmpf"
        f"&year1={first.year}&month1={first.month}&day1={first.day}"
        f"&year2={last.year}&month2={last.month}&day2={last.day}"
        "&tz=Etc/UTC&format=onlycomma"
    )


# --- parsing -----------------------------------------------------------------------------


def _empty_obs() -> pd.DataFrame:
    """An empty frame carrying the pinned obs dtypes (not an untyped `DataFrame()`)."""
    return pd.DataFrame(
        {
            "valid_time": pd.Series([], dtype=_TIME_DTYPE),
            "temp_f": pd.Series([], dtype=_TEMP_DTYPE),
        }
    )


def parse_iem_csv(text: str) -> pd.DataFrame:
    """Parse an IEM `onlycomma` response into `["valid_time", "temp_f"]`.

    Rows whose `tmpf` is `M`, `T`, blank or otherwise non-numeric are DROPPED (SPEC §4),
    as are rows with an unparseable `valid`. Exact duplicate timestamps keep the first
    value. The result is sorted ascending with a fresh index.
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lines) < 2:
        return _empty_obs()

    raw = pd.read_csv(io.StringIO("\n".join(lines)), dtype=str)
    for column in ("valid", "tmpf"):
        if column not in raw.columns:
            raise AssertionError(
                f"SPEC §4: the IEM response must carry a {column!r} column; header is "
                f"{list(raw.columns)}. Requesting the wrong `data=` field yields a file that "
                "parses to nothing and scores perfectly."
            )

    frame = pd.DataFrame(
        {
            # errors="coerce" turns 'M', 'T', '' and any other non-numeric tmpf into NaN,
            # and an unparseable timestamp into NaT; both are dropped on the next line.
            # format="ISO8601" pins IEM's `YYYY-MM-DD HH:MM` instead of letting pandas
            # sniff a format per element (which warns, and can guess differently per file).
            "valid_time": pd.to_datetime(
                raw["valid"], utc=True, errors="coerce", format="ISO8601"
            ),
            "temp_f": pd.to_numeric(raw["tmpf"], errors="coerce"),
        }
    )
    frame = frame.dropna(subset=COLUMNS)

    # ---------------------------------------------------------------------------------
    # HERE is where the temptation lives: `.dt.floor("h")`, `.dt.round("h")` or a
    # `.resample("1h")` would make these timestamps line up neatly with model valid times.
    # DO NOT. ASOS reports at :52 (spike F5). T5's join is ±30 min nearest, which needs
    # the real minute; an on-the-hour obs file matches ZERO rows and reports a perfect
    # MAE on an empty join (SPEC §4/§10). Missing rows stay missing — never interpolated.
    # ---------------------------------------------------------------------------------

    frame = frame.drop_duplicates(subset="valid_time", keep="first")
    frame = frame.sort_values("valid_time", kind="stable").reset_index(drop=True)

    if frame.empty:
        return _empty_obs()

    frame["valid_time"] = frame["valid_time"].astype(_TIME_DTYPE)
    frame["temp_f"] = frame["temp_f"].astype(_TEMP_DTYPE)
    return frame[COLUMNS]


# --- coverage ----------------------------------------------------------------------------


def distinct_hours(df: pd.DataFrame) -> int:
    """Number of distinct floored UTC hours covered — **the SPEC §8 acceptance measure**.

    Deliberately NOT a row count. 900 rows sitting inside 3 hours passes any row-count
    threshold and covers nothing. The floor is used to *count* coverage only; it is never
    written back onto `valid_time`.
    """
    if df.empty:
        return 0
    return int(df["valid_time"].dt.floor("h").nunique())


def obs_summary(df: pd.DataFrame) -> dict:
    """`{"rows", "distinct_hours", "start", "end"}` — side-effect free, no I/O.

    `fetch/backfill.py` imports this for `data/coverage.json`'s `obs` block, so the
    timestamps are ISO-8601 `Z` strings (or `None` on an empty frame), never Timestamps.
    """
    return {
        "rows": int(len(df)),
        "distinct_hours": distinct_hours(df),
        "start": _iso_z(df["valid_time"].min()) if len(df) else None,
        "end": _iso_z(df["valid_time"].max()) if len(df) else None,
    }


def _iso_z(moment) -> str:
    """ISO-8601 with a `Z` suffix, not `+00:00` — coverage.json is read by the frontend."""
    return pd.Timestamp(moment).tz_convert("UTC").isoformat().replace("+00:00", "Z")


# --- http --------------------------------------------------------------------------------


def fetch_obs(start: datetime, end: datetime, *, session_get=requests.get) -> pd.DataFrame:
    """GET the IEM slice for `[start, end]` and parse it.

    `session_get` is injected so tests never touch the network (SPEC §13).
    """
    url = build_url(start, end)
    resp = session_get(url, timeout=_TIMEOUT)
    status = getattr(resp, "status_code", None)
    if status != 200:
        raise RuntimeError(
            f"SPEC §9 hard stop: GET {url} returned HTTP {status} (expected 200). IEM is the "
            "ONLY observation source — SPEC §11 R1 (Open-Meteo) is RETIRED and FORBIDDEN, "
            "and there is no fallback source. Report the failure; do not substitute data."
        )
    return parse_iem_csv(resp.text)


# --- write -------------------------------------------------------------------------------


def write_obs(
    df: pd.DataFrame,
    path: str | Path = DEFAULT_OUT,
    *,
    min_rows: int = MIN_ROWS,
    min_distinct_hours: int = MIN_DISTINCT_HOURS,
) -> Path:
    """Write `df` to `path` as `OBS_SCHEMA`, refusing thin coverage FIRST.

    The distinct-hour check runs before the row-count check on purpose: a row count is
    the measure that can be satisfied by a useless file (SPEC §8/§10).
    """
    hours = distinct_hours(df)
    if hours < min_distinct_hours:
        raise AssertionError(
            f"SPEC §8/§10: refusing to write obs to {Path(path)} — it covers {hours} "
            f"distinct hours (minimum {min_distinct_hours}) across {len(df)} rows. This "
            "check is nunique() on the floored hour, NOT a row count: 900 rows inside 3 "
            "hours passes a row count and covers nothing. Report the shortfall in coverage; "
            "do not lower the minimum and do not fill the gaps."
        )
    return write_parquet_checked(df, path, OBS_SCHEMA, min_rows=min_rows, label="obs")


# --- cli ---------------------------------------------------------------------------------


def _default_bounds() -> tuple[datetime, datetime]:
    _, inits = default_window()
    return obs_bounds(inits)


def _minute_summary(df: pd.DataFrame) -> dict:
    """Minute-of-hour distribution — the evidence that nothing resampled to `:00`."""
    if df.empty:
        return {"min_minute": None, "max_minute": None, "on_hour_rows": 0, "distinct_minutes": 0}
    minutes = df["valid_time"].dt.minute
    return {
        "min_minute": int(minutes.min()),
        "max_minute": int(minutes.max()),
        "on_hour_rows": int((minutes == 0).sum()),
        "distinct_minutes": int(minutes.nunique()),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch.obs",
        description="Fetch KOMA (OMA) ASOS observations from IEM and write data/obs.parquet.",
    )
    default_start, default_end = _default_bounds()
    parser.add_argument("--start", default=default_start.isoformat(), help="ISO-8601 UTC start")
    parser.add_argument("--end", default=default_end.isoformat(), help="ISO-8601 UTC end")
    parser.add_argument(
        "--out", default=DEFAULT_OUT, help=f"output parquet (default {DEFAULT_OUT})"
    )
    parser.add_argument(
        "--min-distinct-hours",
        type=int,
        default=MIN_DISTINCT_HOURS,
        help=f"SPEC §8 coverage floor in distinct hours (default {MIN_DISTINCT_HOURS})",
    )
    args = parser.parse_args(argv)

    start = _as_utc(datetime.fromisoformat(args.start))
    end = _as_utc(datetime.fromisoformat(args.end))

    print(f"IEM ASOS {STATION} (OMAHA/EPPLEY)  {start.isoformat()} .. {end.isoformat()}")
    print(f"  {build_url(start, end)}")

    df = fetch_obs(start, end)
    summary = obs_summary(df)
    minutes = _minute_summary(df)

    print(f"  rows            : {summary['rows']}")
    print(f"  distinct_hours  : {summary['distinct_hours']}  (SPEC §8 measure, not rows)")
    print(f"  start           : {summary['start']}")
    print(f"  end             : {summary['end']}")
    print(
        f"  minutes         : min={minutes['min_minute']} max={minutes['max_minute']} "
        f"distinct={minutes['distinct_minutes']} on_the_hour={minutes['on_hour_rows']}"
    )
    if summary["rows"] and minutes["on_hour_rows"] == summary["rows"]:
        print("  WARNING: every observation lands on :00 — something resampled (spike F5).")

    out = write_obs(df, args.out, min_distinct_hours=args.min_distinct_hours)
    print(f"  wrote           : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
