# Pipeline Status

**Updated:** 2026-09-04 08:10 local — **RUN COMPLETE, ALL SIX TICKETS GREEN**

## Active

| Field | Value |
|-------|-------|
| Feature | — (none active; backlog complete) |
| Phase | **DONE** — all six tickets green and committed |
| Next | nothing queued. Demo at 16:00. SPEC §9 stop condition reached. |
| Branch | `feat/site-tuned-blend` |

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
