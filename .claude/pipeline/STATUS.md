# Pipeline Status

**Updated:** 2026-09-04 19:05 local — F3 finalized

## Active

| Field | Value |
|-------|-------|
| Feature | `forecast-page` (FORECAST-SPEC §12, tickets F1–F9) |
| Phase | F3 done — ready for F4 |
| Next | `/research forecast-api` (F4) |
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

## Ticket backlog (FORECAST-SPEC §12)

| # | Feature | Depends on | Status |
|---|---------|-----------|--------|
| F1 | `forecast-design` | — | DONE — finalized 2026-09-04, no PR (see FORECAST-SPEC §12) |
| F2 | `forecast-live-fetch` | — | GREEN — finalized 2026-09-04, commit `96d0d55`, no PR (FORECAST-SPEC §12) |
| F3 | `forecast-payload` | F2 | GREEN — finalized 2026-09-04, commit `dc97165`, no PR (FORECAST-SPEC §12) |
| F4 | `forecast-api` | F3 | TODO (needs main.py — 2 lines; boundary) |
| F5 | `forecast-page` | F1, F3 | TODO |
| F6 | `forecast-history` | F4, F5 | TODO |
| F7 | `forecast-skill-panel` | F4, F5 | TODO |
| F8 | `forecast-docs` | all | TODO |
| F9 | `forecast-scorecard` | F3, F4 | TODO — **user-approved 11:44**; added on develop @ 37ca272 |

## Completed

| Feature | Date | PR |
|---------|------|----|
| - | - | - |

## Blocked

| Feature | Reason | Tried |
|---------|--------|-------|
| - | - | - |
