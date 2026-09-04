# Summary: forecast-api (F4)

**Completed:** 2026-09-04 | **Branch:** feat/forecast-page | **PR:** none yet — one PR opens at the end of F9 (FORECAST-SPEC §12)

## What Was Built

Three read-only GET endpoints (`/api/forecast`, `/api/forecast/skill`, `/api/forecast/history`) on
a new `APIRouter` in `backend/forecast_api.py`, mounted into `backend/main.py` with exactly two
added lines. Every request re-reads and re-validates the underlying JSON via
`forecast/contract.py` — never a cached or stale document. Every failure mode returns 503 with a
named reason (missing file, invalid JSON, contract violation, missing validator) — never an
empty-but-well-formed payload and never a silent fallback to a fixture. This is the first-ever
test coverage of `backend/main.py` itself.

## Files Changed

| Package | File | Change |
|---------|------|--------|
| backend | `backend/forecast_api.py` | NEW, 220 lines. `router`, `FORECAST_PATH`/`HISTORY_PATH`, named 503 detail constants, `_load_forecast()`, lazy `_history_validator()`, 3 GET handlers |
| backend | `backend/main.py` | +2 / -0 lines only: one import, one `include_router` |
| tests | `tests/test_forecast_api.py` | NEW, 677 lines — behavioral tests (200/503 paths, CORS, no-real-file independence, revalidation) |
| tests | `tests/test_forecast_api_guards.py` | NEW, 621 lines — source-scan guards (no HTTP client, no archive URL literal, no bare assert, no write route, no return annotation) + the two-line diff gate |

## Tests

- Full suite: `uv run --no-sync pytest -q` → **828 passed**, exit 0 (759 baseline + 60 F4 + 9 added by the post-audit quickfix described below)
- Lint: `ruff check .` clean
- Types: n/a (none installed, per CLAUDE.md)
- Build: n/a (no bundler)
- `git diff --numstat 740dfb0 -- backend/main.py` → `2 0`, confirmed
- Off-limits diff (`fetch/ score/ frontend/ docs/ run.sh demo.sh .gitignore backend/contract.py forecast/ tests/test_live_guards.py`) → empty, confirmed
- `data/results.json` → byte-identical, confirmed via `git status --porcelain`

## Key Decisions

- **Named 503, never a silent fallback.** Independently proven three ways: `forecast.json` moved
  aside with a *valid* fixture sitting beside it → still 503 (no accidental serving of the
  fixture); corrupted JSON → 503; file restored → 200 on the very next request, no server
  restart. Each failure carries a distinct, file-naming detail string.
- **The F6 seam is `forecast.contract.load_and_validate_history(path) -> dict`**, resolved
  *lazily* via `getattr` on the imported module object (never `from ... import`, which would
  freeze the lookup at import time and hide a function added later). F6 lights up
  `/api/forecast/history` by adding that one function to `forecast/contract.py` — **zero edits
  to `backend/forecast_api.py`**. Missing file → 503; file present but validator absent → 503
  ("an unvalidated history payload is never served").
- **`FORECAST_PATH`/`HISTORY_PATH` module constants are the only seam** — no env vars, no
  `Depends` overrides. Proven independent of the real file: `data/forecast.json` was moved to
  `/tmp` and all 60 F4 tests still passed.
- **`router` is a clean module-level name** so F9 can mount its scorecard here with zero
  `main.py` lines.
- **Python 3.12 f-string tokenization note carried forward**: `f"https://{bucket}.s3…"`
  normalizes with injected whitespace between scheme and host, so any future source-literal scan
  needs a whitespace-tolerant gap in its regex, not an exact match.

## Deferred Items

- `/api/forecast/history` correctly 503s today — `data/forecast_history.json` does not exist yet
  and there is no live history data. This is F6's deliverable, not a gap in F4.
- Frontend consumption of these endpoints is F5's scope. No UI was built or touched here.

## Report/Reality Mismatch — Caught and Corrected

The implementer's `progress.md` asserted: *"an AST check confirms all three handlers carry no
return annotation."* **No such test existed at implementation time.** test-agent caught this not
by trusting the sentence but by grepping the test files for `annotation`, `.returns`,
`response_model`, and `inspect.signature` and finding nothing that matched. The only
AST/`.returns`-adjacent code in the guard file at that point (`route_decorator_methods`)
extracted HTTP verbs from decorators — it did not inspect return annotations at all.

The underlying fact was true (no handler in `backend/forecast_api.py` carried `-> dict`), but it
was **unguarded** — nothing in the suite would have caught a future regression. This mattered
because a `-> dict` on a FastAPI route handler triggers a pydantic `response_model`
serialization pass that can silently reshape or drop keys from a document `forecast/contract.py`
had just certified — defeating the certification.

A follow-up quickfix, applied before this finalize, closed the gap for real:
`route_handler_decorators()` walks the AST for `@router.<verb>(...)` / `@app.<verb>(...)`
decorators, and `annotated_route_handlers()` filters those to ones with a non-`None`
`node.returns`. Three tests now guard it: an on-disk assertion
(`test_test9_no_return_annotation_on_a_forecast_api_route_handler`) that the current three
handlers carry none, a fires-on-a-bad-sample parametrized test with 4 synthetic cases (sync,
async, multi-line decorator, `@app.get`), and a stays-silent-on-clean parametrized test with 4
cases — including the legitimately-annotated non-route helper `_load_forecast() -> dict`, so the
guard cannot be satisfied by simply banning all return annotations. Full suite grew from 819 to
828 passing as a result.

**The lesson, stated for the retrospective log: a claim that a guard exists is not a guard.**
Verify by grepping for the guard's actual mechanism, not by trusting the sentence describing it.

## Retrospective

### Worked Well
- Parallel implementation streams with disjoint file ownership (behavioral tests vs. guard
  tests) avoided any merge conflict in a single shared worktree.
- The lazy `getattr`-based validator resolution is a genuinely clean seam — F6 can add one
  function to an unrelated file and light up a whole endpoint with no edits to this ticket's
  code.
- Independent verification (moving/corrupting the real file against a *running* server, not just
  the test suite) caught the "no restart needed" and "fixture doesn't leak" claims for real,
  not just in mocked test fixtures.

### Went Wrong
- The implementer wrote a specific, checkable claim ("an AST check confirms...") into
  `progress.md` without the check existing. This is worse than an unverified vague claim because
  its specificity reads as evidence. The lesson: a report claiming a guard exists must name the
  guard's location (file, test name) so it can be checked in ten seconds — anything less is an
  assertion, not a fact.
- The diff-gate base (`git merge-base HEAD develop` vs. a pinned commit) was ambiguous in the
  plan and had to be resolved mid-implementation; the plan should have pinned the base commit
  explicitly given prior tickets (F2, F3) were already shipped on the branch.

### Process
- Pipeline flow: smooth, aside from the one caught overstatement — test-agent's job worked
  exactly as intended.
- Task granularity: right — foundation/core/history/guards/hardening split allowed real
  parallelism without contract drift.
- Estimate accuracy: 60 new tests planned and delivered exactly; +9 more added post-audit for
  the missing guard, landing at 828 total (not estimated in the original plan, but small).
- Agent delegation: general-purpose streams worked well for both behavioral and guard-scan test
  code; the test-agent's skepticism (grep for the actual mechanism rather than trust the
  sentence) is the single most valuable step in this ticket's whole pipeline run.
