---
description: Plan a feature — spawns plan-agent for architecture and task breakdown
---

Spawn the **plan-agent** for feature: `$ARGUMENTS`

## Prerequisites
Verify `.claude/features/$ARGUMENTS/*_research.md` exists. If not → "Run `/research $ARGUMENTS` first."

## Steps
1. Check if `.claude/active-work/$ARGUMENTS/diagnosis.md` exists (fix cycle). If so, include it in the agent prompt.
2. Launch a plan-agent: "Plan feature '$ARGUMENTS'. Read the latest research doc and CLAUDE.md. **If `.claude/active-work/$ARGUMENTS/diagnosis.md` exists, read it — this is a fix cycle, not a greenfield plan. Focus tasks on the fixes proposed in the diagnosis.** Write plan to `.claude/features/$ARGUMENTS/`."
3. When agent returns, verify the plan doc was created with tasks
4. Update `.claude/pipeline/STATUS.md`: phase=`plan-complete`, next=`/implement $ARGUMENTS`
5. Give user a 2-3 line summary (streams, effort estimate, key decisions)
6. Suggest: "Plan done. Run `/implement $ARGUMENTS`?"

## Expected Output
The agent creates `YYYY-MM-DDTHH:MM:SS_plan.md` with: Architecture, File Changes, Tasks (organized by stream with agent routing), Handoff Checklist, Non-Goals.

**Do NOT plan it yourself. Spawn the agent.**
