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

---

# Captured fixtures — provenance (T2, `grib-point-fetch`)

Captured **2026-09-04** by `fetch/capture_fixtures.py` (`uv run python -m fetch.capture_fixtures`),
a self-contained live probe that imports neither `fetch.idx` nor `fetch.grib` — it is the
independent witness those modules are checked against. Every file below was written by that run and
passed its `git check-ignore` trackability gate.

All ten files come from the same model cycle: **run date 2026-08-05, init hour 12z**. Host pattern
is `https://{bucket}.s3.amazonaws.com/{key}`; the `.idx` URL is the GRIB key plus `.idx`. The buckets
are public — no credentials.

## `tests/fixtures/idx/` — index text, saved verbatim

The whole `.idx` file is saved (no range request), so the parser is exercised against every line —
including NAM's sub-message entries `284.1` / `284.2`, which share a start byte and make `int()` on
a message number raise. **Expected value** here is the message the anchored needle
`":TMP:2 m above ground:"` must select (with `ens std dev` rejected).

| File | Date | Model | Init | Lead | Source URL | Byte range | Expected value |
|---|---|---|---|---|---|---|---|
| `hrrr_20260805_12z_f006.idx` | 2026-08-05 | HRRR | 12z | f006 | `https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20260805/conus/hrrr.t12z.wrfsfcf06.grib2.idx` | whole file (no range), 10,355 B | selects msg **`71`** |
| `gfs_20260805_12z_f006.idx` | 2026-08-05 | GFS | 12z | f006 | `https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20260805/12/atmos/gfs.t12z.pgrb2.0p25.f006.idx` | whole file (no range), 40,478 B | selects msg **`581`** |
| `nam_20260805_12z_f006.idx` | 2026-08-05 | NAM | 12z | f006 | `https://noaa-nam-pds.s3.amazonaws.com/nam.20260805/nam.t12z.awphys06.tm00.grib2.idx` | whole file (no range), 24,288 B | selects msg **`321`** |
| `nbm_20260805_12z_f006.idx` | 2026-08-05 | NBM | 12z | f006 | `https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.20260805/12/core/blend.t12z.core.f006.co.grib2.idx` | whole file (no range), 16,197 B | selects msg **`187`** |
| `nbm_20260805_12z_f012.idx` | 2026-08-05 | NBM | 12z | f012 | `https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.20260805/12/core/blend.t12z.core.f012.co.grib2.idx` | whole file (no range), 16,816 B | selects msg **`192`** |
| `nbm_20260805_12z_f024.idx` | 2026-08-05 | NBM | 12z | f024 | `https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.20260805/12/core/blend.t12z.core.f024.co.grib2.idx` | whole file (no range), 17,184 B | selects msg **`195`** |

The three NBM entries exist to pin **187 / 192 / 195** — the index moves with lead time (spike F10).
Those numbers are *recorded provenance*, read from the `.idx` at test time. They are **never**
constants in `fetch/`.

## `tests/fixtures/grib/` — the exact range-request bytes

One GRIB message each: the anchored `:TMP:2 m above ground:` record, saved byte-for-byte as the
HTTP `Range` request returned it (HTTP 206, body starts with the `GRIB` magic). **Expected value**
is the decoded nearest-cell temperature at KOMA (41.3032, -95.8941), valid **2026-08-05 18:00Z**,
asserted at `abs(diff) < 0.01`.

| File | Date | Model | Init | Lead | Source URL | Byte range | Expected value |
|---|---|---|---|---|---|---|---|
| `hrrr_20260805_12z_f006_t2m.bin` | 2026-08-05 | HRRR | 12z | f006 | `https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20260805/conus/hrrr.t12z.wrfsfcf06.grib2` | `bytes=43193578-44475973` (1,282,396 B) | **68.24 F** |
| `gfs_20260805_12z_f006_t2m.bin` | 2026-08-05 | GFS | 12z | f006 | `https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20260805/12/atmos/gfs.t12z.pgrb2.0p25.f006` | `bytes=428319247-428842068` (522,822 B) | **71.65 F** |
| `nam_20260805_12z_f006_t2m.bin` | 2026-08-05 | NAM | 12z | f006 | `https://noaa-nam-pds.s3.amazonaws.com/nam.20260805/nam.t12z.awphys06.tm00.grib2` | `bytes=48465225-48706128` (240,904 B) | **69.53 F** |
| `nbm_20260805_12z_f006_t2m.bin` | 2026-08-05 | NBM | 12z | f006 | `https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.20260805/12/core/blend.t12z.core.f006.co.grib2` | `bytes=153756600-155939230` (2,182,631 B) | **70.61 F** |

Byte ranges were computed from the `.idx` alone: start is the selected record's offset, end is the
**next entry with a strictly greater start offset, minus one**. (Literally "the next line" would
yield a zero-length range on NAM's `.1`/`.2` sub-message pairs.)

### Nearest cell selected, and the observed full-precision values

Nearest cell by plain euclidean degrees after normalizing longitude with `((lon + 180) % 360) - 180`
— GFS is 0–360. **No interpolation.** These reproduce spike F11 exactly.

| Model | Nearest cell (lat, lon) | Distance | Observed `temp_f` | Expected | Diff |
|---|---|---|---|---|---|
| HRRR | (41.2914, -95.8923) | 0.012 deg | 68.23976562500005 | 68.24 | -0.00023 |
| GFS | (41.2500, -96.0000) | 0.119 deg | 71.65415161132816 | 71.65 | +0.00415 |
| NAM | (41.2864, -95.9305) | 0.040 deg | 69.52516601562505 | 69.53 | -0.00483 |
| NBM | (41.3034, -95.9029) | 0.009 deg | 70.61001098632816 | 70.61 | +0.00001 |

## Naming and decode notes

- **`.bin`, not `.grib2`** — `.gitignore:24` is `*.grib2` and would silently untrack these. The
  capture script runs `git check-ignore -q` on every file it writes and exits non-zero if any is
  ignored, so the naming rule cannot rot. **Do not rename these to `.grib2`.**
- Decode with `xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})`. The empty
  `indexpath` is mandatory — without it cfgrib drops a sidecar index into this directory, which then
  goes stale and gets committed.
- cfgrib exposes the message as the data variable **`t2m`**; eccodes' own `GRIB_shortName` attribute
  for it is **`2t`** and `GRIB_cfVarName` is `t2m`. Assert on the variable name `t2m` and on the
  absence of `aptmp` — asserting `GRIB_shortName == "t2m"` fails on valid data.
- `F = (K - 273.15) * 9/5 + 32`. Kelvin never leaves the decoder.

---

# Captured fixture — provenance (T4, `data-backfill`)

Captured **2026-09-04** by `fetch/capture_iem_fixture.py`
(`uv run python -m fetch.capture_iem_fixture`), a self-contained live probe that imports nothing
under test — not `fetch.obs`, `fetch.grib`, `fetch.idx`, `fetch.schema` nor `fetch.window`. It is
the independent witness the observation loader is checked against; that same discipline is what
surfaced T2's `2t` surprise. The file below was written by that run and passed the same
`git check-ignore` trackability gate T2 uses.

## `tests/fixtures/iem/` — Iowa Environmental Mesonet ASOS observations, saved verbatim

The whole response body is saved (no filtering, no resampling, no reformatting), so the loader is
exercised against exactly the bytes IEM served. Header line is `station,valid,tmpf`.

| Field | Value |
|---|---|
| **Date range captured** | 2026-09-01 00:00 UTC .. 2026-09-03 23:55 UTC (3 days; request `day1=1`..`day2=4`) |
| **Station** | `OMA` — OMAHA/EPPLEY |
| **Source URL** | `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=OMA&data=tmpf&year1=2026&month1=9&day1=1&year2=2026&month2=9&day2=4&tz=Etc/UTC&format=onlycomma` |
| **Parameters** | `data=tmpf&tz=Etc/UTC&format=onlycomma` |
| **Row counts** | **912** total / **75** non-`M` / **72** distinct floored hours (all 912 rows also span 72 floored hours) |
| **Captured** | 2026-09-04 by `fetch/capture_iem_fixture.py` |
| **Expected value** | the loader drops every `M` row, preserves off-hour minutes exactly as served, and does **no** resampling — 912 rows in, **75** rows out, timestamps unchanged |

`oma_sample.csv`, 21,295 B, 913 lines (1 header + 912 data rows), trailing newline present.

## Why this fixture exists — it pins exactly two behaviours

**1. `M`-row dropping.** IEM writes the literal string `M` for a missing `tmpf`. **837 of the 912
rows are `M`** (the service emits a 5-minute grid; OMA only reports a temperature hourly), e.g.:

```
OMA,2026-09-01 00:00,M
```

Those rows must be **dropped**, never interpolated, never forward-filled (SPEC §4 — "never
interpolate observations, drop missing"). A loader that coerces `M` to `NaN` and then fills it
would turn 75 real observations into 912 fake ones.

**2. True off-hour timestamps (spike F5).** ASOS routine observations land at **:52**, not on the
hour. Of the 75 non-`M` rows: **72 at minute `:52`**, plus three SPECIs at `:46`, `:19` and `:07`.

```
OMA,2026-09-01 00:52,83.00
OMA,2026-09-01 01:52,81.00
```

**Zero non-`M` rows fall on minute `:00`** — verified against this exact slice. So a join that
assumes on-the-hour observation timestamps matches **ZERO rows**, and an empty join **scores
perfectly** (MAE 0.0, RMSE 0.0). That is the failure spike F5 found, and it is silent: nothing
errors, the numbers just come out flawless. Hence CLAUDE.md's rule — **assert on join match
counts**. This fixture is the regression test for it: floor the observation timestamp to the hour
to join (72 hours here), but never rewrite the timestamps themselves.

The capture script hard-verifies both properties before it will write a summary — HTTP 200, at
least one literal `M` row, at least one non-`:00` minute, and nothing gitignored — and exits
non-zero otherwise. Those checks are **never** relaxed to make a capture pass (SPEC §10): if a
future slice lacks `M` rows or lacks off-hour timestamps, that is a finding to report, not a
threshold to move.
