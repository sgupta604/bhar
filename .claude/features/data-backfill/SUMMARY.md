# Summary: data-backfill

**Completed:** 2026-09-04 | **Branch:** feat/site-tuned-blend | **PR:** none — no git remote configured (see below)

## What Was Built
The T4 orchestrator that produces T5's two clean inputs: `data/forecasts.parquet` (1440 NOAA point
forecasts = 30 days × 4 inits × 3 leads × 4 models, via T2's unmodified `fetch_point()` under an
8-worker thread pool) and `data/obs.parquet` (IEM ASOS OMA, true off-hour timestamps, `M` dropped,
never interpolated/resampled), plus a per-model coverage report against the SPEC §5 90% floor. An
append-only JSONL ledger is the single source of truth; both parquets and `coverage.json` are pure
functions of it, which gives resumability and offline-testable writers with zero networked tests.
T4 flags below-floor coverage but never excludes a model — that decision belongs to T5.

## Files Changed
| Package | File | Change |
|---------|------|--------|
| fetch | `fetch/grib.py` | Additive only — `class ArchiveMissing(RuntimeError)`, raised on HTTP 404/403 for the `.idx` GET and the ranged GRIB GET, citing SPEC §11 R2. Every other non-200 still raises the original `RuntimeError` citing §9. `decode_point`, `select_tmp_2m`, `_get`, `build_urls`, `valid_time`, byte-range logic byte-identical (confirmed by diff). |
| fetch | `fetch/schema.py` | NEW — `FORECAST_SCHEMA`/`OBS_SCHEMA` (`timestamp[us, tz=UTC]` on both time columns, `model` as plain `pa.string()`, never dictionary) and `write_parquet_checked()`, the single place the SPEC §10 non-trivial-row assert lives. |
| fetch | `fetch/window.py` | NEW — D5 window: pure function of `now_utc`, 120 synoptic inits, 1440 work items, obs bounds. |
| fetch | `fetch/obs.py` | NEW — IEM fetch, `M`-drop, dedupe, sort, `distinct_hours` (nunique on floored hour, not row count), CLI. |
| fetch | `fetch/backfill.py` | NEW — ledger, D3 classification (`success`/`missing`/`failed_network`/`failed_decode`/`not_attempted`), thread pool + retry + 900 s deadline guard, coverage, parquet/JSON writers, CLI. |
| fetch | `fetch/capture_iem_fixture.py` | NEW — dev-only live IEM capture; imports nothing under test, not collected by pytest. |
| tests | `tests/test_grib.py`, `tests/test_schema.py`, `tests/test_window.py`, `tests/test_obs.py`, `tests/test_backfill.py` | NEW/extended — 220 tests total, all offline, no socket opened. |
| tests | `tests/fixtures/iem/oma_sample.csv`, `tests/fixtures/README.md` | NEW/APPEND — captured 3-day IEM slice + provenance. |
| data | `data/coverage.json` | NEW, **committed** — stored coverage report. |
| data | `data/obs.parquet`, `data/forecasts.parquet`, `data/raw/backfill_ledger.jsonl` | NEW, **gitignored** — a fresh clone must re-run `uv run python -m fetch.backfill`. |

## Tests
- Full suite: 220 passing, 0 failures (`uv run pytest -q`)
- Non-integration: 200 passing, 20 deselected (`-m "not integration"`)
- T2 regression: 63 (`test_grib.py`) + 24 (`test_idx.py`) all still green
- Lint: `ruff check .` clean
- Types: n/a (deliberate, SPEC §13) | Build: n/a (Python from source)
- Live run: 1440/1440 forecasts, 115 s wall clock (deadline guard 900 s, not hit)

## Key Decisions

### The 100% coverage result — validated, not accepted
1440/1440 with zero `missing` is exactly the shape of a fake, and SPEC §11 R2 had explicitly
predicted HRRR archive holes in a 30-day window. It was believed only after three independent
checks, re-run by the test-agent itself rather than taken from the implementer's report:
1. **T2 acceptance anchor reproduced digit-for-digit** — 2026-08-05 12z f006 read directly out of
   `data/forecasts.parquet`: HRRR 68.239766 / GFS 71.654152 / NAM 69.525166 / NBM 70.610011, each
   matching the recorded full-precision values to <0.01.
2. **The `missing` detector was fired live at genuinely nonexistent keys**, independently, by the
   test-agent: `fetch_point("hrrr", 2014-01-01, 6)` and `fetch_point("hrrr", 2026-08-20 12z, 99)`
   each returned a real HTTP 404 against the live NOAA bucket, raised `ArchiveMissing`, and did not
   abort. "Zero missing" therefore means *no holes occurred in this window*, not *the detector is
   blind*.
3. **The data is non-degenerate** — 1209 distinct `temp_f` values across 1440 rows, zero NaNs, zero
   duplicate `(model,init,lead)` keys, `valid_time == init_time + lead_h` on every row, and a real
   diurnal cycle by valid UTC hour (12Z 68.3°F coolest, 00Z 84.7°F warmest).

**The below-90% exclusion path exists, is unit-tested (including the exact 90.0-passes /
89.99-flags boundary), but was not exercised live** — no model fell below the floor on this run.
That is an expected outcome (SPEC §11 R2 not biting this particular window), not a code gap.
**T6 must state the real coverage numbers (all four models 100.00%) in the README rather than
imply the exclusion path was exercised.**

### Obs shape T5 depends on
932 rows over 744 distinct floored hours (`nunique()` on the floor, not a row count — the
acceptance floor is `>= 700`). Only 5 of 932 rows land on minute `:00`; the rest are true
off-hour METAR/SPECI timestamps, never resampled, never interpolated. T5's ±30 min nearest join
needs these exact timestamps to match anything.

### Schema contract T5's `merge_asof` depends on
Both parquet files use `timestamp[us, tz=UTC]` on every time column, and `model` is plain
`pa.string()` — **never** `pandas.Categorical` / pyarrow dictionary, which would silently break a
`merge_asof` join key comparison. Verified on round-trip by both the implementer and the test-agent
independently.

### `ArchiveMissing` is additive
`class ArchiveMissing(RuntimeError)` was added to `fetch/grib.py`, raised only on 404/403 for the
`.idx` GET and the ranged GRIB GET. Every other T2 code path — `decode_point`, `_get`,
`build_urls`, `valid_time`, the byte-range arithmetic — is byte-identical to the finalized T2
commit; confirmed by diff, not just by the passing 81 T2 tests staying green.

### The two guards that keep a fast run from being a fake one
- The 900 s deadline guard (`fetch/backfill.py`) makes SPEC §8's "under 15 minutes" an enforced
  property rather than a hope. It did not fire (115 s actual), but is proven by test with an
  injected fake fetcher and a tiny deadline.
- `write_parquet_checked`'s non-trivial-row assert (`fetch/schema.py:57-83`) is the only thing
  standing between a beautifully-typed parquet and an empty one that would pass a schema check
  perfectly (SPEC §10's empty-join analogue).

### Data layout
`data/coverage.json` is committed (it is a small result document, not a large artifact); both
parquet files and `data/raw/` are gitignored. **A fresh clone has no forecast/obs data until
`uv run python -m fetch.backfill` (and `fetch.obs`) is re-run** — only the coverage report and the
window bounds survive in git.

## Deferred Items
- The `--executor process` escape hatch (for cfgrib misbehaving under threads) was built and
  offline-tested but never needed live — 8 threads reproduced bit-identical values under
  concurrent load in the smoke probe. Left in place as a flag, not exercised in the full run.
- Below-90% coverage flagging is unit-tested only, not exercised against a live below-floor model.
  Deferred to whichever future window actually produces one — SPEC §11 R2's expectation is not
  wrong in general, it simply didn't bite in this 30-day slice.

## Retrospective
### Worked Well
- **Treating "too clean" as a hypothesis to disprove, not a result to accept.** The three-check
  validation (anchor reproduction, live re-fire of the missing detector against real 404s,
  non-degeneracy of the diurnal signal) is exactly the kind of check SPEC §10 exists to force, and
  it was performed independently by both the implementer and the test-agent, which is what made the
  100% number trustworthy rather than merely reported.
- **The ledger-as-pure-function design.** Deriving both parquets and the coverage report from one
  append-only JSONL made the entire write path testable offline with zero live-network tests, while
  still being resumable against a real crash mid-run.
- **Path-scoped commits held under real concurrency.** T3 was mid-implementation on `backend/`,
  `frontend/`, and `data/results.json` at the same wall-clock time T4 committed; the enumerated
  path list in `git add` kept the two tickets from ever touching each other's files.

### Went Wrong
- Nothing failed in this run. The one near-miss worth recording: `fetch/grib.py:_get` wraps
  `requests.RequestException` in a plain `RuntimeError`, so a naive `except requests.RequestException`
  in the classifier would have silently never fired, misclassifying every network failure as a
  decode failure. The fix (classify off `exc.__cause__`) is now documented at
  `fetch/backfill.py` and should be treated as a standing gotcha for any future consumer of `_get`.

### Process
- Pipeline flow: smooth — research correctly front-loaded the one genuine blocker (the 404-as-
  hard-stop conflation) as Task 1.1, so nothing downstream was blocked on the SPEC ambiguity.
- Task granularity: right — the Foundation/Observations/Engine/Smoke/Live-run/Verify streams let
  Streams 2 and 3 run concurrently on disjoint files against contracts locked in Stream 1.
- Estimate accuracy: plan projected ~30–35 min build + ~5–8 min live run; actual live run was 115 s
  against a ~2 min projection from the smoke probe — the projection held, with 13% of the 900 s
  deadline guard used.
- Agent delegation: execute-agent handled all streams directly per the plan's note that no
  specialist agents exist beyond the pipeline agents; Streams 2 and 3 sub-delegated to
  general-purpose agents on disjoint files without a write-write conflict.
