---
description: Finalize a feature — spawns finalize-agent for commit, PR, summary with retrospective
---

Spawn the **finalize-agent** for feature: `$ARGUMENTS`

## Preconditions
- Verify `.claude/active-work/$ARGUMENTS/test-pass.md` exists. If not → "Run `/test $ARGUMENTS` first."
- Verify you're on the correct branch (`feat/$ARGUMENTS` or `fix/$ARGUMENTS` or `hotfix/$ARGUMENTS`). If on main/master → "Create and checkout the feature branch first."
- Verify there are uncommitted changes to commit. If clean working tree → "Nothing to finalize. Already committed?"

## Steps
1. Launch a finalize-agent: "Finalize feature '$ARGUMENTS'. Security sweep, write SUMMARY.md with retrospective, commit, create PR, update STATUS.md, clean active-work."
2. When agent returns, report the PR URL and summary to user

## Expected Output
The agent creates `SUMMARY.md` in features/, conventional commit, PR, updates STATUS.md, cleans active-work/.

It runs an **output integrity check** before committing and stops without committing if the feature's output overstates what the evidence supports. That's working as intended.

If no git remote is configured, it commits and reports the PR step as skipped. Not a failure.

**Do NOT finalize it yourself. Spawn the agent.**
