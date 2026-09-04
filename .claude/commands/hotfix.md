---
description: Hotfix — urgent fix with clear requirements, skip research, abbreviated plan
---

Handle a **hotfix** for: `$ARGUMENTS`

Hotfixes skip `/research` and use an abbreviated plan. Requirements are provided inline by the user.

## Steps
1. Create branch `hotfix/$ARGUMENTS`
2. Create an abbreviated plan inline (no research doc needed):
   - Write a minimal plan doc to `.claude/features/$ARGUMENTS/YYYY-MM-DDTHH:MM:SS_plan.md` with just the task(s) and acceptance criteria
3. Update STATUS.md: feature=`$ARGUMENTS`, phase=`plan-complete`, next=`/implement $ARGUMENTS`
4. Suggest: "Hotfix plan ready. Run `/implement $ARGUMENTS`?"

The rest of the pipeline (`/implement → /test → /finalize`) runs normally. Hotfixes still get tested and finalized.

**You may write the abbreviated plan yourself** (this is the ONE exception to the dispatch rule — hotfix plans are 5-10 lines).
