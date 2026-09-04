---
description: Resume a parked feature — restores state and continues from last phase
---

Resume feature: `$ARGUMENTS`

## Steps
1. Read STATUS.md — find `$ARGUMENTS` in the Parked section
2. If not found → "Feature '$ARGUMENTS' is not parked. Check `/status`."
3. If another feature is currently active → "Active feature exists. Run `/park` first."
4. Move the feature from Parked back to Active in STATUS.md
5. Set Next to the appropriate command based on last phase:
   - research-complete → `/plan $ARGUMENTS`
   - plan-complete → `/implement $ARGUMENTS`
   - implement-complete → `/test $ARGUMENTS`
   - test-pass → `/finalize $ARGUMENTS`
   - test-fail → `/diagnose $ARGUMENTS`
   - diagnosed → `/plan $ARGUMENTS`
6. Report: "Resumed [feature] at phase [phase]. Next: [/command]"
7. Warn: "Note: docs may be stale if other features changed the codebase. The next agent will re-read current code."

Do NOT spawn an agent. Handle this directly.
