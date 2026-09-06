# Summary: forecast-skill-panel (F7 — the trust panel)

**Completed:** 2026-09-05 | **Branch:** feat/forecast-page | **PR:** none yet — single PR opens at end of F9 (FORECAST-SPEC §12)

## What Was Built

The trust panel for the forecast page: a section that shows how each blend's weights performed
historically (backtest out-of-sample skill vs. the best single model, plus a realized-error
figure), stated entirely in past tense with explicit windows and leads, and gated by a four-layer
copy guard so no future edit can turn a historical measurement into a promise about the current
forecast. The panel renders three variants (better/level/worse than the best single model) chosen
by the same function that sets the visual tone, so text and colour cannot disagree, and it
surfaces (rather than hides) the fact that the fixture payload's 24 h blend actually loses to GFS.
When the fixture's synthetic backtest is served, the panel now states plainly that the backtest
figures are fabricated and not comparable to the realized figure beside them.

## Files Changed

| Package | File | Change |
|---------|------|--------|
| frontend | `frontend/forecast.js` | +571/-1 — skill panel render logic, tone/variant selection, realized-vs-backtest derivation, synthetic-mixing label |
| frontend | `frontend/forecast.css` | +169 — F7 region styling, win/loss colour-only tone rule |
| frontend | `frontend/forecast.html` | +19 — panel mount points |
| tests | `tests/test_forecast_skill_panel_copy.py` (new) | 1691 lines — 4-layer copy guard: containment, byte-pin, blacklist+allowlist, derived-not-typed checks |
| tests | `tests/test_forecast_skill_panel_ui_guards.py` (new) | 1439 lines — region/geometry/token-injection guards |
| docs | `.claude/features/forecast-skill-panel/` | plan + research docs (research already committed earlier; this adds the plan and this summary) |

## Tests

- Full suite: 1480 passing, 0 failing (1212 pre-existing + 268 new)
- `ruff check .`: clean
- Types: n/a (SPEC §13, deliberate — none installed)
- Build: n/a (no bundler)
- Verification gate (FORECAST-SPEC §3): `git diff --numstat 740dfb0 -- backend/main.py` → `2 0`;
  `data/results.json` sha256 `3b113a99…`, `data/forecast_history.json` sha256 `e9a3482c…` — both
  byte-identical to pre-F7; exactly 3 `frontend/forecast.*` files; all protected paths
  (`tests/test_live_guards.py`, `test_forecast_ui_guards.py`, `test_forecast_api_guards.py`,
  `score/**`, `backend/**`, `forecast/**`, the nine pre-existing frontend files +
  `overview.css`/`overview.js` + `vendor/**`, `docs/**`, `run.sh`, `demo.sh`, `.gitignore`)
  confirmed unmodified in the working tree.

## Key Decisions

- **`1.973` not `1.9730`** — padding the realized figure to a fixed decimal width would print
  `5.5500 °F` on the fixture and invent a measured digit that was never recorded. Overrides the
  plan's stated formatting default; deliberate, documented in code and in progress.md.
- **The IMPROVEMENT cell stays untoned (no second `--success` colour rule)** — a second success
  rule on that cell would visually double-endorse the same number the tone token already colours
  elsewhere, violating OQ-A (no compounding endorsement). One `--success` per rendered figure.
- **Containment guard runs first, before byte-pin/blacklist/derivation checks** — without it, the
  other three layers only scan whatever substring containment happens to isolate, and can report a
  green result over a shrunken or wrong scope. This ordering carries forward F5/F6's guard pattern.
- **Synthetic-mixing label gated on a single boolean (`state.meta.is_synthetic`)**, not a second
  `data-synthetic` DOM attribute — avoids a second source of truth that could drift from the first.
- **12 h boundary test corrected mid-implementation**: the plan (§6.4) asserted the global re-split
  boundary differs from the per-lead boundary "at every lead," citing 79/41 and 77/43. It is
  actually **coincident at 6 h** (80/40) because 6 h sets the global minimum `valid_time` by
  construction — the plan's claim would have made the shipped test assert something false. The
  test was corrected to check 12 h/24 h only, with the reasoning left in the test file.

## Deferred Items

- **`forecast/contract.py`'s value-level `skill.note` §6.2 ban remains open** (tracked as a
  standalone quickfix, out of scope for F7 per the plan and the ticket instructions). The words are
  banned as dict *keys* but `skill.note`'s *value* is validated only as non-empty — a
  server-authored note reading "we expect tomorrow to be within 2 degrees" would currently pass
  contract validation and render verbatim. F7's guard suite catches this in the committed frontend
  copy only, not in a hypothetical future server payload.
- **`weights_age_days > 45` staleness-note class swap** has no exercisable payload in this repo
  (`weights_age_days` is 0 on both committed payloads) — verified at source only, not exercised
  end-to-end. Not a defect; disclosed in progress.md and test-pass.md.

## Retrospective

### Worked Well
- Reproducing the ticket's own injection scenario against the *real* `frontend/forecast.js` file
  (not a copy), then restoring byte-identical and re-running green, is now a proven pattern across
  three tickets in this project (F5, F6, F7) for proving a grep/pin-based guard is not fake-green.
- Deriving the pair-count figure (`round(40 * 30/10) = 120`) independently instead of trusting the
  rendered number caught that the claim really is computed, not typed, on both payloads.
- Selecting variant (better/level/worse) and colour tone from the same function eliminated an
  entire class of "text says one thing, colour implies another" bugs by construction.

### Went Wrong
- The plan's §6.4 boundary claim ("differs at every lead") was wrong at the earliest lead for a
  structural reason (6 h sets the global minimum `valid_time`) that should have been checked by
  hand before being written into the plan as a certainty. **Lesson: a claim about "every N" derived
  from a small, fixed set (three leads) is cheap enough to verify by hand before it becomes a test
  assertion — don't let a plausible-sounding universal claim skip that check.**
- The realized-vs-backtest caveat, the strip cross-link sentence, and the synthetic-mixing
  statement are pinned as *authored* text with no external anchor (unlike most of the panel copy,
  which must reproduce design-target §4 verbatim). Their byte-pins prove only that nobody edited
  them since they were written — not that they are correct. This was caught during implementation,
  not planning; a plan that flags "which sentences will have no independent anchor" up front would
  surface this earlier.

### Process
- Pipeline flow: smooth. Research was already committed from before the pause; plan → implement →
  test → finalize proceeded without a diagnose loop.
- Task granularity: right — the four-layer-guard structure gave natural task boundaries (Layer 1
  containment, Layer 2 byte-pin, Layer 3 blacklist+allowlist, Layer 4 derivation checks) that each
  produced an independently testable unit.
- Estimate accuracy: not tracked in hours for this ticket; scope matched the plan except for the
  one corrected boundary assertion (§6.4) and the two deliberate formatting/styling overrides noted
  above.
- Agent delegation: test-agent's independent re-derivation (recomputing pooled MAE and pair counts
  from raw data rather than trusting the report) is what actually closed the "is this guard real"
  question — worth keeping as standard practice for any ticket that ships a compliance guard.
