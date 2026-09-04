---
description: Abort current implementation — revert to last clean state
---

Abort the current in-progress work for: `$ARGUMENTS`

Use this when `/implement` produced broken state and you want to start over cleanly.

## Steps
1. Confirm with user: "This will discard uncommitted changes to source files. Continue?"
2. If user confirms:
   - `git stash` (preserves changes in case you need them later)
   - Report the stash ref: "Changes saved as `git stash list` entry. Use `git stash pop` to recover."
3. Clean up `.claude/active-work/$ARGUMENTS/` (delete progress.md)
4. Uncheck any tasks that were checked off in the plan doc during this attempt
5. Update STATUS.md: phase=`plan-complete`, next=`/implement $ARGUMENTS`
6. Report: "Aborted. Implementation reverted to plan-complete state. Run `/implement $ARGUMENTS` to try again, or `/rework $ARGUMENTS` for a different approach."

Do NOT spawn an agent. Handle this directly (it's pipeline state management).

**IMPORTANT:** Never run `git reset --hard` or `git checkout .` without user confirmation. Always `git stash` first so work is recoverable.
