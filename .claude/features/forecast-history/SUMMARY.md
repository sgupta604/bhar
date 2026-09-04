# Summary: forecast-history (F6)

**Completed:** 2026-09-04 | **Branch:** `feat/forecast-page` | **Commit:** recorded below |
**PR:** none — FORECAST-SPEC §12 opens a single PR for all nine tickets at F9; this ticket
only commits and pushes to the shared branch.

## What Was Built

The back-arrow into scored history: `forecast/history.py` builds `data/forecast_history.json`
(32 days, leads 6/12/24, 360 total entries) directly from `data/forecasts.parquet` and
`data/obs.parquet`, joined and validated exactly like the live path but replayed against the
archive. `forecast/contract.py` gained a `load_and_validate_history` seam; `backend/forecast_api.py`
required zero changes to serve it. `frontend/forecast.{html,js,css}` gained the back-arrow UI. This
is a **backtest replay** of days already in the archive at the time the blend weights were fitted —
**not** a live forward-validated track record (that is F9) and **not** the trust panel (that is F7).

## Files Changed

| Package | File | Change |
|---------|------|--------|
| backend | `forecast/history.py` | NEW — 764 lines, builds and validates the history payload from the two parquets |
| backend | `forecast/contract.py` | +745/-22 — adds `load_and_validate_history`, `HISTORY_TOL` |
| tests | `tests/test_forecast_history.py` | NEW — 37 tests, builder/omission/identity/anchor coverage |
| tests | `tests/test_forecast_history_contract.py` | NEW — 40 tests (51 collected), contract validation incl. 11 banned-field-name-at-depth cases |
| tests | `tests/test_forecast_history_ui_guards.py` | NEW — 61 tests (132 collected), frontend BANLIST + static guards |
| tests | `tests/test_forecast_refresh.py` | modified — F3's CLI-surface guard widened 3→4 entries to register `history.py` deliberately |
| frontend | `frontend/forecast.html/js/css` | modified — back-arrow UI, +609/-26 lines combined |
| data | `data/forecast_history.json` | NEW — 165 KB, 6322 lines, committed (not gitignored — the parquets are, so this is the only way a fresh clone can render the back-arrow) |
| docs | `.claude/features/forecast-history/**` | research + plan docs |

## Tests

- Full suite: 1209 passing (983 baseline + 226 new), 0 failed
- Lint: `ruff check .` clean
- Types/Build: n/a per SPEC §13 (no tooling installed)
- `backend/forecast_api.py`: zero diff — F4's lazy `getattr` seam lit up purely from `forecast/contract.py`

## Key Decisions

1. **The "empty join scores perfectly and is fake" guard is real, proven by mutation — twice.**
   Injecting `return []` into `_omitted_days` turned exactly the two named tests red on their own
   assertions; restored byte-identical (sha256 `846f8e24…`). The branch is **unreachable on real
   data** (1440/1440 matched), so it lives or dies by its fixture alone.
2. **The fixture needs 11 dates, and why.** A one-date version drops that group below
   `score.join`'s 80% match floor, which raises — exercising the floor, not the omission. Starving
   a date requires removing *two* readings — the date's own and the previous day's 23:52Z — because
   a forecast valid at 00:00Z matches backwards across midnight. A dedicated test pins that a
   3-date version raises, so the fixture cannot be quietly shrunk later.
3. **The `2026-08-04` edge day is real, not a bug.** MAE 6.1 at 6h and 14.47 at 12h, no 24h entry.
   Cause: the window's earliest init is 06:00Z, arithmetically excluding several lead/valid
   combinations, plus a genuine observation dip (67→64→69°F) all four models missed. Independently
   verified from raw parquet data. It is honest data and must never be trimmed (SPEC §15).
4. **32 days, not 30** — two partial edges. Nothing asserts `len(days) == window.days`; trimming
   the edges to force 30 would be the tuning §15 forbids.
5. **`HISTORY_TOL = 0.005 + ε`, not F3's `1e-6`** — the payload is 2-dp per design-target §6, so
   reusing `BLEND_TOL` would fail on correct data.
6. **Realized MAE is `1.825250 / 1.971250 / 2.045500`**, not the plan's `1.8253 / 1.9707 / 2.0449`.
   The plan computed unrounded; §6 mandates 2-dp `error_f`, so MAE over the *stored* errors differs
   by ~0.0006. The build is right; the plan's anchors were wrong.
7. **`best_single_model_f` is the named model's value, never the per-row closest member** — the
   latter is look-ahead bias, the same class of error as trusting `blends[0]`. A fixture where the
   two differ pins this.
8. **`backend/forecast_api.py` has zero diff.** F4's lazy `getattr` seam lit up purely by adding
   `load_and_validate_history` to `forecast/contract.py`. But new *code* needs a process restart —
   only new *data* is picked up per request. That cost ~45 minutes of confusing 503s during the
   build; F8 must document this restart-vs-data distinction.
9. **F3's guard pinning `forecast/`'s CLI surface to three entry points was deliberately widened
   to four** (`history.py` registered by name in the test docstring), then re-proved to still fire
   on a fifth. Widen deliberately, then re-prove teeth — never weaken a guard silently.

## Deferred Items

- Trust/track-record framing (whether the history is presented as trustworthy, with caveats) is
  F7's job, not this ticket's.
- Live forward-validation (comparing future predictions to future outcomes as they arrive) does
  not exist yet and is F9's job. This ticket replays only days already in the archive when the
  weights were fit.

## Retrospective

### Worked Well
- Mutation-testing the omission guard (inject `return []`, watch the exact two tests go red,
  restore byte-identical) caught that the branch was otherwise untestable on real data — a claim
  that would have been impossible to verify by inspection alone.
- Widening the F3 CLI-surface guard by name (registering `history.py` in the docstring rationale)
  instead of loosening the assertion kept the guard at full strength — re-proven to still fire on
  a fifth surface.

### Went Wrong
- ~45 minutes lost to confusing 503s because new *code* (the `load_and_validate_history` seam)
  needs a server restart while new *data* files are picked up live per request — this distinction
  wasn't obvious from the seam's design and cost real debugging time. Lesson: **a guard/branch
  whose real-data path is unreachable lives or dies entirely by its fixture, and that fixture must
  itself be proven necessary (not just present)** — the same applies to any "can't happen on real
  data" code path added in future tickets.

### Process
- Pipeline flow: smooth — research → plan → implement → test → finalize with no rework needed.
- Task granularity: right — the fixture-construction task (11 dates, cross-midnight offsets) was
  correctly sized as its own step rather than folded into the builder task.
- Estimate accuracy: the plan's MAE anchors were computed unrounded and were off by ~0.0006 from
  the actual 2-dp-rounded stored values; otherwise on target.
- Agent delegation: test-agent's independent mutation re-verification (not just re-reading the
  implementer's claim) is what actually proved the omission guard's teeth — worth keeping as
  standard practice for any "unreachable on real data" branch.
