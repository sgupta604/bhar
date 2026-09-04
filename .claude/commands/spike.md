---
description: Spike — timeboxed experiment to answer an empirical question. Throwaway code, findings doc, no tests.
---

Spawn a **general-purpose agent** to run a spike on: `$ARGUMENTS`

Use this when a question can only be answered by running code — does this API exist, does it return what the spec claims, is this identifier right, is this fast enough. `/research` reads docs and code; a spike goes and finds out.

## When to spike
- The research doc listed an Unverified Assumption and planning is blocked on it
- The spec sketched an API signature from memory
- An external service's behavior is unknown (does it serve archived data? what's the actual response shape?)
- You need a rough sense of cost — download size, runtime, rate limits

## Steps
1. Ask the user for a timebox if they didn't give one. Default **30 minutes**.
2. Launch the agent:
   "Spike: '$ARGUMENTS'. Timebox: [N] minutes. Answer the question empirically — write throwaway code, run it, observe. Scratch code goes in `spikes/` (gitignored). Do NOT write tests, do NOT touch `src/`, do NOT build the real implementation. Write findings to `.claude/features/<feature>/YYYY-MM-DDTHH:MM:SS_spike.md`. If you hit the timebox without an answer, say so and report what you ruled out — that's a valid result."
3. When the agent returns, report the findings and what they unblock
4. Update STATUS.md: note the spike under the active feature; phase is unchanged
5. Suggest the next step — usually `/research` or `/plan`, now that the unknown is resolved

## Expected Output
`YYYY-MM-DDTHH:MM:SS_spike.md`:

```markdown
# Spike: [question]

**Date:** ... | **Timebox:** N min | **Answer:** YES / NO / PARTIAL / INCONCLUSIVE

## Question
[what we needed to know, and what it blocks]

## What I Did
[the minimum experiment, and how to re-run it]

## Findings
- [observed fact, with the evidence — actual response, actual signature, actual timing]

## Actual vs Assumed
| Assumed | Actual |
|---------|--------|

## Recommendation
[which path this unblocks, or what to try next if inconclusive]

## Throwaway Code
`spikes/[file]` — not production, not tested, delete when done
```

## Rules
- **Findings are the deliverable. Code is exhaust.** Spike code never graduates to `src/` — the real implementation gets written properly through the pipeline.
- **Respect the timebox.** "I couldn't confirm it in 30 minutes" is a real answer that changes the plan.
- **Report what you actually observed**, not what you expected. Paste the real response shape, the real signature, the real error.
- **Inconclusive is allowed. Guessing is not.**

**Do NOT run the spike yourself. Spawn the agent.**
