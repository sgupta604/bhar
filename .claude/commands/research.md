---
description: Research a feature — spawns research-agent to gather requirements and context
---

Spawn the **research-agent** for feature: `$ARGUMENTS`

**Normalize feature name** to kebab-case before proceeding.

## Steps
1. Create directory `.claude/features/$ARGUMENTS/` if it doesn't exist
2. Launch a research-agent: "Research feature '$ARGUMENTS'. Read CLAUDE.md and the project's spec/brief docs in `docs/`. Write output to `.claude/features/$ARGUMENTS/`."
3. When agent returns, verify the research doc was created
4. Update `.claude/pipeline/STATUS.md`: feature=`$ARGUMENTS`, phase=`research-complete`, next=`/plan $ARGUMENTS`
5. Give user a 2-3 line summary of findings
6. Suggest: "Research done. Run `/plan $ARGUMENTS`?"

## Expected Output
The agent creates `YYYY-MM-DDTHH:MM:SS_research.md` with: Goal, Requirements (FR/TR), Code Examples, Unverified Assumptions, Affected Code, Patterns to Follow, Risks, Open Questions, Recommended Approach, Scope estimate.

Expect open questions to come back. Answering them is the point of this step, not an interruption.

**Do NOT research it yourself. Spawn the agent.**
