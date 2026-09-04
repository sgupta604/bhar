# Pipeline Workflow

## Flow

```
/spike ⇢ /research → /plan → /implement → /test → /finalize
                         ^       ↑ /abort     ↓ (fail)
                         +— /diagnose ←———————+
```

`/spike` is optional and sits before or alongside research — use it whenever an unknown is empirical rather than documentary.

## Phases

### 1. Research → research-agent
**Writes:** `.claude/features/<feature>/YYYY-MM-DDTHH:MM:SS_research.md`

Six phases: gather context → extract requirements → analyze code → identify risks → resolve questions → recommend approach. Includes "Patterns to Follow", "Code Examples from Spec" and "Unverified Assumptions" in output.

**Exit gate:** FRs/TRs listed, affected files identified, unverified assumptions flagged, risks assessed, approach recommended.

### 2. Plan → plan-agent
**Writes:** `.claude/features/<feature>/YYYY-MM-DDTHH:MM:SS_plan.md` (includes tasks)

Architecture + task breakdown in ONE file. Tasks organized by streams with [P] markers. Each task has "Accepts when" criteria. Includes handoff checklist for test agent.

**Exit gate:** Architecture described, files listed, every task has acceptance criteria, non-goals stated.

### 3. Implement → execute-agent (delegates to frontend-agent / backend-agent)
**Writes:** `.claude/active-work/<feature>/progress.md`, checks off tasks in plan doc

Execute-agent is a **conductor**. It reads the plan and routes each stream by its Task Index **Agent** column:
- A specialist that exists in `.claude/agents/` → spawned
- A specialist that doesn't exist yet → general-purpose agent, briefed with the conventions from CLAUDE.md
- Marked `-`, or cross-cutting → execute-agent handles directly

**Error handling:** Max 2 retries per task. If still failing, mark BLOCKED, continue with non-dependent tasks.

**Exit gate:** All tasks checked off (or BLOCKED with documented reason), lint clean, tests pass.

### 4. Test → test-agent
**Writes:** `.claude/active-work/<feature>/test-pass.md` or `test-fail.md`

Runs the project's test, lint, type and build commands (from CLAUDE.md), then verifies end to end. Walks handoff checklist.

**Evidence rules:** Save failure artifacts to the project's output directory. Reference by path. Don't embed. Don't clean up failures — they're evidence for /diagnose.

**Exit gate (pass):** All suites pass, build succeeds, lint/types clean, checklist verified, no suspiciously clean results left unexplained.

### 5a. Finalize → finalize-agent
**Writes:** `.claude/features/<feature>/SUMMARY.md` (includes retrospective)

Cleanup → commit → PR → update STATUS.md → clean active-work/. Security checklist: no secrets, no debug code, no TODO hacks. Only 3 committed files per feature (research, plan, summary).

### 5b. Diagnose → diagnose-agent
**Writes:** `.claude/active-work/<feature>/diagnosis.md` (versioned: v2, v3...)

Root causes with evidence. Fix plan with effort estimates. Loops back to /plan.

## Alternative Paths

### Spike (`/spike`)
Timeboxed experiment answering a question that can only be settled by running code — does this API exist, does it return what the spec claims, is this identifier right.

- **Findings are the deliverable**, code is exhaust. Scratch code lives in `spikes/` (gitignored) and never graduates to `src/`.
- No tests, no production code, no pipeline state change beyond a note on the active feature.
- Writes `.claude/features/<feature>/YYYY-MM-DDTHH:MM:SS_spike.md`.
- Feeds `/research` (or `/plan` directly, if research is already done and only this was blocking).
- Inconclusive within the timebox is a valid result — it changes the plan.

### Quick Fix (`/quickfix`)
< 3 files, obvious cause, low risk. Agent fixes + tests. No docs. If complex → recommends full pipeline.

### Hotfix (`/hotfix`)
Urgent production fix with clear requirements:
- **Skip** `/research` (requirements provided inline)
- **Abbreviated** `/plan` (can be a single task, inline in command)
- `/implement` → `/test` → `/finalize` still required
- Creates a hotfix branch: `hotfix/<name>`

### Park (`/park`)
Saves current state to STATUS.md. Active-work/ preserved. New feature can start.

### Resume (`/resume <feature>`)
Reads STATUS.md for last phase. Resumes from there. Re-reads docs (may be stale).

### Abort (`/abort`)
If `/implement` produced broken state and you want to start over:
1. `git stash` (preserves work, recoverable)
2. Cleans active-work/, unchecks tasks in plan
3. Resets to `plan-complete` — run `/implement` again or `/rework` for new approach

### Rework
Archives current plan as `*_abandoned.md`. Resets to /research. Old research kept.

## Infrastructure Rules

### Feature Names
Kebab-case, normalized. `user-auth` not `user-authentication`. The orchestrator normalizes before passing to agents.

### "Latest File" Resolution
Sort `*_plan.md` or `*_research.md` lexicographically (ISO 8601 timestamps with zero-padded hours). Last entry = latest.

### Branch Naming
`feat/<feature-name>`, `fix/<feature-name>`, `hotfix/<feature-name>`, `refactor/<feature-name>`.

### CLAUDE.md Growth Strategy
When CLAUDE.md exceeds 150 lines, move architecture details to `.claude/ARCHITECTURE.md` and reference it from CLAUDE.md. Keep CLAUDE.md focused on pipeline rules + essential project context.

### Commit Messages
Conventional commits, scoped to the module:
`feat(<scope>): <description>`
`fix(<scope>): <description>`
`test(<scope>): <description>`

## File Lifecycle

### Per Feature (committed)
```
.claude/features/<feature>/
  YYYY-MM-DDTHH:MM:SS_spike.md      (zero or more, optional)
  YYYY-MM-DDTHH:MM:SS_research.md
  YYYY-MM-DDTHH:MM:SS_plan.md
  SUMMARY.md
```

### Retrospective Rollup (committed)
`.claude/pipeline/RETROSPECTIVES.md` — finalize-agent appends one line per feature. research-agent reads this single file instead of globbing every SUMMARY.md, so the feedback loop keeps working as the feature count grows.

### Working Files (gitignored, cleaned after finalize)
```
.claude/active-work/<feature>/
  progress.md, test-pass.md, test-fail.md, diagnosis.md
```

## Worktree Safety
- Max 2 parallel worktrees
- Never branch from HEAD with uncommitted changes
- Use git merge, not file copying
- Run full tests after merge
- Parallel streams must not touch same files

## Specialist Agents

The pipeline agents (research, plan, execute, test, finalize, diagnose) orchestrate **when**. Specialist agents know **how** for one area of a specific codebase.

None are defined yet. Until they are, execute-agent routes stream work to general-purpose agents briefed from CLAUDE.md — which works, but they re-derive the project's conventions every time.

Add a specialist when a domain has accumulated enough hard-won specifics (stack conventions, API gotchas, testing patterns) that repeating them in every task prompt is wasteful. Write it to `.claude/agents/<name>-agent.md`, then name it in the plan's Task Index Agent column and execute-agent will spawn it.

## Agent Output Rules
1. Concise — summaries under 500 words
2. Reference by path — don't paste code blocks
3. Signal over noise — only info that helps the next phase
4. Screenshots by path — never inline
5. Omit empty sections
6. Each agent writes ONE output file (plus checking off tasks)
