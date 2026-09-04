# Summary: demo-shell (T3 of 6)

**Completed:** 2026-09-04 | **Branch:** feat/site-tuned-blend | **PR:** none — no git remote configured (SPEC §8; PR step skipped, not failed)

## What Was Built
The SPEC §7 `results.json` contract locked in executable form (`backend/contract.py::validate_results()`),
a deterministic synthetic fixture generator, a FastAPI backend serving the fixture at `GET /api/results`
(CORS, per-request re-validation, 503-on-failure — never a silent fallback), and a static Clarity-styled
frontend rendering a leaderboard, lead-time toggle, live weight sliders (exact-lookup, never computed),
a two-model error/weight chart, and an honesty panel. `data/results.json` on disk is now the entire T5
seam: T5 overwrites that one file and touches no frontend code. This is the demo-insurance ticket — after
it, a demoable artifact exists even if every downstream ticket fails.

## Files Changed
| Package | File | Change |
|---------|------|--------|
| backend | `backend/contract.py` | NEW — `validate_results()`, the executable §7 lock, shared with T5 |
| backend | `backend/make_fixture.py` | NEW — deterministic seeded synthetic generator |
| backend | `backend/main.py` | CORS, `GET /api/results`, disk load + re-validation, 503 path |
| data | `data/results.json`, `data/results.synthetic.json` | NEW, committed — the insurance artifact |
| frontend | `frontend/index.html`, `tokens.css`, `app.css` | NEW — shell, Bhar-local tokens, layout |
| frontend | `frontend/app.js`, `models.js`, `format.js`, `chart.js` | NEW — fetch/state/render, exact-lookup sliders, signed formatting |
| frontend | `frontend/vendor/` | Clarity `tokens.css` + 3 WOFF2 faces, vendored — zero network at render |
| scripts | `scripts/smoke_ui.sh` | NEW — agent-browser check, outside pytest |
| root | `run.sh` | `?api=` URL on port override; cleanup-ordering bugfix (sweep before `wait`) |
| design | `.claude/features/demo-shell/design-target.md` | NEW — written `/design` pass output |

## Tests
- Full suite (incl. concurrent T2/T4 work): 220/220 passing
- T3-only (`test_results_contract.py`, `test_fixture_gen.py`, `test_scaffold.py`): 34/34 passing
- Build: n/a (static frontend, no bundler, by decision) | Lint: `ruff check .` clean | Types: n/a (none installed, by decision)
- `scripts/smoke_ui.sh`: exit 0, full agent-browser run (not degraded); independently re-verified by the test-agent with its own slider vector
- Security/quality sweep (this pass): no secrets, no debug leftovers, no TODO/FIXME/HACK, no commented-out code, no machine-specific paths, across all files touched by `b40b381` and `8c4bf20`. The `print()` calls in `backend/make_fixture.py` are the CLI's intended output; the `python3 -c 'print(...)'` one-liners in `scripts/smoke_ui.sh` are JSON-parsing helpers inside a shell script, not debug leftovers.

## Key Decisions
- **The T5 seam is one file.** `data/results.json`, served whole by `GET /api/results`. Flipping `meta.is_synthetic` to `false` removes the banner, the 3px inset frame, and the `[SYNTHETIC]` title prefix with **zero frontend code edits** — all three key off that single boolean, and this was verified by hand-flipping the value and re-rendering, not assumed.
- **`blends` must be the COMPLETE 286-point grid** (`C(13,3)` over 4 models at a 0.1 step), not a top-N. The slider works by exact lookup into that array; a truncated array silently breaks it with no error. Verified 286 at all three lead times (6h/12h/24h), and `validate_results()` now enforces the count so T5 fails loudly rather than shipping a dead slider.
- **Winner is selected on in-sample MAE, reported out-of-sample (D13).** This is what makes `improvement_pct_vs_best_single` capable of going negative honestly — if the winner were simply `blends[0]` (OOS-sorted), the number could never be negative and SPEC §10's honesty requirement would be untestable. Consequence for anyone building on this: **the winner is not `blends[0]`.** Its out-of-sample rank was #2 at 6h, #5 at 12h, and **#17 at 24h** — the originally-planned leaderboard rule (top-5 + every pure model) would have made the winner invisible at 24h, so the rule was changed mid-implementation to always include the winner row regardless of rank. Match the winner by `winner.label`, never by index.
- **`backend/contract.py::validate_results()` is the executable §7 lock.** T5's acceptance test must call this same function on the real file, unchanged — including the `models_included` / `models_excluded` disjointness check (D14; the SPEC §7 example itself lists NAM in both lists, which is internally inconsistent and was not copied).
- **`run.sh` had a cleanup-ordering bug**, not caught by the plan's "change nothing else" instruction: `cleanup()` called `wait` *before* the port sweep, and when a child outlived SIGTERM, `wait` blocked forever — the sweep never ran, and the *next* `./run.sh` refused to start (port still held). Fixed to sweep first, reap second. Verified clean over 2+ full start/SIGTERM/restart cycles (`ps` + `lsof` showed no orphan and no held port after each cycle, including a successful restart on the same ports).
- **The 16:00 demo command, because port 8000 is squatted** by a VS Code helper that answers `/health` byte-identically to this app: `BHAR_BACKEND_PORT=8011 BHAR_FRONTEND_PORT=5184 ./run.sh`, then open the `Frontend:` URL it prints — it already carries the `?api=` override. Confirm identity via `/openapi.json`'s title (`"Bhar - Site-Tuned Model Blend"`), **never** `/health`. **T6's README must lead with this line, verbatim.**
- **Zero external network at render.** Clarity's `tokens.css` and all 3 WOFF2 faces (Inter, Sora, JetBrains Mono) are vendored into `frontend/vendor/`. `grep -rn "https\?://" frontend/*.html frontend/*.css` returns zero hits; the one `http://` hit in `frontend/*.js` is the required `localhost:8000` API-base fallback, appearing exactly once.

## Deferred Items
- **Chart pair selector and the chart itself were never actually cut** — the plan's pre-declared cut order (pair selector → chart → dark mode) existed as an escape hatch for the 05:30 checkpoint but was not needed; Stream 4 finished on time with nothing cut.
- **Dark mode** — deferred by design decision D11 (Clarity's fetchable `tokens.css` is light-only; hand-copying dark values from the token doc was out of scope for this ticket). Tokens are authored under `:root` so `[data-theme=dark]` can be dropped in later without restructuring.
- **No refetch endpoint, not even a 501 stub (D8)** — a live-fetch route that is never pressed on the demo path is dead code and a foot-gun. The refresh path is described in the README (T6) as the offline CLI instead.

## Test Gaps (acknowledged, not hidden)
- **Model-checkbox filtering was not independently step-driven by the test-agent.** It is visually present and the code path is described in `progress.md`, but the test-agent's handoff notes this was taken partly on the strength of code review rather than an independent drive of the checkboxes — a light gap under the timebox, not a failure.
- **The 503 path was not re-exercised by the test-agent.** The implementer's `progress.md` reports it was tested (missing file, truncated `blends`, malformed JSON — all returning 503 with a specific message, then restored byte-identical) and every other check the test-agent ran independently confirmed the file is currently present and valid, but the test-agent deliberately did not re-run the 503 scenario itself, to avoid any risk of leaving the insurance artifact (`data/results.json`) in a bad state during an unattended run.

## Retrospective

### Worked Well
- **Contract-first ordering.** Writing `backend/contract.py` and `backend/make_fixture.py` before any consumer existed meant the fixture, the backend, and the frontend were all built against one already-locked shape — no shape renegotiation mid-stream, and the foundation was committed (`b40b381`) before the frontend existed, so a frontend failure could never have cost the whole ticket.
- **Writing the smoke script's DOM contract (data-weights/data-mae-oos attributes, class names) before spawning the frontend-building agent**, then handing the same selectors to that agent. Both sides were built against one written spec instead of the check being retrofitted afterward.
- **The fixture deliberately exercises its own honesty requirements** — a genuinely negative improvement at 24h (−1.16%), a winner that is never OOS rank 1, an excluded model that was never in the study. The dishonest-rendering guardrails are proven live by the demo itself, not only by unit tests.
- **Independent verification with a self-picked vector.** The test-agent didn't reuse the implementer's reported slider example; it drove its own weight vector and cross-checked against `curl /api/results` directly. That's the difference between "the implementer says it agrees" and "it agrees."

### Went Wrong
- **The plan's own leaderboard row rule (top-5 blends + every pure model) was under-specified against its own acceptance bar.** It produces only 8 rows at 24h (one pure model already sits in the top 5) against a stated "≥9 rows at every lead," and — worse — the winner's actual OOS rank (#17 at 24h) meant the winner row would not have appeared on the leaderboard at all under the literal rule. Lesson: when a plan states both a construction rule and a numeric acceptance bar for the same output, check them against each other with the real data before treating the rule as final — "top 5 + pures" and "≥9 rows, winner always visible" are not the same constraint once the winner isn't OOS-sorted.
- **A "change nothing else" instruction on `run.sh` almost hid a real regression.** The plan assumed the existing cleanup trap (T1's "hard-won behavior") already handled orphaned processes; it did not — `wait` blocking before the port sweep meant the *next* invocation of `./run.sh` would refuse to start after any Ctrl-C that outlived the signal. This would have cost real minutes at 16:00 on exactly the first restart. Lesson: "don't touch working code" is a fine default, but the acceptance criterion ("Ctrl-C leaves no orphans") should always be independently verified against the actual behavior, not assumed satisfied because a prior ticket wrote it.

### Process
- Pipeline flow: smooth. Research → plan → implement → test ran without a blocked task or a stop-and-wait condition; two deviations were caught and self-corrected within `/implement`, both documented in `progress.md` with the reasoning, rather than silently diverging from the plan.
- Task granularity: right. The plan's stream split (design/contract/backend/frontend/smoke/verify) gave each delegated agent a self-contained unit; Stream 4 (all of `frontend/`) was correctly kept as one agent rather than split, since splitting would have put two agents in `app.js` simultaneously.
- Estimate accuracy: estimated 60–90 min (scope **L**), actual ~70 min. Accurate, and nothing was cut despite the plan pre-declaring a cut order for exactly this contingency.
- Agent delegation: general-purpose agents handled Streams 1 (design + vendor), 2 (contract + fixture), and 4 (frontend) cleanly, each passing acceptance on the first or second round (Stream 4 needed one follow-up pass for the above-the-fold honesty-panel layout). Streams 3, 5, and 6 (backend API, smoke check, verify+commit) were handled directly by the execute-agent rather than delegated further — appropriate given their small, single-file scope and the need for tight identity/CORS/503 verification loops that benefit from staying in one context.
