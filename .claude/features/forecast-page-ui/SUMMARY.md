# Summary: forecast-page-ui (F5)

**Completed:** 2026-09-04 | **Branch:** `feat/forecast-page` | **Commit:** `72f0630` | **PR:** none —
FORECAST-SPEC §12 opens a single PR for all nine tickets at F9; this ticket only commits and pushes
to the shared branch.

## What Was Built

The first visible surface of the forecast page: `frontend/forecast.html`, `frontend/forecast.js`,
`frontend/forecast.css` (a complete static skeleton, one-pass renderer, and re-authored Clarity
component styles — no build step, no framework, no imports), plus a test-only DOM/string guard
suite (`tests/test_forecast_ui_guards.py`) and a trap-restoring payload-swap harness
(`scripts/f5_payload_swap.sh`) used to drive the page against live, fixture, missing, and corrupt
`data/forecast.json` states without ever risking the one live copy of NOAA cycle `2026090412` this
worktree holds. Zero existing frontend files were touched; `backend/main.py` carries only F4's
already-committed two lines.

## Files Changed

| Package | File | Change |
|---------|------|--------|
| frontend | `frontend/forecast.html` | NEW — 254 lines, static skeleton, every state's markup unconditionally present, 31 unique ids |
| frontend | `frontend/forecast.css` | NEW — 1092 lines, design-target §2 (44 blocks) + §3 pasted verbatim, Clarity components re-authored (`app.css` is off-limits) |
| frontend | `frontend/forecast.js` | NEW — 845 lines, single file, no imports, attribute-gated state on `<html>` |
| tooling | `scripts/f5_payload_swap.sh` | NEW — 351 lines, trap-restoring swap harness with SHA-256 verification, repo-root guard pinned to this worktree only |
| tests | `tests/test_forecast_ui_guards.py` | NEW — ~1555 lines (149 test cases, plus a post-commit fix to two of them — see Known Issue below), 56 test functions: non-vacuous BANLIST gate + static guards + regression-diff gate |

`.gitignore` was touched and then reverted in the same finalize pass (see Key Decision 8) — net
change is zero; it does not appear in the final diff.

## Tests

- Full pytest, run against the **pushed, committed** tree (not the pre-commit tree test-agent
  saw): **976 passing, 1 failing**, not the 977/0 that `test-pass.md` reported. The failure is
  `tests/test_forecast_api_guards.py::test_test10_diff_names_no_off_limits_path` — pre-existing,
  F4-owned, **not caused by any content F5 wrote**. Full explanation in **Known Issue** below;
  treat that section as required reading before trusting "green" on this branch.
- Guard module alone: `tests/test_forecast_ui_guards.py` — 149/149 passing (after the post-commit
  fix described below)
- Build: n/a (static frontend, source-run Python) | Lint: `ruff check .` clean | Types: n/a (SPEC §13 — none installed)
- Regression gate (§3), re-verified against actual `HEAD` (not `HEAD` compared to itself, which is
  what running this before the commit would silently give you): `git diff --stat 00e3441 HEAD --
  frontend/ backend/ score/ docs/ run.sh demo.sh` shows exactly the three new files as pure
  additions, nothing else; all nine pre-existing `frontend/` files (`index.html`, `overview.html`,
  `app.js`, `app.css`, `models.js`, `theme.js`, `tokens.css`, `chart.js`, `format.js`) plus
  `vendor/` are byte-identical to `HEAD`; `git diff --numstat 740dfb0 HEAD -- backend/main.py` is
  exactly `2 0`; `data/results.json` byte-identical; `data/forecast.json` SHA-256 still
  `9a860e1d…`, matching the verified backup throughout.

## Known Issue — suite is not fully green, and the cause is not F5's content

Discovered during finalize's own re-verification, **after** the commit, by re-running the full
suite against the actual committed tree instead of trusting `test-pass.md`'s pre-commit number.
Two distinct problems, handled two different ways:

1. **Fixed here (in-scope):** two of F5's own new guard tests
   (`test_diff_gate_no_tracked_demo_path_file_was_modified`,
   `test_diff_gate_the_three_new_files_are_present_and_untracked`) compared the base commit to the
   **working tree** (`git diff <base> --`, `git status --porcelain`) instead of to `HEAD`. That
   reads correctly before a commit and is permanently, unfixably red after one — the moment
   `forecast.{html,js,css}` are tracked, `git status` can never again show them as `??`. A sibling
   test in the same file (`test_diff_gate_backend_main_gained_exactly_two_lines`) already used the
   correct commit-to-commit pattern and says so explicitly in its docstring ("Commit-to-commit on
   purpose ... already committed"). Rewrote both to use `git diff --name-status <base> HEAD`,
   matching that sibling. This file is F5's own, so fixing it is in scope; behavior asserted is
   unchanged, only the mechanism.
2. **NOT fixed here (out of scope — another ticket's protected file):**
   `tests/test_forecast_api_guards.py::test_test10_diff_names_no_off_limits_path` is F4's guard.
   Its `OFF_LIMITS` tuple includes a blanket `"frontend/"` prefix, and its base is
   `branch_point()` — `git merge-base HEAD develop`, i.e. **the whole branch's divergence point**,
   not F4's own commit range (contrast `MAIN_PY_BASE = "740dfb0"`, used two tests above it in the
   same file, which correctly scopes to F4 alone). Because every ticket after F1 shares this one
   branch, that test was always going to break the instant *any* later ticket added a file under
   `frontend/` — and STATUS.md's mid-branch update explicitly **lifted** the frontend/ hold for F5
   ("F5 may now create `frontend/forecast.{html,js,css}`"). F4's guard was never updated to match
   that authorization. This is a stale guard, not a regression: F5 did exactly what it was told to
   do, and the guard's scope predates being told that. `tests/test_forecast_api_guards.py` belongs
   to F4, not F5 — F5's own guard file says so explicitly in its header comment ("belongs to
   another ticket") — so it was left untouched rather than edited unilaterally.

**This blocks a fully-green suite for F6 onward until someone with authority over F4's guard file
narrows its `OFF_LIMITS` entry from the blanket `"frontend/"` to the specific paths STATUS.md
actually still protects** (`frontend/index.html`, `overview.html`, `app.js`, `app.css`,
`models.js`, `theme.js`, `tokens.css`, `vendor/**` — not `frontend/forecast.*`, which F5 was
authorized to add). Recommend a small coordinated fix — not a fresh ticket — before F6 starts, so
F6 inherits a green baseline rather than one known-red test it has to rediscover.

Full detail was recorded in `.claude/active-work/forecast-page/test-pass.md` (PASS, recommended
for finalize) before cleanup.

## Key Decisions

1. **The BANLIST guard is GENUINE, and was proven by injection, not by reading the test file.**
   test-agent injected `p90`, `confidence_pct`, `uncertainty` and `±` (U+00B1) into the real
   `frontend/forecast.{html,js,css}` — not copies — confirmed the suite went red every time, then
   restored byte-identical (SHA-256 compared before/after). The haystack assertion is itself
   code-enforced (`test_haystack_is_exactly_three_files` asserts exactly 3 filenames;
   `test_haystack_each_file_exists_and_is_not_empty` asserts `path.is_file()` plus a 2000-byte
   floor per file), so a typo'd path fails immediately rather than silently grepping nothing and
   passing. **This project had shipped a guard that could not fail three times before this** — F1's
   gate, F4's phantom AST check, and the demo team's `prefers-color-scheme` split (see
   RETROSPECTIVES.md for all three). It did not happen a fourth time here.
2. **Dark mode cost ~25 mirrored lines, not a new layer.** `tokens.css:236-281` already ships both
   design-target §5.1 (semantic override) and §5.3 (the `--model-*` 300-weight step) verbatim, so
   F5 authored neither — re-declaring either would be exactly the second source of truth §0.1
   forbids. Only §5.2's pre-hydration script was mirrored, and a test asserts the
   `internal-portal:theme` key literal is byte-identical to `index.html`'s so the two pages cannot
   silently diverge. `--mark-color` stays a `var()` reference, never resolved to hex.
3. **`frontend/theme.js` is deliberately NOT script-tagged on this page.** F5's read-only grant
   names three CSS files, not this JS file; its `linkify()` helper is dead code here, and
   `onChange` exists to drive `models.js.resetColors()`, a concern F5's single-pass renderer
   sidesteps entirely.
4. **The hostile fixture (`data/forecast.fixture.json`, synthetic and deterministic) did its job.**
   Its zero-weight model is NAM where the live payload's is GFS, so any hardcoded model name would
   have rendered correctly against live and lied against the fixture — it didn't, because
   zero-weight is computed per-payload (`row.weights[m] === 0`). Both the fixture's gaps carry
   neither `data-band` nor `data-extrapolated`, including the gap at lead 48 (past the 24h
   boundary, adjacent to an extrapolated cell) — the interior/beyond-boundary distinction holds in
   both directions.
5. **Both strip-boundary layout forms were verified**, not just the default: row-edge break at 8
   columns (1440×900) and mid-row break at 6 columns (1300×900).
6. **Known F3 defect, out of F5's scope, not fixed here:** `meta.weights_source.path` in the live
   payload is the absolute path `/Users/sanjaygupta/Projects/Bhar-forecast/data/results.json`,
   where FORECAST-SPEC §9 specifies a repo-relative `"data/results.json"`. It leaks a home
   directory into a customer-facing trust-panel field and makes the payload non-reproducible
   across machines. F5 renders this value **verbatim** from the payload rather than constructing a
   path itself, which is the correct behavior for this ticket — the fix belongs in
   `forecast/build.py` (F3's module) and should land there, in one place, not patched around here.
7. **Scope boundary confirmed, not assumed:** `best_single_model` and `improvement_pct` belong to
   F7, not F5. `grep -c` for both against `frontend/forecast.js` returns 0 (the only hit is a
   comment noting them as a "never do this here" reminder).
8. **Fixture-commit decision: NOT committed, and left un-gitignored.** `data/forecast.fixture.json`
   stays untracked. Reasoning: it is deterministic and regenerable via
   `uv run --no-sync python -m forecast.make_fixture --out data/forecast.fixture.json`; no pytest
   in the suite depends on the repo-root copy existing on disk — `tests/test_forecast_fixture.py`
   and `tests/test_forecast_api.py` both build their fixture documents in memory or under
   `tmp_path` via isolated fixtures (`isolated_paths`, `forecast_path`), never reading
   `<repo>/data/forecast.fixture.json`. The one consumer that does read the real path is
   `scripts/f5_payload_swap.sh` (manual browser-probe tool) — it does **not** auto-regenerate the
   file and exits with "fixture not found" if it's absent, so **F6–F9 sessions must run the
   `make_fixture` command above once before their first `f5_payload_swap.sh fixture` call.**
   A `.gitignore` entry for it was tried and then reverted in this same finalize pass: it tripped
   `tests/test_live_guards.py::test_t30_gitignore_gained_exactly_the_two_expected_lines`, F2's own
   guard, hardcoded to accept only F2's two specific additions — another other-ticket-owned file
   this ticket must not edit (see Known Issue). Leaving the fixture untracked-and-unignored avoids
   that collision; it will show as `??` in `git status` for anyone with a stale copy on disk,
   which is a minor, known cosmetic cost, not a functional one.

## Deferred Items

- F3's absolute-path leak in `meta.weights_source.path` (Key Decision 6) — belongs to a future F3
  follow-up or a `forecast/build.py` fix, not this ticket.
- A second click on an already-pinned cell leaves `aria-pressed="true"` rather than toggling back
  to `false` (observed at cell 0). Not a failure against F5's stated accessibility acceptance line
  (Tab reaches every cell, Enter pins with `aria-pressed="true"`, no panel strobing on pointer
  sweep — all three confirmed), but worth a look in a later ticket.
- No automated JS test runner exists — by design, per the plan's Non-Goals; DOM behavior is
  verified by browser matrix (agent-browser) instead.
- The page is reachable only at `/forecast.html` directly — no nav link, because `index.html` and
  `overview.html` are frozen per FORECAST-SPEC §3. The other session (main checkout) adds the link
  after its demo. F8's README must say this explicitly.
- **Blocking, not merely deferred:** `tests/test_forecast_api_guards.py`'s F4-owned `OFF_LIMITS`
  guard needs its blanket `"frontend/"` entry narrowed — see Known Issue above. Whoever picks up
  F6 should resolve this before relying on "pytest passes" as a baseline.

## Retrospective

### Worked Well
- Delegating the BANLIST guard's non-vacuity proof to an independent injection pass (not trusting
  the implementing agent's own claim) caught exactly the failure mode this project had shipped
  three times before. Repeat this for every future grep/string-based gate.
- The payload-swap harness's repo-root guard (asserts the resolved path is exactly this worktree)
  meant a script mistake could not have touched the sibling `/Users/sanjaygupta/Projects/Bhar`
  checkout mid-demo, even under time pressure.
- Building the hostile fixture with a *different* zero-weight model than the live payload (NAM vs.
  GFS) forced per-payload computation rather than hardcoding, and caught it before finalize rather
  than after.

### Went Wrong
- During implementation, the conductor twice misjudged a healthy sub-agent as stalled because its
  own `sleep`-based polling never actually blocked — elapsed-time assumptions were wrong, not the
  agent's progress. One of those misjudgments moved a file out from under an agent still writing
  it, costing roughly an hour of recovery. Lesson: never read-modify-write or relocate a file
  another agent owns while it's still writing, and verify elapsed time before acting on an "it's
  stalled" judgment.
- The task brief's own line-number citations for `tokens.css` and the acceptance-floor attribution
  of `best_single_model`/`improvement_pct` to F5 were both wrong (off-by-two and wrong-ticket,
  respectively) — research caught both before they became implementation bugs, but a plan or brief
  should not be trusted for exact citations without a source check.
- **`test-pass.md`'s "977 passed" was true only of the pre-commit tree, and nobody re-ran the
  suite against the actual committed `HEAD` before this finalize pass did.** Two of F5's own new
  diff-gate tests compared base-commit-vs-working-tree, which silently flips from green to
  permanently red the instant the files they check for get committed — the exact moment `/finalize`
  exists to produce. A third, pre-existing test (F4's `OFF_LIMITS` guard) had the same class of bug
  in the other direction: scoped to the whole branch's divergence point instead of its own ticket,
  so it was guaranteed to break the first time any later ticket touched `frontend/`, which
  STATUS.md had already authorized F5 to do. **Lesson: any test that shells out to `git diff` or
  `git status` needs an explicit note on which side of a commit it's meant to run on, and finalize
  must re-run the full suite against the actual post-commit `HEAD` — not trust a pre-commit
  `test-pass.md` number — before reporting green.**

### Process
- Pipeline flow: smooth once research corrected the two premise errors (dark-mode ownership,
  citation line numbers) up front; no rework cycle was needed.
- Task granularity: right — the 21-task/4-stream breakdown let CSS, JS, and the guard test proceed
  in parallel once the HTML skeleton locked the DOM contract.
- Estimate accuracy: guard test (task 1.4) took roughly an hour longer than planned, entirely due
  to the conductor's polling misjudgment above, not the agent's actual work rate.
- Agent delegation: the three `general-purpose` implementation streams (Foundation, CSS, JS) each
  passed on the first delegated attempt; final verification (Stream 4) was pulled back to the
  conductor because delegated agents were running slower than direct verification at that point in
  the session.
