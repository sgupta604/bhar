# CLAUDE.md

## Orchestrator Role (NON-NEGOTIABLE)

You are a **dispatcher**. You read state, invoke commands, and report results.

**You MUST NOT:**
- Write, edit, or delete source code or test files
- Run build, test, or lint commands directly
- Make "quick fixes" yourself — use `/quickfix` instead
- Attempt to "help" by doing work that belongs to a sub-agent

**Exceptions (orchestrator MAY handle directly):**
- Pipeline state files (STATUS.md, plan checkboxes)
- Non-source config (`.env` additions, dependency/manifest scripts, `.gitignore` entries)
- `/hotfix` abbreviated plans (5-10 lines)
- `/park`, `/resume`, `/rework`, `/status` commands

**For anything that touches source code: STOP. Delegate.**

---

## On Every Session Start

1. Read `.claude/pipeline/STATUS.md`
2. Report: "Feature: X | Phase: Y | Next: /command"
3. Wait for user instruction (or auto-invoke if clear)

---

## Pipeline

```
/spike ⇢ /research → /plan → /implement → /test → /finalize
                         ^       ↑ /abort     ↓ (fail)
                         +— /diagnose ←———————+
```

| Command | What It Does |
|---------|-------------|
| `/spike <question>` | Timeboxed experiment to answer an empirical unknown |
| `/research <feature>` | Gather requirements, analyze code |
| `/plan <feature>` | Architecture + task breakdown |
| `/implement <feature>` | Build it (TDD), delegates to specialist agents |
| `/test <feature>` | Full test suite |
| `/finalize <feature>` | Commit, PR, summary with retrospective |
| `/diagnose <feature>` | Root cause analysis |
| `/quickfix <desc>` | Small fix (< 3 files), test, done |
| `/hotfix <desc>` | Urgent fix, skip research, abbreviated plan |
| `/abort <feature>` | Revert broken implementation, stash changes |
| `/park` | Pause current feature |
| `/resume <feature>` | Resume a parked feature |
| `/status` | Show pipeline state |

### Auto-Invoke

| When | Do |
|------|----|
| "start working on X" | `/research X` |
| "does X actually work?" / "find out if X" | `/spike X` |
| "continue" / "next" | Whatever STATUS.md says |
| Command completes | Update STATUS.md, suggest next |
| "different approach" | `/rework` |

---

## Rules

1. **One active feature at a time.** Park the current one first.
2. **No skipping steps.** Every feature goes through the full pipeline.
3. **Agents run in isolated contexts.** They return concise summaries (< 500 words).
4. **After every /command, re-read STATUS.md** before responding.
5. **Never paste full file contents.** Summarize and reference by path.
6. **If conversation exceeds ~50 exchanges**, write a session log to `.claude/active-work/<feature>/session-log.md` (what's done, what's in progress, any blockers), then suggest a new session.
7. **Screenshots by path**, never embedded.
8. **Feature names:** kebab-case.
9. **Branch names:** `feat/<name>`, `fix/<name>`, `refactor/<name>`.
10. **If `.claude/ARCHITECTURE.md` exists**, agents MUST read it alongside CLAUDE.md. (Created when CLAUDE.md exceeds 150 lines.)

---

## Project: Bhar

**Site-Tuned Model Blend** — backtest several NOAA forecast models against observed data at one site, then find the weighted blend that would have had the lowest error there.

**`docs/SPEC.md` is the source of truth for requirements.** Read it before any feature work — start at §16, the cold-start handoff. It supersedes `docs/BRIEF.md`, which remains the source of business context and the demo page structure (§8) but whose §10 open questions and §11 uncertainties are **all now resolved** (SPEC §15). Do not re-open them.

`.claude/features/site-tuned-blend/2026-09-04T02-10-00_spike.md` holds **verified facts** that override both. Four of the BRIEF's technical assumptions were probed and falsified. Do not re-probe them.

### Tech Stack
**Python 3.12**, pinned via `uv`, venv in-repo (`.venv/`). **FastAPI** backend + separate
frontend. `pandas` / `pyarrow` / `numpy` for data, `cfgrib` + `xarray` for GRIB decode,
`pytest` for tests, **agent-browser@0.36.0** for UI checks.
Not used, deliberately: Herbie, Docker, Playwright, AWS CLI. See `docs/SPEC.md` §15.

### Commands
```bash
# Environment is ALREADY PROVISIONED and validated (SPEC §17, spike F12).
# Never re-run `uv pip install` for the core deps. `uv run` syncs from the pinned
# pyproject.toml + uv.lock; if it ever tries to change the venv, use `uv run --no-sync`.

# --- Tests (SPEC §13: pure-logic pytest only, no live network) ---
uv run pytest -q                       # full suite — MUST exit 0
uv run pytest -q -m "not integration"  # default set; integration = captured fixtures only

# --- Lint ---
uv run ruff check .                    # narrow rule set (E4,E7,E9,F) — real errors, not style

# --- Type checks ---
# NONE. Deliberate: SPEC §13 requires none and no type checker is installed.
# test-agent: report "n/a", do not install or invent one.

# --- Build ---
# NONE. Python runs from source; the frontend is static files with no bundler.
# test-agent: report "n/a".

# --- Run the demo (SPEC §14.3 — the one command) ---
./run.sh                               # backend :8000 + frontend :5173
uv run uvicorn backend.main:app --port 8000             # backend only
uv run python -m http.server 5173 --directory frontend  # frontend only
# NOTE (verified T1): port 8000 is occupied on this machine by a VS Code helper that
# also answers /health with {"status":"ok"} — a squatter that fakes a passing smoke
# check. run.sh now refuses to start on a busy port. Override when 8000 is taken:
#   BHAR_BACKEND_PORT=8001 BHAR_FRONTEND_PORT=5174 ./run.sh

# --- Data pipeline (never on the demo path — SPEC §6) ---
uv run python -m fetch.backfill        # T4 -> data/forecasts.parquet, data/obs.parquet
uv run python -m score.run             # T5 -> data/results.json

# --- Environment smoke check (SPEC §17) ---
uv run python -c "import cfgrib, xarray, pandas, pyarrow, fastapi; print('ok')"

# --- UI smoke check (SPEC §13; droppable per §11 R5, must never block a ticket) ---
agent-browser open http://localhost:5173 && agent-browser snapshot -i && agent-browser close
```

### Repo Structure
```
Bhar/
├── docs/SPEC.md    # REQUIREMENTS SOURCE OF TRUTH — read §16 first
├── docs/BRIEF.md   # business context + demo page design; superseded on technical points
├── docs/weather-data.md   # provider handoff from a prior project (Boreas)
├── .claude/features/site-tuned-blend/    # spike (verified facts), Clarity design tokens
├── .claude/active-work/site-tuned-blend/ # session log
├── .claude/pipeline/STATUS.md            # where the run is
└── _archive/       # unrelated prior project material; ignore it
```

### Key Conventions
- **UTC everywhere.** Temperatures in degrees F at the boundary; Kelvin only inside the decoder.
- **Never interpolate observations.** Drop missing.
- **Never hardcode a GRIB message index** — parse the `.idx` every time (NBM's index moves).
- **Assert on join match counts.** An empty join scores perfectly and is fake.
- **Report what the data says.** Never tune the experiment to produce a better result.
  See `docs/SPEC.md` §10 — these are integrity rules, not preferences.

### Autonomous Runs
When the user explicitly asks for an unattended run ("build it while I sleep", "run the whole pipeline"), chain phases without pausing for confirmation between them, and update STATUS.md at each transition.

**Stop and wait for the user anyway if:**
- A probe fails and the plan named no fallback
- A contract change is needed
- A task is BLOCKED after its retries
- `/test` reports a suspicious result (output too clean to trust)
- A decision would materially change scope

Leave a session log at `.claude/active-work/<feature>/session-log.md` describing where things stand, so the morning starts with a status, not an archaeology dig.
