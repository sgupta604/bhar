# Summary: forecast-design (ticket F1 of FORECAST-SPEC)

**Completed:** 2026-09-04 | **Branch:** `feat/forecast-page` (shared across all nine
FORECAST-SPEC tickets — no separate `feat/forecast-design` branch was created) | **PR:** none —
FORECAST-SPEC §12 defines one PR at the end of F9, not per ticket

## What Was Built
A pure design document, `.claude/features/forecast-page/design-target.md` (1944 lines) — the
written visual target for the forecast page's eight required regions (headline/run label,
forward strip, 24h boundary, gap treatment, trust panel, back-arrow/past-day view, stale/
synthetic states, empty state) plus literal, pasteable CSS. It produces no HTML, CSS, or JS
file; F5 builds `frontend/forecast.{html,css,js}` from it later. The document is a direct
descendant of the sibling `demo-shell` design (T3) and explicitly references rather than
restates T3's model→colour map, slider CSS, and chart/axis CSS.

## Files Changed
| Package | File | Change |
|---------|------|--------|
| `.claude/features/forecast-page/` | `design-target.md` | New — 1944-line design spec |
| `.claude/features/forecast-design/` | `2026-09-04T16-14-18_research.md`, `2026-09-04T16-20-01_plan.md` | New — research and plan docs |
| `.claude/decisions/` | `0001-banlist-gate.md` | New — ADR for the BANLIST technique |
| `.claude/pipeline/` | `STATUS.md` | F1 row → done; phase/next advanced to F2 |

No file under `frontend/`, `backend/`, `score/`, `fetch/`, `docs/`, or `tests/` was touched
(`git diff --stat 37ca272` confirms — only `.claude/` changed).

## Tests
- pytest: 308 passing, exit 0 (unchanged — this ticket adds no test code, correctly: the
  deliverable is a markdown document)
- Lint: `ruff check .` clean
- Types: n/a — no type checker installed, deliberate (SPEC §13)
- Build: n/a — Python from source, static frontend, no bundler
- BANLIST gate: independently re-run (not taken on the implementer's or test-agent's word) —
  stripped file returns zero hits; unstripped file returns 8 hits, all inside the block
  (lines 116-185)

## Key Decisions
- **The BANLIST technique** (see ADR-0001): a design doc that *bans* words (§6.2's confidence/
  probability/percentile/error_bar/±/etc.) must also *print* them to define what's forbidden, so
  a naive whole-file grep can never pass. Every banned identifier used definitionally is confined
  to a single `<!-- BANLIST:START -->`…`<!-- BANLIST:END -->` block; the gate strips that block
  first, then greps the rest:
  ```
  awk '/<!-- BANLIST:START -->/{s=1} /<!-- BANLIST:END -->/{s=0;next} !s' design-target.md \
    | grep -nEi 'confidence|probability|percentile|uncertainty|error_bar|ci_low|ci_high|\bp10\b|\bp50\b|\bp90\b|±'
  ```
  **F5 and F7 must reuse this exact gate against their own source files.** Trap to avoid: the
  `awk`/`grep` invocation itself must never be pasted *inside* the BANLIST block — otherwise awk
  matches the marker strings in its own quoted source line and the alternation leaks past the
  intended region. Keep the gate command in prose or a separate fenced block, outside the markers.
- **Gate verified against real content, not an empty haystack.** Ran the identical grep against
  the *unstripped* file first: 8 genuine hits, all located at lines 125-169 (entirely inside the
  BANLIST block). This is the same discipline SPEC §4 requires of join match counts — a check
  that "passes" only because it never saw a real hit is a fake green, not a pass. Confirmed twice
  independently: once during implementation, once again during this finalize pass.
- **Section numbering is a contract, not cosmetics.** F5, F6, and F7 each cite this document's
  section numbers directly (§1.1-1.9 for the eight regions, §2/§3 for CSS, §4 for the trust
  panel, §5 for dark-mode, §6 for token audit rules, §7 for weight banding). Renumbering any
  section later breaks three downstream tickets simultaneously — treat the numbering as frozen
  unless all three are updated together.
- **`frontend/theme.js` does not exist on this branch**, and no `[data-theme=dark]` rule exists
  in any linkable stylesheet (`tokens.css`, `vendor/clarity-tokens.css`). §5 of the design doc
  therefore supplies the dark semantic layer and pre-hydration script itself, scoped entirely to
  `forecast.css`. **Recommendation carried to F5: ship light-only for v1** — the dark block is
  written and ready in §5 whenever F5 (or a later ticket) chooses to wire it in, but nothing
  requires it for F1-F5 to be considered complete.
- **`frontend/app.css` is not on §3's permitted-link list.** `forecast.css` must re-author
  `.card`/`.tbl`/`.segmented`/`.empty-state` rather than link the existing stylesheet. This
  duplication is deliberate, not an oversight — it is what keeps the demo path (`index.html`,
  `app.css`, `app.js`) byte-identical while the forecast page ships independently.
- **Winner selection: in-sample MAE, not `results.json`'s own rank.** `results.json`'s `blends[]`
  array is ranked by *out-of-sample* MAE, and rank-1 there is **not** the blend the design doc
  uses. The test-agent recomputed independently and confirmed the document's trust-panel weights
  are the blend that minimizes **in-sample (train)** MAE at each lead, matched by `winner.label`
  — the methodologically correct choice (fit on train, score on held-out test). Reproduced
  exactly at all three leads (6h/12h/24h). **F3 must select the winner the same way** —
  defaulting to `blends[0]` or the JSON's own ranking is look-ahead bias and would silently
  misreport which blend actually won.

## Deferred Items
- No automated harness re-runs the BANLIST gate or the token audit in CI. F5/F6/F7 each re-run
  the two-line grep by hand against their own new source files, per the document's own
  instructions. Worth a follow-up ticket; not a blocker for F1 or any ticket that depends on it.
- Dark-mode wiring (`theme.js`, `[data-theme=dark]` activation) is specified in §5 but not
  activated anywhere yet — deferred to F5's judgment, with a light-only-v1 recommendation.

## Retrospective
### Worked Well
- Writing the banned-term definitions inside a single delimited, strippable block (rather than
  scattering inline exceptions or weakening the regex) kept both the prose and the compliance
  gate simple enough to eyeball and to reuse verbatim in later tickets.
- The test-agent's discipline of running the grep against the *unstripped* file before trusting
  the stripped-file zero-hits result caught exactly the failure mode this project has hit before
  (SPEC §4's empty-join integrity rule) — a check that passes because it has nothing to check.
  That verification step is now documented in ADR-0001 as required practice, not optional.
- Cross-checking trust-panel numbers against `data/results.json` by hand, including reproducing
  the in-sample-MAE winner selection independently rather than string-matching the plan's
  pre-stated table, surfaced a genuinely non-obvious detail (rank-1 in `blends[]` is not the
  fitted winner) that a looser check would have missed entirely.

### Went Wrong
- The feature's `active-work` directory is named `forecast-page`, but this ticket's own
  identity is `forecast-design` (research/plan docs live under
  `.claude/features/forecast-design/`, the deliverable under `.claude/features/forecast-page/`).
  The mismatch is intentional per FORECAST-SPEC (one shared branch, nine tickets, two directory
  names in play), but it is exactly the kind of thing a fresh session could stumble on — worth
  calling out explicitly in each ticket's kickoff rather than relying on the session log alone.
- WORKFLOW.md's default finalize process (branch-per-feature, PR-per-feature, delete
  `active-work/`) actively conflicts with FORECAST-SPEC's shared-branch, one-PR-at-F9,
  keep-the-session-log model. Every one of these nine finalize passes needs the override spelled
  out explicitly, or a fresh finalize-agent will try to cut a new branch and delete the session
  log by default.

### Process
- Pipeline flow: smooth. Research → plan → implement → test → finalize ran without rework;
  the test-agent's independent re-verification (BANLIST gate, trust-panel numbers) caught no
  actual defects but is exactly the check that would have caught one.
- Task granularity: right. F1 as "design document only, no source files" is a clean, verifiable
  unit — the absence of `frontend/forecast.{html,css,js}` is itself part of the acceptance gate.
- Estimate accuracy: not tracked in hours for this run; scope (1944-line document, 8 regions,
  literal CSS) matched what the plan called for with no material overrun.
- Agent delegation: research-agent, plan-agent, and test-agent all performed independent
  verification rather than trusting upstream claims (the test-agent in particular re-derived
  trust-panel numbers and re-ran the BANLIST gate from scratch) — this is the pattern to keep
  reinforcing across F2-F9.
