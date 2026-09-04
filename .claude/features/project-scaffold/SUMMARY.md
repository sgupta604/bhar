# Summary: project-scaffold (T1 of 6)

**Completed:** 2026-09-04 | **Branch:** feat/site-tuned-blend | **PR:** none — no git remote configured; commit only, per SPEC §8

## What Was Built
A declared, reproducible Python 3.12 project on top of the already-provisioned `.venv`: `pyproject.toml` with ten `==`-pinned runtime deps, `uv.lock`, the SPEC §6 repo layout (`fetch/`, `score/`, `backend/`, `frontend/`, `data/`, `tests/`), a 4-test `pytest` suite so the suite exits 0 rather than 5, a `run.sh` that starts backend + frontend with port-conflict detection and orphan-free shutdown, and a populated `CLAUDE.md` Commands block — the only command source `test-agent` reads for all six tickets.

## Files Changed
| Package | File | Change |
|---------|------|--------|
| root | `pyproject.toml` | NEW — `bhar` 0.1.0, 10 pinned deps, `requires-python >=3.12,<3.13`, pytest + ruff config |
| root | `.python-version` | NEW — `3.12`, prevents `uv run` selecting host CPython 3.14.2 |
| root | `uv.lock` | NEW — 40 packages resolved, `uv lock --check` clean |
| root | `run.sh` | NEW — port preflight, orphan-free trap (`pkill -P`), `BHAR_BACKEND_PORT`/`BHAR_FRONTEND_PORT` overrides |
| root | `CLAUDE.md` | MODIFIED — Commands block populated (was an empty TODO stub), one hunk |
| fetch | `fetch/__init__.py` | NEW — empty package, owned by T2/T4 |
| score | `score/__init__.py` | NEW — empty package, owned by T5 |
| backend | `backend/__init__.py`, `backend/main.py` | NEW — 10-line FastAPI health stub, owned by T3 |
| frontend | `frontend/.gitkeep` | NEW — placeholder for T3 |
| data | `data/.gitkeep`, `data/raw/.gitkeep` (untracked) | NEW — output dirs |
| tests | `tests/conftest.py`, `tests/test_scaffold.py`, `tests/fixtures/README.md` | NEW — 4 real tests + fixture provenance rules |

## Tests
- pytest: 4 passing, exit 0 (`4 passed in 0.50s`)
- Build: n/a (Python from source, static frontend, no bundler) | Lint: clean (`ruff check .`) | Types: n/a (no type checker, by decision)
- Env smoke: `import cfgrib, xarray, pandas, pyarrow, fastapi` → ok; Python 3.12.14
- End-to-end: `./run.sh` on free ports serves `/health` and static frontend; SIGINT/SIGTERM leave no orphaned processes; refuses to start (exit 1, names the squatter PID) on a busy default port rather than faking success

## Key Decisions
- Manifest files (`pyproject.toml`, `.python-version`, lockfile) were written directly by the implementing agent rather than delegated — the `.venv` is the one asset whose loss would cost the whole night, and subagents were forbidden from running `uv` concurrently to avoid a race.
- `run.sh` refuses to start on a busy port instead of starting degraded — a backend that silently fails to bind while something else answers `/health` is the worst outcome for a demo.
- Dropped `-q` from `pytest` `addopts`: combined with the documented `uv run pytest -q` command it collapsed to `-qq`, which suppressed the `N passed` summary line the test-agent parses.
- Ports kept at 8000/5173 by default (T3 codes against them); override is the escape hatch, not the default.
- Ruff kept as the lint tool — installed cleanly via the dev group, so the "drop lint" fallback never fired.

## Deferred Items
- `uv run python -m fetch.backfill` and `-m score.run` are forward references in the Commands block; they fail today by design and become true when T4/T5 land. Not a T1 gap.
- No UI smoke check (`agent-browser`) — droppable per SPEC §11 R5; T3 hasn't built frontend content yet for it to render.

## Retrospective

### Worked Well
- Treating a naive `/health` 200 as untrustworthy and re-verifying against `/openapi.json`'s title caught a real false-positive before it reached the commit — exactly the "empty join scores perfectly" failure class CLAUDE.md warns about, just on the demo path instead of a data join.
- Keeping manifest/venv-critical work un-delegated and explicitly forbidding subagents from running `uv` concurrently prevented any risk of a torn or re-synced `.venv` — the single asset that would have been most expensive to lose overnight.
- Documenting deviations with an explicit "planned vs. actual vs. why" table in progress.md made this finalize pass fast — no archaeology needed to understand why `run.sh` or `addopts` differ from the plan.

### Went Wrong
- The plan's `pytest -q` + `addopts = "-q"` combination was never caught until execution — a plan that specifies both a CLI flag and the same flag in config should be checked for flag-stacking before implementation, not after a confusing "tests pass but no summary line" surprise.
- The plan's `run.sh` didn't account for a `uv run` wrapper process orphaning its Python child on kill — any plan involving process lifecycle management under `uv run` should assume a grandchild-process problem by default and test Ctrl-C explicitly, not just the happy path.

### Process
- Pipeline flow: smooth — research → plan → implement → test → finalize ran without a stop condition firing; T1 was scoped tightly enough (declare, don't provision) that no genuine unknown surfaced mid-implementation.
- Task granularity: right — five streams (manifest, layout, tests, commands, verify) matched the natural dependency order and let manifest work stay serialized while layout ran in parallel.
- Estimate accuracy: not tracked in hours for this run (unattended overnight pipeline); no rework or blocked tasks occurred.
- Agent delegation: general-purpose agents handled layout and test-file creation correctly on the first pass; the conductor's direct handling of venv-critical config and final verification avoided a class of errors delegation would have risked (accidental `uv` re-sync, partial venv mutation).
