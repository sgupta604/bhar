# Pipeline Status

**Updated:** 2026-09-04 03:53 local

## Active

| Field | Value |
|-------|-------|
| Feature | `score-and-blend` (T5 of 6) |
| Phase | T3 `test` / T4 `test` / T5 `research` |
| Next | finalize T3 + T4, then `/plan score-and-blend` |
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
| T3 | `demo-shell` | T1 | IN PROGRESS — test (committed `b40b381` + `8c4bf20`) |
| T4 | `data-backfill` | T2 | IN PROGRESS — test (committed `46d58c9`) |
| T5 | `score-and-blend` | T4 | IN PROGRESS — research |
| T6 | `readme-and-caveats` | T5 | not started |

T3 is independent of the data path. If T2 blocks, T3 still runs — log the blocker and move on.

## Queue

| Feature | Priority | Notes |
|---------|----------|-------|
| - | - | - |

## Completed

| Feature | Date | PR |
|---------|------|----|
| `project-scaffold` (T1) | 2026-09-04 03:04 | none — no remote (SPEC §8) |
| `grib-point-fetch` (T2) | 2026-09-04 03:48 | none — no remote (SPEC §8) |

## Parked

| Feature | Phase | Reason |
|---------|-------|--------|
| - | - | - |
