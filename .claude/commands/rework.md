---
description: Rework a feature — archive current approach and reset to research
---

Rework feature: `$ARGUMENTS`

## Steps
1. Read STATUS.md for current feature state
2. Rename current plan to `*_abandoned.md` in `.claude/features/$ARGUMENTS/`
3. Create brief note in `.claude/active-work/$ARGUMENTS/rework.md`:
   - What approach was tried
   - Why it's being abandoned (ask user)
   - New direction (ask user)
4. Update STATUS.md: phase=`rework`, next=`/research $ARGUMENTS`
5. Tell user: "Old approach archived. Run `/research $ARGUMENTS` with the new direction?"

Keep the research doc — requirements usually still apply. Only the approach changes.

Do NOT spawn an agent. Handle this directly.
