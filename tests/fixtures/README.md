# Test fixtures — provenance

Everything in this directory is **captured or synthetic data committed to the repo**. Tests read it
from disk. Nothing here is fetched at test time.

## What belongs here

- **Captured `.idx` text** (T2) — the raw index files downloaded from NOAA, saved verbatim.
- **Captured GRIB2 bytes** (T2) — the byte ranges pulled for the `TMP:2 m above ground` message,
  saved exactly as the HTTP range request returned them.
- **Synthetic dataframes / frames** (T5) — small hand-built inputs for the join, blend math,
  MAE/RMSE/bias arithmetic, and unit conversion. Synthetic, not sampled from production.

## The rule: no live-network tests (SPEC §13)

There are **NO live-network tests** in this suite. A test that hits NOAA and fails at 04:00 halts a
ticket over NOAA having a bad minute, not over our code. If a test needs bytes from NOAA, those
bytes get captured once, land in this directory with provenance recorded below, and the test reads
them from disk forever after.

## Provenance fields T2 MUST record for every captured fixture

Every captured file gets an entry in this README listing all of:

1. **date** — the model run date (UTC)
2. **model** — HRRR / GFS / NAM / NBM
3. **init hour** — e.g. `12z`
4. **lead** — e.g. `f006`
5. **source URL** — the full NOAA URL the bytes came from
6. **byte range** — the exact `start-end` range requested
7. **expected value** — what the decoded fixture must produce

A capture with no provenance entry is not a fixture, it is an unexplained blob. Record all seven.

## T2's known-good assertion

T2's acceptance floor — **68.24 / 71.65 / 69.53 / 70.61 degrees F** (HRRR / GFS / NAM / NBM,
2026-08-05 12z f006 valid 18:00Z, nearest cell to KOMA) — **must run off captured bytes on disk**,
never off a live fetch, and must be marked `@pytest.mark.integration`.

Run only those: `uv run pytest -m integration`. Skip them: `uv run pytest -m "not integration"`.

## Markers are strict

`--strict-markers` is on (see `pyproject.toml`). A mistyped marker is a hard **error**, not a
silent skip — so a fixture-backed test can never quietly stop running because someone wrote
`@pytest.mark.integraton`.
