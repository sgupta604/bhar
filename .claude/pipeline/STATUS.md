# Pipeline Status

**Updated:** 2026-09-04 11:25 local

## Active

| Field | Value |
|-------|-------|
| Feature | `demo-overview` — GREEN (demo polish) |
| Phase | **DONE** — SPEC backlog + demo-overview all green |
| Next | user click-through, then demo at 16:00. Forecast page: see `docs/FORECAST-SPEC.md` §1 (separate session). |
| Branch | `feat/demo-overview` (off `develop`; remote `github.com/sgupta604/bhar`) |

## Context for a cold session

**Read `docs/SPEC.md` first — it is the contract and it overrides `docs/BRIEF.md`.**
Start at SPEC §16 (cold-start handoff). Verified facts that override the BRIEF live in
`.claude/features/site-tuned-blend/2026-09-04T02-10-00_spike.md`.

Requirements were fully settled in a grilling session on 2026-09-04 ~02:00. **There are no open
questions.** The environment is **already provisioned** and the GRIB path is **already validated
end to end for all four models** — see the spike addendum (F9–F12). Do not re-provision, do not
re-probe, and do NOT trigger the Open-Meteo fallback: the top project risk is retired. The user is asleep, wakes 07:30, leaves 08:15, and **demos at 16:00**.
The loop must not need them — see SPEC §9.

## Ticket backlog (SPEC §8)

| # | Feature | Depends on | Status |
|---|---------|-----------|--------|
| T1 | `project-scaffold` | — | **GREEN** — committed `a487f6c` + `22b7972` |
| T2 | `grib-point-fetch` | T1 | **GREEN** — committed `93a4817` + `4e87789` |
| T3 | `demo-shell` | T1 | **GREEN** — committed `b40b381` + `8c4bf20` + `c957a14` |
| T4 | `data-backfill` | T2 | **GREEN** — committed `46d58c9` + `10b08db` |
| T5 | `score-and-blend` | T4 | **GREEN** — committed `78046e7` + `864c781` |
| T6 | `readme-and-caveats` | T5 | **GREEN** — committed `3710898` + `d657931` + `06d50ec` |

**All six complete. No ticket was ever BLOCKED.** The only interruption was an account-level API
spend limit at ~04:15 that killed T5 and T6 mid-flight; both were resumed from disk at 07:52 and
completed. That is why the 07:30 handoff was missed — not a blocker, and not a broken tree.

## Start the demo

```bash
BHAR_BACKEND_PORT=8011 BHAR_FRONTEND_PORT=5184 ./run.sh
```
Then open the `Frontend:` URL it prints (it carries the `?api=` override). Port 8000 is held by a
VS Code helper that answers `/health` with a byte-identical `{"status":"ok"}` — verify identity
via `/openapi.json`'s title, never `/health`.

## The result, in one paragraph

A blend beats the best single model at all three leads: **+9.02% / +13.82% / +16.51%** at
6h/12h/24h out of sample. **HRRR, not NBM, is the best single model** at every lead. But most of
that gain is **avoiding GFS**, not the fitted weights: an *un-fitted* "drop GFS, average the rest"
blend beats the fitted winner at 12h and is the floor of all 286 vectors at 24h. Fitted weighting
buys a little at 6h and nothing measurable at 12h or 24h. README §1 and §5.1 say this plainly.

## Queue

| Feature | Priority | Notes |
|---------|----------|-------|
| - | - | - |

## Completed

| Feature | Date | PR |
|---------|------|----|
| `project-scaffold` (T1) | 2026-09-04 03:04 | none — no remote (SPEC §8) |
| `grib-point-fetch` (T2) | 2026-09-04 03:19 | none — no remote (SPEC §8) |
| `data-backfill` (T4) | 2026-09-04 03:51 | none — no remote (SPEC §8) |
| `demo-shell` (T3) | 2026-09-04 03:57 | none — no remote (SPEC §8) |
| `score-and-blend` (T5) | 2026-09-04 08:08 | none — no remote (SPEC §8) |
| `readme-and-caveats` (T6) | 2026-09-04 08:10 | none — no remote (SPEC §8) |

## Parked

| Feature | Phase | Reason |
|---------|-------|--------|
| - | - | - |

---

## Post-SPEC work (user awake, 2026-09-04 morning)

| Feature | Branch | State | Commits |
|---|---|---|---|
| `demo-overview` | `feat/demo-overview` | **GREEN** — tests pass, not merged | `fb2dd6e` + `c914d97` |
| `forecast-page` (F1–F8) | not started | spec written, awaiting a session | `6a20257` (spec only) |

**Branch model:** `feat/*` off `develop`, batched into `main`. Remote `origin` =
`https://github.com/sgupta604/bhar.git`. All four branches pushed. `demo-overview` is
deliberately NOT merged — the user decides after the 16:00 demo.

**Start the demo:** `./demo.sh` — auto-selects free ports, verifies it is serving real data,
opens the overview page first. Port 8000 is held by a VS Code helper (PID 1163) that now serves
a "Boreas API" OpenAPI document; identity is always checked via `/openapi.json`'s title, never
`/health`.

**Panic path (verified 12:40):** `git checkout feat/site-tuned-blend && ./demo.sh` restores the
known-good product-page-only demo.

**Forecast page:** `docs/FORECAST-SPEC.md` §1 is the cold-start handoff. F1–F8 with a dependency
graph in §12/§13. Must not modify `frontend/index.html`, `frontend/overview.html`, `app.js`,
`app.css`, `models.js`, `theme.js`, `tokens.css`, `backend/contract.py`, `score/`, or
`data/results.json`.
