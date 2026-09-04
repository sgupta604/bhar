# Summary: readme-and-caveats (T6 of 6 — final ticket)

**Completed:** 2026-09-04 | **Branch:** feat/site-tuned-blend | **PR:** none — no git remote configured (see Rules, SPEC §8/§9)

## What Was Built

A full rewrite of `README.md` as the project's demo document: run command, screenshot inventory,
what the numbers mean, the real backtest result (with the GFS finding given its own prominent
section), all six required caveats, and a repro path. Written in two passes — structure and prose
first (Pass A, independent of T5), then the thirteen real numbers copied from `data/results.json`
in one pass gated by a mechanical provenance check (Pass B). This finalize pass made one bounded
fix from the test-agent's finding — naming three previously-unlisted real-data screenshots in
README §2 — then closed the ticket.

## Files Changed

| Package | File | Change |
|---------|------|--------|
| docs | `README.md` | Full rewrite (commit `3710898`): run command, result, caveats, repro. Finalize fix (commit `d657931`): one sentence naming `real-6h.png`/`real-24h.png`/`real-full.png` in §2's screenshot inventory. |

## Tests

- test-agent: PASS (`.claude/active-work/readme-and-caveats/test-pass.md`, now cleaned up) —
  documented demo command run live as a stranger would, identity string matched byte-for-byte,
  `grep TBD` empty, every headline number independently recomputed from `data/results.json`.
- Finalize security/quality sweep: clean — no secrets, no debug code, no TODO/FIXME/HACK, no
  leftover fill-in markers, no machine-specific paths.
- Build / Lint / Types: N/A — doc-only ticket, no code changed.

## Key Decisions

- **D2 (plan) — structure now, numbers later; `grep TBD` is the completion gate.** Splitting the
  write into a T5-independent Pass A and a numbers-only Pass B took T6 off T5's critical path.
  It also turned out to be what let T6 survive the 04:15 API spend-limit halt: Pass A (631 lines,
  30 `TBD-FROM-T5` markers) was already on disk when both in-flight agents were killed, and it
  came back intact at resume with nothing to redo.
- **The provenance gate (plan Task 4.1) was the load-bearing control, not a formality.**
  `data/results.json` began the night byte-identical to `data/results.synthetic.json` (same md5,
  `is_synthetic: true`, a fabricated `RAP` exclusion, a hand-tuned −1.16% improvement). Without a
  mechanical gate checking `is_synthetic`, `source`, and the absence of that fabricated exclusion,
  Pass B could have copied fixture numbers into a README describing a real backtest and no
  reviewer would have caught it from the prose alone. The gate passed on first run only because
  T5 had genuinely landed by the time Pass B ran.
- **The GFS "drop it and average" finding was verified and found understated, not just repeated.**
  The un-fitted blend (HRRR 0.4 / NAM 0.3 / NBM 0.3) beats the fitted winner at 12 h (1.8879 vs
  1.9661) as well as at 24 h, where it is rank 1 of 286 — the literal floor. The README does not
  ship the softer original claim; it states the narrower surviving one — fitted weighting buys "a
  little at 6 h, nothing measurable at 12 h or 24 h" — in §1 up front and in a dedicated §5.1
  ("Most of the gain is from dropping GFS, not from the fitted weights"), not in a footnote.
- **Two claims were checked against reality and corrected before Pass B closed.** The
  `/openapi.json` identity string is `Bhar - Site-Tuned Model Blend` with a plain ASCII hyphen —
  Pass A had quoted an em dash, which matters because it is the one string a reader is told to
  match exactly. And "2.4× the next worst model" was wrong; the actual multiples are 2.03× / 2.30×
  / 2.26× at 6 h / 12 h / 24 h.
- **GFS is framed as a result, not an exclusion.** It was included in the study, scored, and
  earned weight 0.0 in every winning blend at every lead time. Coverage was 100.00% for all four
  models and the 90% floor excluded nobody — this is stated explicitly so a reader cannot mistake
  a fitted-weight-of-zero for a data problem.
- **This finalize pass's own scope was bounded to the test-agent's single finding.** The only
  authorized change was one sentence in README §2 naming `real-6h.png`, `real-24h.png`, and
  `real-full.png` as additional real-data captures alongside `t5-real-results.png`. No other edit,
  refactor, or polish pass was made, per SPEC §9's stop condition ("all six tickets green → stop;
  do not polish").

## Deferred Items

- **`scripts/smoke_ui.sh` step 6, recorded not fixed (T3-owned).** It asserts a *negative* 24 h
  improvement, which was true of the synthetic fixture but is false of the real data (+16.51%), so
  the smoke check no longer exercises the danger-tone render path against real data. The danger
  path itself is still covered against the synthetic fixture. Flagged in the README and in the
  session log for whoever next touches T3; out of scope for a docs-only ticket.

## Retrospective

### Worked Well

- The Pass A / Pass B split (D2) did exactly what it was designed for — kept T6 off T5's critical
  path — and then did something it wasn't explicitly designed for: it made the ticket resilient
  to an infrastructure failure. When the 04:15 spend-limit halt killed both in-flight agents,
  T6's non-result prose was already safely on disk and only the numbers pass had to be redone.
  Lesson: sequencing a ticket so its cheap, deterministic part is written first and its
  data-dependent part is a small, separately-gated pass is worth doing even when the only stated
  reason is scheduling, because it also buys resumability for free.
- The provenance gate (`is_synthetic`, `source`, absence of the fabricated `RAP` exclusion) is the
  single artifact from this ticket worth reusing verbatim on the next project with a
  fixture/real-data seam. It converted an easy-to-violate promise ("don't copy fixture numbers")
  into a five-line script with an exit code, and it caught nothing this time only because T5 had
  already landed — the value is that it *would* have caught it.
- Verifying claims against `data/results.json` independently, rather than trusting the research
  doc's phrasing, caught two real errors (the em dash vs. ASCII hyphen identity string, and the
  2.4× vs. actual 2.03–2.30× multiplier) before they shipped. Both were the kind of small, plausible
  inaccuracies that survive a read-through but fail the first time a real reader copy-pastes a
  string.

### Went Wrong

- The test-agent found a real, if minor, gap: three real-data screenshots existed in the
  screenshots directory but weren't named in README §2's inventory. Nothing in Pass A or Pass B
  caught this because both passes were driven by a checklist of *required* content, not by a
  listing of the directory being described. Lesson for future doc tickets: when a README section
  claims to inventory a directory, generate or check the inventory against `ls`, not against a
  fixed acceptance-criteria list — an itemized list can be internally complete and still miss a
  file that showed up after the list was written (here, screenshots captured at 08:02, after Pass
  A's list was drafted at 04:13).
- Nothing else surfaced by this finalize pass. No secrets, no debug code, no stray TODOs, no
  fabricated numbers survived to this point in the pipeline — which is itself a marker of the
  earlier gates (T5's mutation-proof tests, T6's provenance gate) doing their job upstream rather
  than finalize catching them late.

### Process

- Pipeline flow: smooth. The one disruption (04:15 spend-limit halt) was infrastructure, not a
  plan or code failure, and the resuming agent verified rather than trusted the inherited
  Pass A state before continuing — no rework was needed.
- Task granularity: right. Splitting the ticket into Streams 1–3 (structure/prose, serialized on
  one Markdown file) and Stream 4 (number fill-in, gated on T5 green) matched the actual
  dependency shape and avoided idle waiting on the slower ticket.
- Estimate accuracy: plan estimated ~40–55 min prose + ~10 min number fill-in; actual came in
  close to that shape (Pass A by 04:13, Pass B by 08:00) once the spend-limit gap (04:15–08:00,
  external to the ticket's own effort) is excluded.
- Agent delegation: the two-pass split let a single implementer own the whole ticket without
  needing a specialist handoff — appropriate for a doc-only ticket with no code or schema surface.
  This finalize pass required no delegation: the one authorized fix was a single sentence with a
  named, bounded scope.
