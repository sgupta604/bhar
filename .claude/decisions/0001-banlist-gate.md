# ADR-0001: BANLIST block + strip-then-grep gate for banned identifiers

**Status:** Accepted
**Date:** 2026-09-04

## Context
FORECAST-SPEC §6.2 bans a list of statistical-confidence identifiers (`confidence`,
`probability`, `p10`/`p50`/`p90`, `error_bar`, `ci_low`, `ci_high`, `uncertainty`, `±`, …) from
the forecast page — the product must never claim calibrated confidence it hasn't earned. F1's
deliverable (`design-target.md`) has to *define* those banned terms so implementers and
reviewers know exactly what is prohibited and why. A document that both defines and forbids a
word necessarily contains that word. A naive `grep -v` gate over the whole file would therefore
either (a) always fail, because the definition section trips it, or (b) be weakened to the point
of being useless. Ticket F1 also required proof that the gate isn't a fake green — SPEC §4's
empty-join failure mode (a check that passes only because it has nothing to check) is a named
project anti-pattern, and a grep gate that "passes" against a file it can't actually see hits
would be the same bug in a new shape.

## Decision
Confine every banned §6.2 identifier used for definitional purposes to a single delimited block:
```
<!-- BANLIST:START -->
...banned terms, listed and explained, exactly once...
<!-- BANLIST:END -->
```
The gate strips that block before scanning:
```
awk '/<!-- BANLIST:START -->/{s=1} /<!-- BANLIST:END -->/{s=0;next} !s' <file> \
  | grep -nEi 'confidence|probability|percentile|uncertainty|error_bar|ci_low|ci_high|\bp10\b|\bp50\b|\bp90\b|±'
```
A pass requires the piped command to return nothing (grep exit 1) against the *stripped* output.
Verification must also run the same grep against the *unstripped* file and confirm real hits
exist, all located inside the block — proving the gate is filtering live content, not scanning
an accidentally-empty haystack.

**Trap to avoid:** the `awk`/`grep` invocation itself must never be pasted inside the
BANLIST block (e.g. in a "how to check this" code sample) — awk would then match the marker
strings inside its own quoted source line and the alternation leaks past the intended scope.
Keep the gate command outside the block, in prose or in a separate fenced example clearly outside
the markers.

## Consequences
- **Positive:** the document can define and explain banned terms in full prose without
  self-defeating its own compliance gate; the check is mechanical and cheap (`awk`+`grep`, no
  tooling dependency); the "verify against the unstripped file first" step gives a repeatable,
  non-trivial way to catch a broken/empty-scan gate before it ships.
- **Negative:** relies on markers being well-formed (exactly one START before one END) — a
  malformed or duplicated marker pair silently changes what's covered. Anyone editing the
  document must remember not to introduce a second BANLIST region or a banned term outside it.
  There is no automated test enforcing this yet (noted as a gap in F1's test report); F5/F6/F7
  each re-run the two-line grep by hand against their own source files.

## Alternatives Considered
- **Inline HTML comments per banned word** (e.g. `<!-- allowed: confidence -->` next to each
  use): rejected — doesn't scale to a block of prose that uses several banned terms together,
  and scatters the allowlist logic across the document instead of one auditable region.
- **A separate glossary file outside the design doc**: rejected — moves the definitions away
  from the sections that need them, and doesn't solve the core problem (something, somewhere,
  still has to both state and forbid the same words).
- **Weakened regex that excludes common definitional phrasing**: rejected — brittle, and defeats
  the purpose of the gate being simple enough to eyeball and re-run by hand in F5/F6/F7.
