---
description: Implement a feature — spawns execute-agent which delegates to frontend/backend agents
---

Spawn the **execute-agent** for feature: `$ARGUMENTS`

## Prerequisites
Verify `.claude/features/$ARGUMENTS/*_plan.md` exists. If not → "Run `/plan $ARGUMENTS` first."

## Steps
1. Launch an execute-agent: "Implement feature '$ARGUMENTS'. Read the latest plan doc and CLAUDE.md. Delegate each stream to the agent named in the plan's Task Index; handle streams marked `-` directly. Run probe tasks before the streams they gate. Follow TDD. Check off tasks as you complete them."
2. When agent returns, verify progress.md was created and tasks are checked off
3. Update `.claude/pipeline/STATUS.md`: phase=`implement-complete`, next=`/test $ARGUMENTS`
4. Give user a 2-3 line summary (what was built, test results, any blocked tasks)
5. Suggest: "Implementation done. Run `/test $ARGUMENTS`?"

## Expected Output
The agent checks off tasks in the plan doc and creates `.claude/active-work/$ARGUMENTS/progress.md` with: Changes table, Delegation log, Reality Check, Blocked tasks (if any), Final test/lint state.

**Do NOT implement it yourself. Spawn the agent.**
