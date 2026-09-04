---
description: Test a feature — spawns test-agent for full suite + end-to-end verification + handoff checklist
---

Spawn the **test-agent** for feature: `$ARGUMENTS`

## Preconditions
- Verify `.claude/active-work/$ARGUMENTS/progress.md` exists. If not → "Run `/implement $ARGUMENTS` first."
- Verify the plan doc has checked-off tasks. If all tasks are unchecked → "Implementation doesn't appear complete. Run `/implement $ARGUMENTS` first."
- If `.claude/active-work/$ARGUMENTS/session-log.md` exists, include it in the agent prompt for context.

## Steps
1. Launch a test-agent: "Test feature '$ARGUMENTS'. Run the project's test, lint, type and build commands from CLAUDE.md, then verify end to end. Walk the handoff checklist in the plan doc. Write report to `.claude/active-work/$ARGUMENTS/`."
2. When agent returns:
   - **PASS:** Update STATUS.md: phase=`test-pass`, next=`/finalize $ARGUMENTS`. Suggest: "Tests passed! Run `/finalize $ARGUMENTS`?"
   - **FAIL:** Update STATUS.md: phase=`test-fail`, next=`/diagnose $ARGUMENTS`. Suggest: "Tests failed. Run `/diagnose $ARGUMENTS`?"
3. Give user the pass/fail summary with test counts

## Expected Output
**Pass:** `test-pass.md` with results table, build/lint status, end-to-end checks, handoff checklist verified.
**Fail:** `test-fail.md` with failures table, failure categories, environment issues separated from code failures, and recommendation.

The agent also flags **suspiciously clean results** as suspected failures. Treat those like any other failure.

**Do NOT run tests yourself. Spawn the agent.**
