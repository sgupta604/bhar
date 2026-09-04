# Summary: grib-point-fetch

**Completed:** 2026-09-04 | **Branch:** feat/site-tuned-blend | **PR:** none — no git remote configured (see below)

## What Was Built
The single-fetch primitive for the site-tuned blend: given `(model, init_time, lead_h)`, parse a
NOAA `.idx`, HTTP range-fetch the anchored 2 m TMP GRIB message, decode it with cfgrib, take the
nearest grid cell to KOMA (no interpolation), and return degrees F. Covers HRRR/GFS/NAM/NBM. A
self-contained capture script performed the one live probe and produced the offline fixture corpus;
all 81 tests (including 20 integration tests against captured `.bin`/`.idx` fixtures) run without
opening a socket.

## Files Changed
| Package | File | Change |
|---------|------|--------|
| fetch | `fetch/idx.py` | NEW — `.idx` parse, anchored `:TMP:2 m above ground:` selection, byte-range arithmetic (string message numbers, strictly-greater-offset rule) |
| fetch | `fetch/grib.py` | NEW — S3 key building, ranged GET, cfgrib decode, nearest-cell pick, K→F, `fetch_point()` |
| fetch | `fetch/capture_fixtures.py` | NEW — independent live-probe + fixture capture (imports neither module above) |
| tests | `tests/test_idx.py`, `tests/test_grib.py` | NEW — 24 + 53 tests, offline, socket-blocked |
| tests | `tests/fixtures/idx/*.idx`, `tests/fixtures/grib/*.bin` | NEW — 6 `.idx` + 4 `.bin` captured fixtures, `.bin` named to avoid `.gitignore:24`'s `*.grib2` |
| tests | `tests/fixtures/README.md` | APPEND — provenance, 7 fields per capture |

## Tests
- Full suite: 81 passing (61 default + 20 integration), 0 failures
- `-m "not integration"`: 61 passing
- Lint: `ruff check .` clean
- Types: n/a (deliberate, no type checker installed)
- Build: n/a (Python from source)
- Acceptance floor (SPEC §8, 2026-08-05 12z f006, valid 18:00Z): HRRR 68.24 / GFS 71.65 / NAM 69.53
  / NBM 70.61, each `abs(diff) < 0.01`, none exact to full float precision — verified by capture
  script, offline fixture tests, and a manual live `fetch_point()` run, all three agreeing bit-for-bit.

## Key Decisions
- **`GRIB_shortName` for 2 m temperature is `2t`, not `t2m`.** Both SPEC §3 and the spike say to
  assert the short name is `t2m`; taken literally that fails on valid data — cfgrib exposes the
  data variable / `GRIB_cfVarName` as `t2m` but the eccodes `GRIB_shortName` attribute as `"2t"`.
  The implemented guard asserts the **data-variable name** is `t2m`, requires `GRIB_cfVarName ==
  "t2m"` when present, and explicitly rejects `aptmp` — still catches the real APTMP bug class,
  just not via the attribute SPEC named. SPEC §3 and the spike are both wrong on this literal
  point and should be corrected before T4/T5 read them at face value.
- **The APTMP trap is not NBM-specific.** GFS f006 also carries an `APTMP:2 m above ground` line
  (msg 585) alongside NBM's msg 1. The spike recorded the trap as narrower than it is; the anchored
  needle (`:TMP:2 m above ground:`, leading colon) already handles both, and a dedicated GFS test
  now covers it.
- **NAM `.idx` has sub-message entries** (`284.1`/`284.2` sharing a start byte). Message numbers
  are kept as strings (never `int()`, never `enumerate()`-derived); the byte-range end is the next
  entry with a strictly greater start offset, with an open-ended `bytes=S-` for the last message.
  Doesn't affect today's NAM 321 message but matters once T4 runs 1440 fetches.
- **NBM probability lines carry up to 9 colon-separated fields** (not the assumed 7), so the parser
  uses `split(":", 6)` and keeps the remainder as `extra`.
- **Fixtures are `.bin`, not `.grib2`**, because `.gitignore:24` (`*.grib2`) would silently untrack
  the latter — the capture script hard-fails via `git check-ignore -q` on every written file as a
  structural guard, not just a naming convention.
- **`fetch_point(model, init_time, lead_h) -> dict`** is pure per-call — no module-level session, no
  cache, at most one retry — and is locked as T4's interface to thread-pool unmodified.

## Deferred Items
- 30-day parallel backfill, `forecasts.parquet` writing, observations join, blend search — all T4/T5, explicitly out of scope here.
- No fallback network path (SPEC §11 R1/Open-Meteo is retired and forbidden; a NOAA outage is a hard stop, not implemented as a code path).

## Retrospective
### Worked Well
- **Capture-once-test-offline (D1/D2 in the plan)** turned the highest-risk ticket into something
  fully reproducible on a dead network: the live probe ran exactly once, and every subsequent test
  run (including this finalize pass) is offline and deterministic.
- **Independent-witness discipline** — `capture_fixtures.py` importing neither `fetch/idx.py` nor
  `fetch/grib.py` — caught the `GRIB_shortName` surprise immediately, because the probe's own decode
  hit the same eccodes attribute mismatch as the implementation would have, rather than the two
  disagreeing silently or a shared bug hiding itself.
- **Contract-first parallel streams**: Stream 3 (`fetch/grib.py`) coded against Stream 2's
  (`fetch/idx.py`) locked signatures in the plan doc rather than waiting on it, and the two streams
  never conflicted on files.

### Went Wrong
- **Two of our own source documents (SPEC §3 and the spike) asserted a literal fact — `t2m` is the
  GRIB short name — that fails on valid data.** The lesson isn't "the spike was sloppy," it's that a
  single-model verification doesn't generalize across cfgrib/eccodes attribute names, and a literal
  assertion from a requirements doc should still be checked against real decoded output before being
  coded as a guard, even when the doc calls it "verified."
- **The spike under-scoped the APTMP trap to NBM** when GFS carries the identical trap line. Lesson:
  when a spike says "trap is specific to model X," treat that as "confirmed present in X," not
  "confirmed absent elsewhere," unless the other models were actually checked.

### Process
- Pipeline flow: smooth — research → plan → implement → test all completed without a stop-and-report
  trigger firing, despite this being the ticket flagged HIGHEST RISK.
- Task granularity: right — the idx/grib split let the highest-risk logic (`.idx` parsing) be
  unit-tested in complete isolation from the network/decode layer.
- Estimate accuracy: plan estimated 45–60 min for an M-scope ticket; consistent with four parallel
  streams landing 81 tests and 3,642 inserted lines (mostly fixtures) without a blocked task.
- Agent delegation: all four streams (probe+capture, idx, grib, verify+commit) reported PASS on
  first attempt; no retries, no rework.

## Finalize Notes
- No git remote is configured on this repo — commit only, no push, no PR. This finalize pass
  committed `.claude/features/grib-point-fetch/SUMMARY.md` and the `RETROSPECTIVES.md` line only,
  path-scoped, alongside the already-committed `93a4817`.
- Security/quality sweep on `93a4817`'s diff: no secrets, no hardcoded credentials, no debug
  statements outside the intentional `capture_fixtures.py` CLI output, no TODO/FIXME/HACK comments,
  no commented-out code, no hardcoded absolute paths, no test-only code in `fetch/`. Fixture binaries
  are intentional captured data, not generated artifacts.
- T3 (`demo-shell`) is concurrently in-flight in this working tree (`run.sh`, `backend/main.py`,
  `frontend/`, `scripts/`, `data/results.json`, `.claude/features/demo-shell/`,
  `.claude/active-work/demo-shell/` all modified/untracked). None of it was staged, evaluated, or
  touched by this finalize pass.
