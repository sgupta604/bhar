# Pipeline Status

**Updated:** 2026-09-05 local — F7 finalized

## Active

| Field | Value |
|-------|-------|
| Feature | `forecast-page` (FORECAST-SPEC §12, tickets F1–F9) |
| Phase | F7 GREEN — ready for F9 |
| Next | `/plan forecast-page` (F9 `forecast-scorecard`) — F8 goes last since it documents F9's commands |
| Branch | `feat/forecast-page` (off `develop`) |
| Worktree | **`/Users/sanjaygupta/Projects/Bhar-forecast`** — NOT the main checkout |

## CRITICAL: isolated worktree

The main checkout `/Users/sanjaygupta/Projects/Bhar` is **occupied by another session**
building the 16:00 demo overview page on `feat/demo-overview`. It switched branches under
us at 11:10. All forecast-page work happens in the **worktree** above so the two sessions
cannot collide. `.venv`, `data/*.parquet` and `data/raw` are symlinked back to the main
checkout (they are gitignored and cannot be checked out).

Run everything as `uv run --no-sync ...` from the worktree root.

## Hard boundary — UPDATED 11:44, user cleared it

The user has **lifted** the hold on `frontend/` and `backend/main.py`. F5 may now create
`frontend/forecast.{html,js,css}`; F4 may add its two lines to `backend/main.py`.

**Still off-limits, permanently, by FORECAST-SPEC §3** (not a temporary hold):
`frontend/index.html`, `overview.html`, `app.js`, `app.css`, `models.js`, `theme.js`,
`tokens.css`, `vendor/**`, `backend/contract.py`, `score/**`, `data/results.json`,
`docs/SPEC.md`, `docs/BRIEF.md`, `docs/FORECAST-SPEC.md`. Read-only reuse only.

The 16:00 demo still outranks the forecast page (§16 R4): if a change breaks the demo path,
revert the ticket.

## Rebased onto develop @ 37ca272 (11:43)

Picked up ticket **F9 `forecast-scorecard`** (additive; depends on F3+F4; does not gate F8) and
the **corrected §3 GRIB rule**: assert the *data variable* and `GRIB_cfVarName` are `t2m`;
`GRIB_shortName` is `"2t"` on valid data and must never be compared to `"t2m"`. F1-F8 scope,
acceptance floors and the dependency graph are unchanged.

## Baseline gate (FORECAST-SPEC §1) — verified 11:12

- `uv run --no-sync python -c "import cfgrib, xarray, pandas, pyarrow, fastapi"` → ok
- `uv run --no-sync pytest -q` → **308 passed**
- `uv run --no-sync ruff check .` → clean


## PAUSED 2026-09-04 ~17:25 — cold-resume instructions

The user is ending the day and going offline. Everything is **committed and pushed**; nothing of
value lives only on the laptop.

**State: F1-F6 GREEN and pushed. 1209 tests passing, ruff clean, demo path untouched.**

### To resume, in order

```bash
cd /Users/sanjaygupta/Projects/Bhar-forecast     # the WORKTREE, not ~/Projects/Bhar
git status                                        # expect clean
uv run --no-sync pytest -q                        # expect 1209 passed
```

Then: **`/plan forecast-skill-panel`** -> `/implement` -> `/test` -> `/finalize`, then F8, then F9.

The F7 **research is done and committed**; only the plan was interrupted (stopped cleanly before it
wrote anything, so there is no partial file). **Read `.claude/active-work/forecast-page/session-log.md`
section "F7 - orchestrator decisions" first — six decisions are already settled and must not be
re-litigated.**

### Restarting the servers (the user's view of the page)

```bash
uv run --no-sync uvicorn backend.main:app --port 8021 --log-level warning &
uv run --no-sync python -m http.server 5194 --directory frontend &
```
Open **`http://localhost:5194/forecast.html?api=http://localhost:8021`** — the `?api=` override is
REQUIRED; `forecast.js:29` defaults to port 8000, which is squatted by a VS Code helper.

**Never run `./run.sh` or `./demo.sh` from this worktree** — they call bare `uv run`, and `.venv`
symlinks into the other checkout's venv.

**New CODE needs a server restart; new DATA does not** (F4's seam resolves against the in-memory
module). This cost 45 minutes of confusing 503s during F6.

### Queued work, in priority order

1. **F7** `forecast-skill-panel` — DONE, finalized 2026-09-05. See ticket backlog below for SHA.
2. **QUICKFIX (carried gap): `skill.note` has no value-level §6.2 sweep.** `forecast/contract.py`
   bans the words as *keys* (`:426`) but validates `skill.note` only as non-empty (`:927`). A
   server-authored note reading "we are 95% confident" would pass validation and render verbatim
   into `.skill-basis`. §6.2's ban is meant to be *executable*; for this field it is not.
3. **F9** `forecast-scorecard` — user-approved; mounts on F4's existing router with **zero**
   `backend/main.py` lines. **Now next**, ahead of F8.
4. **F8** `forecast-docs` — must document: the `?api=` override; the code-vs-data restart rule;
   that the page is reachable only at `/forecast.html` (no nav link — `index.html`/`overview.html`
   are frozen, the other session adds the link post-demo); and `--no-sync`. **Goes last**, since it
   documents F9's commands too.

### Open items for the user

- **Nothing is merged to `develop` or `main`.** All nine tickets live on `feat/forecast-page`.
  The single PR opens at the end of F9 (FORECAST-SPEC §12).
- The other session (`bhar-78`) owns `~/Projects/Bhar` and adds the forecast nav link after its
  demo.

## Ticket backlog (FORECAST-SPEC §12)

| # | Feature | Depends on | Status |
|---|---------|-----------|--------|
| F1 | `forecast-design` | — | DONE — finalized 2026-09-04, no PR (see FORECAST-SPEC §12) |
| F2 | `forecast-live-fetch` | — | GREEN — finalized 2026-09-04, commit `96d0d55`, no PR (FORECAST-SPEC §12) |
| F3 | `forecast-payload` | F2 | GREEN — finalized 2026-09-04, commit `dc97165`, no PR (FORECAST-SPEC §12) |
| F4 | `forecast-api` | F3 | GREEN — finalized 2026-09-04, commit `56967fd`, no PR (FORECAST-SPEC §12) |
| F5 | `forecast-page` | F1, F3 | GREEN — finalized 2026-09-04, commit `72f0630`, no PR (FORECAST-SPEC §12) |
| F6 | `forecast-history` | F4, F5 | GREEN — finalized 2026-09-04, commit `27b0f36`, no PR (FORECAST-SPEC §12) |
| F7 | `forecast-skill-panel` | F4, F5, F6 | GREEN — finalized 2026-09-05, commit `951f7f0`, no PR (FORECAST-SPEC §12) |
| F8 | `forecast-docs` | all | TODO |
| F9 | `forecast-scorecard` | F3, F4 | TODO — **user-approved 11:44**; added on develop @ 37ca272 |

## KNOWN ISSUE — RESOLVED (commit `3c83179`, verified again at F6 finalize: 1209 passed, 0 failed)

Original text preserved below for the record.

## KNOWN ISSUE (historical) — full suite is 976 passed / 1 failed, not fully green

Discovered post-commit during F5's finalize, re-running `pytest` against actual `HEAD` (not the
pre-commit tree `test-pass.md` measured). `tests/test_forecast_api_guards.py::test_test10_diff_names_no_off_limits_path`
(F4's guard) fails: its `OFF_LIMITS` tuple has a blanket `"frontend/"` entry and compares against
`branch_point()` (this whole branch's divergence from `develop`), not F4's own commit range. It
was always going to break the first time any ticket added a file under `frontend/` — which is
exactly what the "Hard boundary" section above says F5 was authorized to do. **Not caused by F5's
content.** `tests/test_forecast_api_guards.py` is F4's own guard file (F5's guard file says so
explicitly — "belongs to another ticket") so F5's finalize left it untouched rather than editing
it unilaterally.

**Fix needed before F6 relies on a green baseline:** narrow F4's `OFF_LIMITS` entry from the
blanket `"frontend/"` to the specific paths still actually protected —
`frontend/index.html`, `overview.html`, `app.js`, `app.css`, `models.js`, `theme.js`,
`tokens.css`, `vendor/**` — matching the "Hard boundary" list above, which already excludes
`frontend/forecast.*`. Small, coordinated fix; not a new ticket. Full detail:
`.claude/features/forecast-page-ui/SUMMARY.md`, "Known Issue" section.

## Completed

| Feature | Date | PR |
|---------|------|----|
| - | - | - |

## Blocked

| Feature | Reason | Tried |
|---------|--------|-------|
| - | - | - |
