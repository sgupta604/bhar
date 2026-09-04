"""Live IEM ASOS probe + one-pass offline fixture capture (T4, Task 2.1).

Dev-only script. It is **never** collected by pytest (``testpaths = ["tests"]``; this file
lives in ``fetch/``) and it deliberately imports nothing under test — not ``fetch.obs``,
``fetch.grib``, ``fetch.idx``, ``fetch.schema`` nor ``fetch.window``. It is the independent
witness those modules are checked against; if the probe and the implementation shared code,
a shared bug would prove itself correct. That discipline is what caught T2's ``2t`` surprise.

Run:  uv run python -m fetch.capture_iem_fixture

It fetches a short slice of OMA (OMAHA/EPPLEY) ASOS ``tmpf`` observations from the Iowa
Environmental Mesonet CGI service (spike F4, HTTP 200), writes the response text verbatim to
``tests/fixtures/iem/oma_sample.csv``, and refuses to finish unless the slice pins the two
behaviours the fixture exists for:

  * at least one row whose ``tmpf`` is exactly ``M`` — the observation loader must DROP these,
    never interpolate them (SPEC 4);
  * at least one row whose ``valid`` minute is not ``00`` — a true off-hour timestamp. Spike F5:
    ASOS reports at :52-ish, so an on-the-hour join matches ZERO rows and scores perfectly.

If the live slice does not contain those rows, this script FAILS and reports what the data
actually said. The checks are never relaxed to make a capture pass (SPEC 10).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import requests

# --- constants -------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
IEM_DIR = FIXTURES / "iem"
OUT_PATH = IEM_DIR / "oma_sample.csv"

STATION = "OMA"  # OMAHA/EPPLEY
BASE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

# 3-day slice ending today (today is 2026-09-04).
START = (2026, 9, 1)
END = (2026, 9, 4)

MISSING = "M"  # IEM's missing-value sentinel; rows carrying it must be dropped, not filled.

TIMEOUT = 120


# --- url building ----------------------------------------------------------------------


def build_url(
    station: str = STATION,
    start: tuple[int, int, int] = START,
    end: tuple[int, int, int] = END,
) -> str:
    """Return the full IEM ASOS request URL for one station over [start, end]."""
    y1, m1, d1 = start
    y2, m2, d2 = end
    return (
        f"{BASE_URL}?station={station}&data=tmpf"
        f"&year1={y1}&month1={m1}&day1={d1}"
        f"&year2={y2}&month2={m2}&day2={d2}"
        "&tz=Etc/UTC&format=onlycomma"
    )


# --- http ------------------------------------------------------------------------------


def fetch_csv(url: str) -> tuple[int, str]:
    """GET the slice. Returns (status_code, text). No retries: a hard stop is a finding."""
    resp = requests.get(url, timeout=TIMEOUT)
    return resp.status_code, resp.text


# --- csv inspection (self-contained; NOT imported from fetch.obs) ------------------------


def split_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """Split the raw response into (header fields, data rows). Comment lines are kept out.

    IEM's ``onlycomma`` output is plain comma-separated with no quoting for these columns,
    so a naive split is honest here. Anything more clever would start reimplementing the
    module under test.
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        raise ValueError("IEM returned no non-comment lines")
    header = [f.strip() for f in lines[0].split(",")]
    rows = [[f.strip() for f in ln.split(",")] for ln in lines[1:]]
    return header, rows


def column(header: list[str], name: str) -> int:
    if name not in header:
        raise ValueError(f"expected a {name!r} column; header is {header}")
    return header.index(name)


def minute_of(valid: str) -> str:
    """Return the minute field of an IEM ``valid`` timestamp (``YYYY-MM-DD HH:MM``)."""
    time_part = valid.split(" ")[-1]
    parts = time_part.split(":")
    if len(parts) < 2:
        raise ValueError(f"unparseable valid timestamp: {valid!r}")
    return parts[1]


def floored_hour(valid: str) -> str:
    """Return ``YYYY-MM-DD HH`` — the timestamp floored to the hour, no rounding."""
    date_part, _, time_part = valid.partition(" ")
    return f"{date_part} {time_part.split(':')[0]}"


# --- trackability gate ------------------------------------------------------------------


def assert_trackable(paths: list[Path]) -> bool:
    """Fail loudly if any written fixture is gitignored (T2's structural guard)."""
    ignored = []
    for p in paths:
        rel = p.relative_to(REPO_ROOT)
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if result.returncode == 0:
            ignored.append(str(rel))
    if ignored:
        print("CHECK 4 git check-ignore gate: FAIL - these files are GITIGNORED and would")
        print("        vanish on a clean clone:")
        for name in ignored:
            print(f"          - {name}")
        return False
    print(f"CHECK 4 git check-ignore gate: PASS - all {len(paths)} written file(s) trackable.")
    return True


# --- main ------------------------------------------------------------------------------


def main() -> int:
    IEM_DIR.mkdir(parents=True, exist_ok=True)

    url = build_url()

    print("=" * 88)
    print(f"LIVE IEM ASOS PROBE + FIXTURE CAPTURE - station {STATION} (OMAHA/EPPLEY)")
    print(f"  {START[0]}-{START[1]:02d}-{START[2]:02d} .. {END[0]}-{END[1]:02d}-{END[2]:02d} UTC")
    print(f"  {url}")
    print("=" * 88)

    status, text = fetch_csv(url)

    # --- check 1: HTTP 200 ---------------------------------------------------------------
    if status != 200:
        print(f"CHECK 1 HTTP status: FAIL - got HTTP {status} (expected 200)")
        print(f"        first 500 chars of body:\n{text[:500]!r}")
        return 1
    print("CHECK 1 HTTP status: PASS - HTTP 200")

    OUT_PATH.write_text(text, encoding="utf-8", newline="")
    written = [OUT_PATH]

    header, rows = split_rows(text)
    print(f"        header line: {','.join(header)}")

    tmpf_i = column(header, "tmpf")
    valid_i = column(header, "valid")

    total = len(rows)
    missing_rows = [r for r in rows if r[tmpf_i] == MISSING]
    non_missing = [r for r in rows if r[tmpf_i] != MISSING]
    off_hour = [r for r in rows if minute_of(r[valid_i]) != "00"]
    hours = sorted({floored_hour(r[valid_i]) for r in rows})

    # --- check 2: at least one literal 'M' tmpf ------------------------------------------
    if not missing_rows:
        print(f"CHECK 2 missing ('{MISSING}') tmpf row present: FAIL - 0 of {total} rows")
        print("        The slice pins nothing about M-dropping. This is a finding to REPORT")
        print("        (SPEC 10), not a check to relax. Sample rows:")
        for r in rows[:5]:
            print(f"          {','.join(r)}")
        return 1
    print(
        f"CHECK 2 missing ('{MISSING}') tmpf row present: PASS - "
        f"{len(missing_rows)} of {total} rows; example: {','.join(missing_rows[0])}"
    )

    # --- check 3: at least one off-hour timestamp ----------------------------------------
    if not off_hour:
        print(f"CHECK 3 off-hour timestamp present: FAIL - all {total} rows land on :00")
        print("        Spike F5 says ASOS reports off the hour; an all-:00 slice cannot pin")
        print("        the join bug. REPORT this (SPEC 10). Sample rows:")
        for r in rows[:5]:
            print(f"          {','.join(r)}")
        return 1
    print(
        f"CHECK 3 off-hour timestamp present: PASS - {len(off_hour)} of {total} rows; "
        f"example: {off_hour[0][valid_i]}"
    )

    # --- check 4: nothing written is gitignored ------------------------------------------
    if not assert_trackable(written):
        return 1

    size = OUT_PATH.stat().st_size
    print()
    print("=" * 88)
    print("SUMMARY")
    print("=" * 88)
    print(f"  file                  : {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"  header                : {','.join(header)}")
    print(f"  total rows            : {total}")
    print(f"  non-'{MISSING}' rows          : {len(non_missing)}")
    print(f"  '{MISSING}' rows              : {len(missing_rows)}")
    print(f"  distinct floored hours: {len(hours)}")
    print(f"  off-hour rows         : {len(off_hour)}")
    print(f"  first timestamp       : {rows[0][valid_i]}")
    print(f"  last timestamp        : {rows[-1][valid_i]}")
    print(f"  byte size             : {size:,d} B")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
