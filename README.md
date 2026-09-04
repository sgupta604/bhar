# Bhar

**Site-Tuned Model Blend** — backtest several NOAA forecast models against observed data at one site, then find the weighted blend that would have had the lowest error there.

See `docs/BRIEF.md` for the full brief: scope, pipeline, demo spec, and open questions.

## Development

This repo uses a Claude Code development pipeline. `CLAUDE.md` and `.claude/` are at the repo root; start Claude Code and it reads `.claude/pipeline/STATUS.md` and prompts you.

## Architecture

```
CLAUDE.md (always in context)
  ↓ user types /research <feature>
.claude/commands/research.md (trigger, ~20 lines)
  ↓ orchestrator spawns
.claude/agents/research-agent.md (brain, fresh context)
  ↓ writes output to
.claude/features/<feature>/2026-09-04T22:00:00_research.md
```

Three layers: CLAUDE.md (always loaded) → Commands (triggers) → Agents (brains in isolated contexts).

## Commands

| Command | What |
|---------|------|
| `/research <feature>` | Gather requirements |
| `/plan <feature>` | Architecture + tasks |
| `/implement <feature>` | Build (delegates to specialists) |
| `/test <feature>` | Full suite + end-to-end verification |
| `/finalize <feature>` | Commit, PR, retrospective |
| `/diagnose <feature>` | Root cause analysis |
| `/quickfix <desc>` | Small fix, no pipeline |
| `/hotfix <desc>` | Urgent fix, skip research |
| `/abort <feature>` | Revert broken implementation, stash changes |
| `/rework <feature>` | Archive approach, reset to research |
| `/park` | Pause current feature |
| `/resume <feature>` | Resume parked feature |
| `/status` | Show pipeline state |

## Agents

### Pipeline (orchestrate WHEN)
| Agent | Model | Purpose |
|-------|-------|---------|
| research-agent | opus | Requirements + code analysis + retrospective review |
| plan-agent | opus | Architecture + task breakdown + contract-first streams |
| execute-agent | opus | Conductor — delegates to specialists, pre-flight checks |
| test-agent | sonnet | Run all suites, verify end to end, handoff |
| finalize-agent | sonnet | Commit, PR, summary, retrospective, ADRs |
| diagnose-agent | opus | Root cause with evidence |

### Specialists (know HOW)
None yet. Execute-agent routes stream work to general-purpose agents briefed from CLAUDE.md until specialists are written. Add one to `.claude/agents/` when a domain's conventions are stable enough to be worth encoding.

## Key Design Decisions

- **Orchestrator dispatches, doesn't code** — handles pipeline state and config; delegates all source code to agents
- **Agents run in fresh contexts** — immune to long-session degradation
- **Contract-first across module boundaries** — shared interfaces locked in a foundation stream before specialists begin
- **Verification-first** — a stream depending on an unconfirmed interface starts with a probe and names a fallback
- **3 tiers:** quickfix (trivial) / hotfix (urgent) / full pipeline (features)
- **Plan + tasks = 1 file** — 3 committed files per feature total
- **Error handling baked in** — max retries, BLOCKED marking, failure routing, `/abort` for recovery
- **Self-check on every agent** — verify before declaring done
- **Retrospective feedback loop** — research-agent reads past "Went Wrong" sections before starting
- **Session continuity** — session-log.md written before suggesting new sessions
- **ARCHITECTURE.md split** — all agents read it when CLAUDE.md outgrows 150 lines
- **Integration test tiers** — unit tests always run, integration tests need network or credentials
- **Diagnosis loop** — `/diagnose` feeds directly into `/plan` for targeted fix cycles
