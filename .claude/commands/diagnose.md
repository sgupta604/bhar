---
description: Diagnose test failures — spawns diagnose-agent for root cause analysis
---

Spawn the **diagnose-agent** for feature: `$ARGUMENTS`

## Prerequisites
Verify `.claude/active-work/$ARGUMENTS/test-fail.md` exists. If not → "Run `/test $ARGUMENTS` first."

## Steps
1. Launch a diagnose-agent: "Diagnose failures for '$ARGUMENTS'. Read test-fail.md and progress.md. Find root causes with evidence. Write diagnosis to `.claude/active-work/$ARGUMENTS/`."
2. When agent returns, update STATUS.md: phase=`diagnosed`, next=`/plan $ARGUMENTS`
3. Give user summary of root causes and proposed fixes (with effort)
4. Suggest: "Diagnosis done. Run `/plan $ARGUMENTS` to create a fix plan?"

## Expected Output
`diagnosis.md` with: Failures (symptom, root cause, evidence), Fix Plan (file, change, effort, agent), Prevention notes.

**Do NOT diagnose it yourself. Spawn the agent.**
