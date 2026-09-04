# Summary: score-and-blend

**Completed:** 2026-09-04 | **Branch:** feat/site-tuned-blend | **PR:** none — no git remote configured (see Deferred Items)

## What Was Built
The scientific core of the project (T5 of 6): joins T4's 1440 forecast rows to 932 real METAR observations under SPEC §4's ±30 min nearest rule, splits chronologically (first paired valid_time + 20 days, 80/40 train/test), scores all 4 NOAA models and searches all 286 simplex weight vectors per lead against the resulting KOMA data. `data/results.json` was replaced with the real, non-synthetic document. Commit `78046e7`.

## Files Changed
| Package | File | Change |
|---------|------|--------|
| score | `score/join.py` | SPEC §4 merge_asof join, per-row `offset_min`, 80% match-rate RAISE |
| score | `score/metrics.py` | PATH A: `model_metrics` — pure-model MAE/RMSE/bias, no weight vector, no blend import |
| score | `score/blend.py` | PATH B: `simplex_grid`, `design_matrix`, `evaluate_design` (+ column-order RAISE), `blend_metrics` |
| score | `score/split.py` | D1 chronological train/test boundary |
| score | `score/build.py` | §7 document assembly, coverage floor, runtime one-hot RAISE, pre-return validate |
| score | `score/run.py` | CLI entrypoint (`python -m score.run`), I/O only, validate-then-atomic-write |
| data | `data/results.json` | Replaced with the real document (`is_synthetic: false`, `source: noaa_s3_grib`) |
| tests | `tests/*` (join/metrics/blend/split/build) | New coverage per module; `test_build.py`'s purity test rewritten as an AST walk (was self-referential and matching its own forbidden-token list) |

## Tests
- Full suite: 308 passing, 0 failing
- Non-integration (`-m "not integration"`): 288 passing, 20 deselected
- Lint: `ruff check .` clean
- Types: n/a by SPEC §13 decision
- Contract: `data/results.json` validates unchanged against `backend/contract.py`; `data/results.synthetic.json` byte-unchanged (md5 confirmed) as demo rollback

## Key Decisions
- **The real headline results, reported as computed, not tuned toward:**
  - 6h: winner HRRR 50 / NAM 10 / NBM 40, OOS MAE 1.9173 vs best single (HRRR) 2.1075 → **+9.02%**
  - 12h: winner HRRR 60 / NAM 10 / NBM 30, OOS MAE 1.9661 vs best single (HRRR) 2.2814 → **+13.82%**
  - 24h: winner HRRR 50 / NAM 10 / NBM 40, OOS MAE 2.1066 vs best single (HRRR) 2.5231 → **+16.51%**
  - Join: 480/480 (100.00%) matched at every lead, mean |offset| 7.92 min, 120/120 paired valid times, 80/40 train/test split.
- **HRRR, not NBM, is the best single model at all three leads.** SPEC §1 anticipated NBM might win outright; the data says otherwise. This must drive the README framing, not the SPEC's prior expectation.
- **The honest framing — must not be softened:** an un-fitted "drop GFS, average the rest" blend (HRRR 0.4 / NAM 0.3 / NBM 0.3) scores 1.9865 / 1.8879 / 2.0886 across leads and is **rank 1 — the floor — at 24h**. Most of the measured gain is from avoiding GFS, not from the fitted tenths. GFS takes weight 0.0 in every winning vector.
- **GFS was included and simply earned zero weight — that is a result, not an exclusion.** Coverage was 100.00% for all four models; nothing was excluded by the 90% floor. GFS's problem is a diurnal amplitude error (+5.1°F at 18z, −2.2°F at 12z), not a decode bug.
- 47/116/105 of 286 blends beat the best single model at 6h/12h/24h respectively — a broad plateau, not one lucky cell.
- **SPEC §10's >10% "investigate, don't celebrate" tripwire fired at 12h and 24h.** It was investigated, not shipped on trust: (1) an independent brute-force hand join/re-derivation (no `score/` import) reproduced all 12 model/lead metric triples to 4dp; (2) the plateau count above; (3) the in-sample choice lands near the OOS optimum; (4) the un-fitted "drop GFS" comparison above. Nothing about the experiment itself was changed — one window, one site, one split, one join tolerance, one run.
- **Mutation proof, independently reproduced twice.** Injecting `W = W[:, ::-1]` into `evaluate_design` turns the non-negotiable one-hot-identity test red — the test-agent's independent run found 5 failing tests (more than the implementer's reported 2, a stronger result) — and the file was restored md5-identical afterward. The single most important test in the project provably can fail.
- A genuine bug was found and fixed in T5's own suite: `test_build.py`'s purity test was scanning its own source file and matching its own forbidden-token list, so it could never go red. Rewritten as an AST walk that skips its own body — strengthened, not relaxed, and verified to still fail on an injected `import socket`.

## Deferred Items
- **PR skipped — no git remote configured on this repo.** Work is committed to `feat/site-tuned-blend` locally; push/PR is unavailable until a remote is added.
- **Handoff note for T3's owner (`readme-and-caveats`), recorded not fixed — out of T5's scope:** `scripts/smoke_ui.sh` step 6 assumes a *negative* 24h improvement, which was true against the synthetic fixture but is false against the real data (+16.51%), so it no longer exercises the danger-tone render path.

## Retrospective
### Worked Well
- Running the acceptance floor (SPEC §8's one-hot identity) through two structurally independent code paths (PATH A never imports `blend.py`; PATH B never imports `metrics.py`) made the mutation proof meaningful rather than circular — sabotage one path and the other still tells the truth.
- Treating the >10% tripwire as a checklist rather than an alarm: four independent, cheap verifications (hand re-derivation, plateau count, in-sample/OOS proximity, un-fitted-blend comparison) resolved the "is this real" question without touching the experiment.
- Fixing the self-referential purity test by strengthening it (AST walk) instead of loosening its token list — the SPEC §10 failure mode is exactly "weaken a test to get green," and the team caught itself before doing that.

### Went Wrong
- The prior execute-agent was killed mid-task by an API spend limit during the "mutate then restore" step for the negative-control proof — the exact step where a stranded mutation would have been worst. No data was lost (progress.md records the resume and an md5-verified restore), but it's a reminder that destructive-but-reversible steps should checkpoint their pre-state hash before mutating, not just intend to restore it. Lesson for future tickets: any test that intentionally corrupts a source file for a negative control should snapshot+verify the hash on both sides of the mutation, unconditionally, not only when nothing goes wrong.

### Process
- Pipeline flow: smooth apart from the mid-task agent kill, which was infrastructure (spend limit), not a code or plan failure; the resuming agent verified rather than blindly trusted the inherited state.
- Task granularity: right — module-per-task (join/metrics/blend/split/build) matched the two-path independence the acceptance test needed.
- Estimate accuracy: not tracked in hours; the >10% tripwire investigation added real but justified time beyond a "just ship it" pass.
- Agent delegation: the test-agent's independent mutation proof (5 failures vs. the implementer's reported 2) is a good example of the second pair of eyes finding a stronger signal than the first — worth keeping this pattern of never trusting the implementer's own report of a negative control.
