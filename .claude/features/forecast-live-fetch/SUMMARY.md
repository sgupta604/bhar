# Summary: forecast-live-fetch (F2)

**Completed:** 2026-09-04 | **Branch:** `feat/forecast-page` (shared across all nine FORECAST-SPEC tickets — F2 is one commit on it, not its own branch) | **PR:** none yet — FORECAST-SPEC §12 opens a single PR at the end of F9; this ticket is commit + push only.

## What Was Built

`forecast/cycle.py` and `forecast/live.py`: cycle-selection with a fallback ladder (max 3
candidate cycles), a disk cache under `data/live/` keyed by init/model/lead, horizon and gap
derivation over a 3-hourly grid, and a live-fetch harness that calls the existing, unmodified
`fetch.grib.fetch_point` against HRRR, GFS, NAM and NBM. `missing` records are cached exactly
like `success` records, so a dead lead is never re-requested. A second run against a populated
cache makes zero network calls (proven both by an injected fetcher that raises on any call, and
by a live second run).

## Files Changed

| Package | File | Change |
|---------|------|--------|
| forecast | `forecast/__init__.py` | new |
| forecast | `forecast/cycle.py` | new — cycle target/candidate/staleness logic |
| forecast | `forecast/live.py` | new — grid/horizon/gap derivation, disk cache, fetch ladder, FR11 manual-run CLI harness |
| tests | `tests/test_cycle.py` | new — 26 functions / 88 instances |
| tests | `tests/test_live.py` | new — 79 functions / 89 instances |
| tests | `tests/test_live_guards.py` | new — 19 functions / 31 instances |
| config | `.gitignore` | +2 lines: `data/live/`, `data/forecast.json` |
| docs | `.claude/features/forecast-live-fetch/*.md` | research, plan, findings docs |
| pipeline | `.claude/pipeline/STATUS.md` | F2 row → GREEN, phase/next → F3 |

`fetch/`, `score/`, `backend/`, `frontend/`, `docs/`, `run.sh`, `demo.sh` are **untouched**
(`git diff --stat` against all of them is empty — verified, and enforced going forward by
`test_t30_fetch_is_untouched_by_this_branch`).

## Tests

- Full suite: 516 passing (308 baseline + 208 new), exit 0, 3.46s, fully offline
- `ruff check .`: clean
- Types: n/a (SPEC §13 — none installed)
- Build: n/a (source-run Python, no bundler)
- Regression gate (FORECAST-SPEC §3): all five checks pass — see `test-pass.md` before cleanup

## Probe & Live Run — settled facts for the remaining tickets

1. **Probe result (196 read-only HEADs, init 2026-09-04 12z):** intersection across all four
   models is **f003…f048, step 3, 16 steps** → `meta.horizon_h = 48`, `meta.step_h = 3`. NBM
   publishes no `f000`. NAM's holes (37,38,40,41,43,44,46,47) all land off the 3-hourly grid, so
   the plan's §16 R1 `awip` detour was never needed. HRRR only reaches f048 because 00/06/12/18z
   are its extended runs — exactly this project's init set, not a general property of HRRR.
2. **Live run:** init 2026-09-04 12z, 64/64 fetches succeeded, run 1 7.535s, run 2 0.293s with
   all 64 cache-file mtimes unchanged from run 1 — the zero-network property is demonstrated on
   live data, not just in the offline raising-stub test.
3. **`derive_horizon` uses TRAILING truncation, not the plan's §2.3 wording.** The plan said
   "contiguous all-four run from `grid[0]`", which is wrong: under that rule an interior hole at
   f012 would set `horizon_h=9`, pushing f012 *above* the horizon and out of `gaps`, permanently
   collapsing `gaps` to empty. What's implemented and tested: a trailing incomplete run truncates
   `horizon_h`; interior holes are `gaps` inside the horizon. **F3 must build on trailing
   truncation, not the stale plan prose.**
4. **Two honest limits, not buried in the code:**
   - Zero 404s occurred on the live run, so `derive_horizon`'s truncation branch and `find_gaps`
     have **only ever been exercised in offline tests with an injected fetcher** (T19a, T21,
     T22, T22a) — never against a real missing lead. F3 should not assume this machinery has
     field validation.
   - The live run is **not** a second independent probe sample — same init (12z), same day as
     the probe. The implementer declined to add an `--init` flag to hunt a different cycle,
     correctly identifying that as the kind of experiment-tuning SPEC §10 forbids.
5. **A round-trip defect a test caught, not inspection:** `_iso` originally wrote second
   precision, so an in-memory record retained microseconds a cached copy would silently drop —
   the record `fetch_one` returned on the fetching run was unequal to what every later run reads
   back from cache. Fixed in `fetch_one`.
6. **A sub-agent's package-wide ban on the string `weight` across `forecast/` was narrowed** to
   `cycle.py` + `live.py` only. F3 legitimately applies fitted weights, and the broad ban would
   have forced F3 to delete an F2 guard to land — the wrong lesson to teach the next agent. The
   package-wide **`renorm` ban stays permanent**; that's the rule actually doing work.
7. **`fetch/` was not modified and must stay that way.** `GRIB_shortName` is `"2t"` on valid
   data (not `"t2m"`); `fetch/grib.py` already guards correctly on the data-variable name and
   `GRIB_cfVarName`. FORECAST-SPEC §3's literal shortName wording is factually wrong and was
   correctly not implemented — see session-log.md carried-findings §1.

## Key Decisions

- **Two-phase fallback rule** (adopted by the orchestrator to resolve a §5.2/§5.3 collision):
  Phase A fetches f003 for all four models and decides the fallback ladder; Phase B fills
  f006…f048 where a trailing miss truncates and an interior miss becomes a gap. No fallback
  fires in Phase B. The probe shows neither branch fires on a healthy cycle — this is insurance,
  not an observed behavior change.
- **Missing records are cached**, not just successes, so a dead lead costs one request per cycle
  attempt, never repeated.

## Deferred Items

- Truncation/gap code paths have no live-network validation yet (by design — SPEC §13 forbids
  live-network tests in the suite) — carried to F3 as a known coverage gap, not resolved here.
- No `--init` override flag — deliberately not added; would let an operator hunt a "better"
  cycle, which SPEC §10 treats as forbidden result-tuning.

## Retrospective

### Worked Well
- The injected-fetcher pattern (a stub that raises `NetworkUsed`, a class deliberately not a
  `RuntimeError` subclass) gives a genuinely unambiguous zero-network proof — a failure there
  can only mean the network was touched, not that some other exception got absorbed.
- Property-style tests (the T10 44-case stale-boundary sweep, the T22a disjointness sweep) caught
  more than example-based tests would have and made the "208 new tests" count independently
  verifiable rather than a number to take on faith.
- Live verification of the probe's `.idx` message-index shift (NBM: 135 at f003 → 173 at f048)
  reconfirmed the no-hardcoded-index rule on real data, not just in a fixture.

### Went Wrong
- The plan's §2.3 horizon-derivation wording was wrong and self-contradictory (it would have
  collapsed `gaps` to always-empty). The implementer caught it and implemented trailing
  truncation instead, documenting the correction in the session log — but the plan itself was
  never corrected, so anyone reading plan §2.3 in isolation would implement the wrong thing.
  **Lesson: when an implementer deviates from a plan for a documented reason, the plan doc
  should get a superseding note added at the point of deviation, not just a note in the session
  log that a later reader has to know to check.**
- A round-trip precision bug (`_iso` truncating to seconds) shipped past initial implementation
  and was only caught by a cache-equality test — inspection alone missed it. Confirms the value
  of asserting round-trip equality explicitly rather than just checking presence/absence of a
  cached file.

### Process
- Pipeline flow: smooth. Worktree isolation from the concurrently-active main checkout worked
  as designed — no collisions observed.
- Task granularity: right. F2 was scoped tightly enough to finish in one session with a real
  live-data run, not just offline tests.
- Estimate accuracy: the plan estimated "~30 new tests"; actual was 208. Verified as earned, not
  padding (see `test-pass.md`'s per-file breakdown), but the estimate itself was off by ~7x —
  worth flagging so F3's own test-count estimate isn't taken as a hard budget.
- Agent delegation: the implementing agent correctly refused two temptations that would have
  looked like progress — "fixing" `fetch/grib.py` to match FORECAST-SPEC §3's wrong literal, and
  adding an `--init` flag to re-probe a different cycle. Both refusals were the right call and
  are the kind of judgment worth naming explicitly in a retrospective, not just noting the code
  that resulted.
