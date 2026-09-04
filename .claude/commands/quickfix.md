---
description: Quick fix — spawns agent for small targeted changes (< 3 files, no pipeline)
---

Spawn a **general-purpose agent** for: `$ARGUMENTS`

## Steps
1. Launch agent: "Quick fix: '$ARGUMENTS'. Verify this is small (< 3 files), obvious, and low-risk. If not, STOP and say 'needs full pipeline'. If yes, fix it, run the project's tests and lint from CLAUDE.md, report results."
2. When agent returns:
   - **Done:** Report changes and test results. Offer to commit.
   - **Too complex:** Suggest `/research` instead.

Quick fixes do NOT update STATUS.md or create feature docs. The commit message is the record.

**Do NOT make the fix yourself. Spawn the agent.**
