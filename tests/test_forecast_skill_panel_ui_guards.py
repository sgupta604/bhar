"""F7 Stream 5 — the skill panel region's own guards, and the proofs that they can fail.

WHAT THIS MODULE IS
-------------------
F7 adds a bounded region to all three shipped frontend files — `frontend/forecast.html`,
`frontend/forecast.js` and `frontend/forecast.css` — between a `SKILL PANEL CONTENT — F7`
banner and its explicit `END SKILL PANEL CONTENT — F7` marker. Everything below scans those
three slices, and only those three slices, for the shapes the ticket forbids.

WHY IT IMPORTS INSTEAD OF RE-TYPING
-----------------------------------
`tests/test_forecast_ui_guards.py` (F5) already owns the ban pattern, the comment strippers,
the payload-literal scanner, the absolute-value scanner, the state-attribute pattern, the
`grep` runner and its exit-status classifier. `tests/test_forecast_history_ui_guards.py` (F6)
owns the tail-anchored region extractor and F6's own byte floors. Both are read-only from
here and every shared name is IMPORTED.

Re-typing one of those patterns "so this file stands alone" is the defect this note exists to
forbid: two copies of a pattern drift, and the copy that drifts is invariably the one that
stops catching things while still reporting green. The only thing declared locally that also
exists upstream is the `grep_binary` fixture, and for one mechanical reason — pytest resolves
a fixture by the name bound in the importing module, and an imported fixture shadowed by a
same-named parameter is a lint error. Its whole body is a PATH lookup; there is no pattern in
it to drift.

THE FAILURE MODE THIS STREAM EXISTS TO PREVENT
----------------------------------------------
A guard that greps three files and finds nothing is indistinguishable, from its output alone,
from a guard that greps NOTHING and finds nothing. This project has shipped that bug more
than once, and a region-scoped guard is the easiest place to ship it again: mistype a marker
and the extractor either returns "" or silently widens to the whole document, and every
assertion below then passes while inspecting the wrong bytes, or none.

So:

    PROOF 1 — the haystack is real. The three files are asserted to exist above F5's own byte
    floor; the F7 region cut from each is asserted above a RAW floor and, separately, above a
    COMMENT-STRIPPED floor, because most guards here read stripped source and a stripper that
    ate the region would make all of them vacuous. The extractor RAISES on a missing opening
    marker and on a missing END marker — it never falls back to the whole file and never
    returns an empty string.

    PROOF 2 — every guard fires. Each carries a positive control: a synthesized violation run
    through THE SAME code path the real assertion uses, never a hand-checked look-alike.

    PROOF 3 — no guard over-fires. Each carries a sanctioned-shape control built from the
    constructs actually present in the shipped source — the hand-folded magnitude, the tone
    attribute write, the stylesheet's own `display` rule, the spacing tokens — so a guard that
    would fail the page for being correct is caught here rather than in review.

    PROOF 4 — the shape guard can see a real hit. `frontend/forecast.js` genuinely contains
    `band` OUTSIDE the F7 region (F5 writes a `data-band` attribute on the strip). The same
    pattern that reports zero hits inside the region is proven to match that real occurrence
    in the same file, so "no hits" here is a fact about the region, not about the pattern.

    PROOF 5 — the gate goes red on F7 content. Each file is copied in memory, a banned token
    is injected INSIDE the F7 region, and the gate is re-run over the copy through the same
    `gate_verdict` the real gate uses. The real file's digest is compared before and after.

    PROOF 6 — F6's region is untouched. F6's own extractor is imported and run; its slices of
    `forecast.js` and `forecast.css` are asserted above F6's floors and pinned, byte for byte,
    to the pre-F7 capture by length and sha256. F6's guard module is then executed in a
    subprocess and required to pass with a non-zero test count.

WHAT THIS MODULE CANNOT CATCH — READ THIS BEFORE TRUSTING IT
------------------------------------------------------------
This is a SOURCE-LEVEL guard and nothing more. Stated plainly, because a guard that
overclaims is worse than no guard at all: it buys the reader a certainty that was never
purchased, and the review that would have caught the problem does not happen.

  * IT NEVER READS THE RENDERED DOM. There is no JavaScript test runner in this project and
    SPEC §13 does not add one. Nothing here executes `frontend/forecast.js`, builds a node, or
    inspects what a browser finally paints. A sentence assembled correctly in source and
    rendered wrongly — wrong node, wrong order, hidden behind a stylesheet rule this module
    does not model — passes every test below.
  * IT CANNOT CATCH A CLAIM NOBODY BLACKLISTED. The ban list is a finite list of tokens. A
    forward-looking promise phrased in words that are not on it reads as ordinary prose to
    every pattern here. Only a human reading the copy catches that, and this module is not a
    substitute for that reading.
  * IT CANNOT POLICE A FUTURE SERVER PAYLOAD. It proves the page does not TYPE a model name,
    a lead hour or a site name. It says nothing about what the backend will one day put in
    `skill.by_lead`, and a page that faithfully renders a wrong number is green here.
  * IT IS SCOPED TO THE F7 REGION. Content moved outside the markers leaves this module's
    field of view entirely. F5's and F6's file-wide guards still apply; these do not.
  * IT DOES NOT CHECK ARITHMETIC. Whether the improvement figure is computed correctly is the
    business of the payload contract tests, not of a text scan.

SCOPE AND SAFETY
----------------
Nothing here starts a server, opens a socket, or writes anywhere but `tmp_path`. Every file
outside `tmp_path` is opened for reading only. No banned string is typed literally in this
source — the tokens are imported from F5, which assembles them from character escapes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_forecast_history_ui_guards import (
    HISTORY_MARKER,
    MINIMUM_REGION_BYTES as F6_MINIMUM_REGION_BYTES,
    region_from_marker as f6_region_from_marker,
)
from test_forecast_ui_guards import (
    ABS_CALL,
    ALTERNATIVE_IDS,
    BANLIST_PATTERN,
    BANLIST_RE,
    BANNED_ALTERNATIVES,
    CLEAN,
    ERROR,
    FORECAST_CSS,
    FORECAST_HTML,
    FORECAST_JS,
    MATCHED,
    MINIMUM_SCANNED_BYTES,
    PLUS_MINUS,
    REPO,
    SCANNED,
    STATE_ATTR_OFF_VALUE,
    TRUE_MINUS,
    baked_payload_literals,
    banned_word,
    forbidden_abs_uses,
    gate_verdict,
    grep_lines,
    strip_css,
    strip_html,
    strip_js,
)

# ==========================================================================================
# The F7 region — bounded on BOTH sides, unlike F6's tail-anchored slice
# ==========================================================================================

#: The banner that opens the region in all three files. Matched case-insensitively.
F7_MARKER = "SKILL PANEL CONTENT — F7"

#: The explicit closing marker. Note it CONTAINS the opening marker as a substring, which is
#: why the search for it starts after the opener's own match rather than at offset zero.
F7_END_MARKER = "END SKILL PANEL CONTENT — F7"

#: The nested copy block inside the JS region, pinned by the sibling copy module.
PANEL_COPY_MARKER = "PANEL COPY"
PANEL_COPY_END_MARKER = "END PANEL COPY"

#: Per-file comment delimiters. The region is rewound to the OPENING delimiter and run to the
#: CLOSING one so it begins and ends with balanced comments — otherwise the strippers would
#: not recognise the banner as a comment, would leave its prose in the "code", and every
#: stripped-source guard below would start scanning English it was never meant to see.
REGION_DELIMITERS: dict[str, tuple[Path, str, str]] = {
    "forecast.html": (FORECAST_HTML, "<!--", "-->"),
    "forecast.js": (FORECAST_JS, "/*", "*/"),
    "forecast.css": (FORECAST_CSS, "/*", "*/"),
}

REGION_NAMES = ("forecast.html", "forecast.js", "forecast.css")

STRIPPERS = {"forecast.html": strip_html, "forecast.js": strip_js, "forecast.css": strip_css}

#: Raw floors. Generous by design — the job is to catch a stub produced by a re-worded marker,
#: not to pin the region's exact size and fail every edit.
MINIMUM_F7_REGION_BYTES = {"forecast.html": 800, "forecast.js": 18000, "forecast.css": 5000}

#: The same floors after comment stripping. Most guards below read the stripped text, so an
#: over-eager stripper would quietly empty every one of them. The HTML floor is small on
#: purpose: F7's markup contribution is one element plus its id, and the comments around it
#: are the bulk of the raw region.
MINIMUM_F7_REGION_CODE_BYTES = {"forecast.html": 50, "forecast.js": 9000, "forecast.css": 900}

#: ...and the same again with all whitespace removed, so a slice that is 90% newlines cannot
#: clear the byte floor while carrying almost no code.
MINIMUM_F7_REGION_CODE_NONSPACE = {"forecast.html": 40, "forecast.js": 6000, "forecast.css": 700}


class MissingRegionMarker(AssertionError):
    """Raised when a marker is gone. NEVER swallowed into an empty or whole-file region.

    Subclasses `AssertionError` so a stray marker rename reads as a test failure rather than
    an error nobody classifies, while still being catchable by type in the controls below.
    """


def f7_region(text: str, opener: str, closer: str) -> str:
    """The slice of `text` from the comment carrying `F7_MARKER` to the one carrying its END.

    Both ends are explicit. That is the whole difference from F6's extractor, which anchors on
    its banner and runs to end of file: F7's regions sit in the MIDDLE of all three files
    (above F6's banner in the two it shares), so a tail-anchored slice would be wrong here and
    a marker-to-marker slice is the only correct shape.

    Raises `MissingRegionMarker` when either marker is gone. The two tempting fallbacks are
    both silent disasters: returning "" makes every region-scoped guard below scan nothing and
    report green, and returning the whole document makes them fire on F5 and F6 content this
    region was never responsible for.
    """
    upper = text.upper()
    index = upper.find(F7_MARKER.upper())
    if index == -1:
        raise MissingRegionMarker(
            f"the {F7_MARKER!r} banner is gone — every region-scoped guard in this module "
            f"would be scanning nothing, and a scan of nothing reports exactly the same green "
            f"as a scan of something clean"
        )
    start = text.rfind(opener, 0, index)
    if start == -1:
        raise MissingRegionMarker(
            f"no {opener!r} precedes the F7 banner; the region would open mid-comment and the "
            f"stripper would leave its prose in the scanned code"
        )
    end_index = upper.find(F7_END_MARKER.upper(), index + len(F7_MARKER))
    if end_index == -1:
        raise MissingRegionMarker(
            f"the {F7_END_MARKER!r} marker is gone — the region is unbounded and would run to "
            f"end of file, swallowing content F7 is not responsible for"
        )
    stop = text.find(closer, end_index)
    if stop == -1:
        raise MissingRegionMarker(f"no {closer!r} closes the region after its END marker")
    region = text[start : stop + len(closer)]
    if not region.strip():
        raise MissingRegionMarker("the extracted region is blank")
    return region


@pytest.fixture(scope="session")
def grep_binary() -> str:
    """The `grep` the gate shells out to — or a clean skip where there is none.

    Declared locally rather than imported for one mechanical reason, recorded in the module
    docstring: pytest resolves a fixture by the name bound in this module, and an imported
    fixture shadowed by a same-named test parameter is a lint error. The body is a PATH
    lookup; nothing in it could drift from F5's copy.
    """
    found = shutil.which("grep")
    if found is None:
        pytest.skip("grep is not available on PATH")
    return found


@pytest.fixture(scope="module")
def f7_raw() -> dict[str, str]:
    """The three F7 regions as written, comments included."""
    return {
        name: f7_region(path.read_text(encoding="utf-8"), opener, closer)
        for name, (path, opener, closer) in REGION_DELIMITERS.items()
    }


@pytest.fixture(scope="module")
def f7_code(f7_raw: dict[str, str]) -> dict[str, str]:
    """The three F7 regions reduced to code: comments out, string literals kept."""
    return {name: STRIPPERS[name](f7_raw[name]) for name in REGION_NAMES}


# ==========================================================================================
# TASK 5.1 — PROOF 1: the haystack is real, and so is the region cut out of it
# ==========================================================================================


def test_haystack_is_exactly_three_files_and_f7_added_no_fourth() -> None:
    """Three scanned files, by name, no more and no fewer.

    F7's whole delivery is three bounded regions inside files that already existed. A fourth
    frontend module would slip past every file-wide guard F5 owns AND past this module, and
    `tests/test_forecast_ui_guards.py` asserts the same count independently — so a new file
    fails there too rather than only here.
    """
    assert len(SCANNED) == 3, f"the scanned set is no longer three files: {SCANNED}"
    assert [path.name for path in SCANNED] == list(REGION_NAMES), (
        f"the scanned set changed to {[p.name for p in SCANNED]}; F7 adds no frontend file, "
        f"it adds a bounded region to each of the three that already ship"
    )


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_haystack_each_file_exists_and_is_above_the_scan_floor(path: Path) -> None:
    """Each scanned path resolves under `frontend/`, exists, and clears F5's byte floor.

    A typo'd path greps nothing and passes silently. That exact failure is named in two of
    this project's retrospectives, which is why it is asserted rather than assumed.
    """
    assert path.is_file(), f"{path} does not exist — a scan of a missing file is not a scan"
    size = path.stat().st_size
    assert size >= MINIMUM_SCANNED_BYTES, f"{path} is only {size} bytes; that is a stub"


@pytest.mark.parametrize("name", REGION_NAMES)
def test_f7_region_is_a_real_substantial_slice(name: str, f7_raw: dict[str, str]) -> None:
    """The extracted region is a real, substantial substring of the file it came from."""
    region = f7_raw[name]
    path = REGION_DELIMITERS[name][0]
    whole = path.read_text(encoding="utf-8")

    assert region in whole, f"{name}: the region is not a substring of its own file"
    assert len(region) < len(whole), (
        f"{name}: the region is the whole document — the END marker is not doing its job, and "
        f"these guards would be firing on F5 and F6 content they do not own"
    )
    floor = MINIMUM_F7_REGION_BYTES[name]
    assert len(region) >= floor, (
        f"{name}: the F7 region read as {len(region)} bytes, under the {floor}-byte floor. "
        f"A mistyped marker yields a stub, and a stub reports the same green as clean code."
    )
    assert F7_MARKER.upper() in region.upper()
    assert F7_END_MARKER.upper() in region.upper()


@pytest.mark.parametrize("name", REGION_NAMES)
def test_f7_region_survives_comment_stripping_with_code_left(
    name: str, f7_raw: dict[str, str], f7_code: dict[str, str]
) -> None:
    """Stripping the comments leaves substantial code behind, in bytes and in non-whitespace.

    Every stripped-source guard below would be vacuous if the stripper returned a stub, and
    an all-whitespace result would clear a naive byte floor, so both are asserted.
    """
    raw, code = f7_raw[name], f7_code[name]
    assert len(code) < len(raw), f"{name}: stripping removed nothing; the comments are intact"

    floor = MINIMUM_F7_REGION_CODE_BYTES[name]
    assert len(code) >= floor, (
        f"{name}: only {len(code)} bytes survived comment stripping, under the {floor}-byte "
        f"floor. Every stripped-source guard in this module would be scanning a stub."
    )
    dense = "".join(code.split())
    dense_floor = MINIMUM_F7_REGION_CODE_NONSPACE[name]
    assert len(dense) >= dense_floor, (
        f"{name}: only {len(dense)} non-whitespace characters survived stripping, under the "
        f"{dense_floor} floor — the slice is mostly blank lines"
    )


def test_f7_region_carries_its_landmarks(f7_code: dict[str, str]) -> None:
    """Real content, named. If the panel is rewritten these names go with it and this fails.

    Deliberately a handful of structural names rather than prose: prose is the sibling copy
    module's business, and duplicating its pins here would create the second copy that drifts.
    """
    assert "skill-lead" in f7_code["forecast.js"]
    assert "data-improve" in f7_code["forecast.js"]
    assert "skill-extrapolated-link" in f7_code["forecast.html"]
    assert ".skill-improve" in f7_code["forecast.css"]


def test_f7_panel_copy_block_is_nested_inside_the_js_region(f7_raw: dict[str, str]) -> None:
    """The copy block the sibling module pins sits strictly INSIDE the F7 JS region.

    Asserted here so a future edit cannot quietly move the copy out of the region these guards
    cover; the copy would then be pinned for wording by one module and scanned for forbidden
    shapes by neither.
    """
    region = f7_raw["forecast.js"]
    start = region.find(PANEL_COPY_MARKER)
    end = region.find(PANEL_COPY_END_MARKER)
    assert start != -1, f"{PANEL_COPY_MARKER!r} is not inside the F7 JS region"
    assert end > start, f"{PANEL_COPY_END_MARKER!r} does not follow its opener inside the region"


# ------------------------------------------------------------------------------------------
# PROOF 1b — the extractor raises rather than degrading to a silent, vacuous scan
# ------------------------------------------------------------------------------------------

CONTROL_DOCUMENT = (
    "/* header comment, not part of the region */\n"
    "var before = 1;\n"
    "/* ══ SKILL PANEL CONTENT — F7 ══ */\n"
    "var inside = 2;\n"
    "/* ══ END SKILL PANEL CONTENT — F7 ══ */\n"
    "var after = 3;\n"
)


def test_f7_region_extractor_positive_control() -> None:
    """On a synthesized document the extractor returns exactly the bounded slice.

    Both ends are checked: content before the banner and after the END marker must be absent.
    An extractor that returned the whole document would pass a "region is non-empty" test and
    then apply region-scoped guards to the entire file.
    """
    region = f7_region(CONTROL_DOCUMENT, "/*", "*/")
    assert region.startswith("/* ══ SKILL PANEL CONTENT")
    assert region.rstrip().endswith("*/")
    assert "var inside = 2;" in region
    assert "var before = 1;" not in region, "the region reached back past its own banner"
    assert "var after = 3;" not in region, "the region ran past its own END marker"


@pytest.mark.parametrize(
    ("broken", "why"),
    [
        ("var only = 1;\n", "no marker at all"),
        ("/* ══ SKILL PANEL CONTENT — F7 ══ */\nvar x = 1;\n", "opener but no END marker"),
        ("/* ══ END SKILL PANEL CONTENT — F7 ══ */\n", "END marker but no opener"),
        ("SKILL PANEL CONTENT — F7\nEND SKILL PANEL CONTENT — F7\n", "no comment delimiter"),
    ],
)
def test_f7_region_extractor_raises_on_a_missing_marker(broken: str, why: str) -> None:
    """A missing marker RAISES. It never yields "" and never yields the whole document.

    This is the single most important test in the file. Both silent fallbacks pass every
    downstream assertion while inspecting the wrong bytes — one scans nothing, the other scans
    everything — and both report exactly the green a clean region reports.
    """
    with pytest.raises(MissingRegionMarker):
        f7_region(broken, "/*", "*/")


def test_f7_region_extractor_finds_the_opener_before_the_end_marker() -> None:
    """The END marker CONTAINS the opening marker; the extractor must not confuse the two.

    A naive `find(END_MARKER)` from offset zero would land on the opener's own line if the
    strings were searched in the wrong order. Here the opener's match is skipped explicitly,
    so a document carrying only the END marker raises rather than yielding a zero-length slice.
    """
    assert F7_MARKER in F7_END_MARKER, "the END marker no longer contains the opener substring"
    region = f7_region(CONTROL_DOCUMENT, "/*", "*/")
    assert region.upper().count(F7_MARKER.upper()) == 2, (
        "the slice should carry the opener once and inside the END marker once"
    )


# ==========================================================================================
# TASK 5.1 — the ban list, run over the real files and proven able to go red
# ==========================================================================================


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_banlist_gate_is_still_clean_after_the_f7_additions(path: Path, grep_binary: str) -> None:
    """F5's gate, unmodified, still reports clean on all three files after F7's regions landed.

    Run through the imported `gate_verdict` so an errored scan is a FAILURE rather than a
    pass: a missing file and a clean file both produce no output, and only the exit status
    tells them apart.
    """
    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, path)
    assert verdict != ERROR, f"the gate errored scanning {path}: {detail}"
    assert verdict == CLEAN, f"{path.name} carries a banned string:\n{detail}"


@pytest.mark.parametrize("alternative", BANNED_ALTERNATIVES, ids=ALTERNATIVE_IDS)
def test_banlist_positive_control_every_alternative_still_fires(
    alternative: str, tmp_path: Path, grep_binary: str
) -> None:
    """Each alternative is proven to match on its own, through the real gate mechanism.

    One parametrized case each, so a single subtly broken branch — a mangled word boundary, a
    typo — cannot hide behind the ten that still work.
    """
    token = banned_word(alternative)
    sample = tmp_path / "sample.js"
    sample.write_text(f"var note = 'a {token} figure';\n", encoding="utf-8")

    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, sample)
    assert verdict == MATCHED, f"the gate did not fire on {alternative!r} ({verdict}: {detail})"
    assert grep_lines(grep_binary, BANLIST_PATTERN, sample), "grep reported no matching lines"
    assert BANLIST_RE.search(sample.read_text(encoding="utf-8")) is not None


# ------------------------------------------------------------------------------------------
# The plus-or-minus character — banned in the region RAW, comments included
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", REGION_NAMES)
def test_no_plus_or_minus_character_in_the_f7_region(name: str, f7_raw: dict[str, str]) -> None:
    """U+00B1 appears nowhere in the F7 region — not in code, not in prose, not in a comment.

    Scanned RAW rather than stripped, deliberately: the ban is on the character reaching the
    source at all. Attached to a measured mean error it would claim a spread this backtest
    never computed, and a comment carrying it is one copy-paste from the page.
    """
    region = f7_raw[name]
    assert len(region) >= MINIMUM_F7_REGION_BYTES[name], "the region read as a stub"
    assert PLUS_MINUS not in region, (
        f"{name}'s F7 region carries the plus-or-minus character at offset "
        f"{region.find(PLUS_MINUS)} — every figure in this region is a settled past "
        f"measurement, not a hedge"
    )


def test_no_plus_or_minus_positive_control(f7_raw: dict[str, str]) -> None:
    """The same membership test, over a region with the character planted, must fire.

    Without this, "the character is not in the region" is indistinguishable from "the region
    is an empty string" — which is exactly why this module asserts its haystack.
    """
    poisoned = f7_raw["forecast.js"] + f"\n// planted {PLUS_MINUS} 0.5\n"
    assert PLUS_MINUS in poisoned, "the membership test cannot see a planted character"
    assert BANLIST_RE.search(poisoned) is not None, "the ban pattern missed the same plant"
    assert PLUS_MINUS not in f7_raw["forecast.js"], "the unplanted region was not clean"


def test_plus_or_minus_guard_does_not_confuse_the_real_minus(f7_raw: dict[str, str]) -> None:
    """U+2212, the typographic minus the formatter substitutes, is NOT the banned character.

    A guard that conflated the two would fail the page for rendering a negative improvement
    correctly — and rendering a negative improvement correctly is the point of the ticket.
    """
    assert TRUE_MINUS != PLUS_MINUS
    assert PLUS_MINUS not in f"a change of {TRUE_MINUS}12.5 percent"
    assert PLUS_MINUS not in f7_raw["forecast.css"]


# ==========================================================================================
# TASK 5.1 — no payload literal typed into the region
# ==========================================================================================


def test_f7_js_region_bakes_in_no_payload_literal(f7_code: dict[str, str]) -> None:
    """No model name, no site name, no bare cell count anywhere in the F7 JS region.

    F5's scanner, imported rather than re-derived. The best single model VARIES BY LEAD in the
    shipped payloads, so a typed name would not merely go stale — it would be wrong on the
    day it was written, for two of the three leads.
    """
    hits = baked_payload_literals(f7_code["forecast.js"])
    assert hits == [], (
        f"the F7 region bakes in payload literals {hits}. The model name arrives in "
        f"meta.best_single_model_by_lead, the site in meta.site, the counts in the payload."
    )


@pytest.mark.parametrize(
    "bad",
    [
        "var best = 'HRRR';",
        'var m = "nbm";',
        "var site = 'Omaha Eppley Airfield';",
        "copyLeadSentence({ model: 'GFS' });",
        "var CELLS = 16;",
    ],
)
def test_payload_literal_positive_control(bad: str) -> None:
    """The scanner fires on each shape a baked literal actually arrives in."""
    assert baked_payload_literals(bad), f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "var best = String(lead.best_single_model || '');",
        "block.setAttribute('data-lead-h', lead.lead_h);",
        "return 'var(--model-' + String(model).toLowerCase() + ')';",
        "var pairs = pairsPerLead(lead.n_test, split.train_days, split.test_days);",
    ],
)
def test_payload_literal_stays_silent_on_the_real_f7_reads(sanctioned: str) -> None:
    """Lines in the shape the shipped region uses. A guard that fires on these is noise."""
    assert baked_payload_literals(sanctioned) == [], f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — no typed lead literal, JS REGION ONLY
# ==========================================================================================

#: The three measured leads, as bare numbers not part of a longer number or identifier. Byte
#: for byte the shape F6 uses, imported in spirit but necessarily re-stated because F6 keeps
#: it module-private; the two are asserted equal in the test below so they cannot drift.
LEAD_LITERAL = re.compile(r"(?<![\w.])(?:6|12|24)(?![\w.])")


def test_f7_js_region_types_no_lead_literal(f7_code: dict[str, str]) -> None:
    """`6`, `12` and `24` are never typed in the JS region. Every lead comes from the payload.

    A typed lead outlives a change to the fitted lead set, and the panel's own rule — no skill
    measurement beyond the fitted range, and no number quoted there — depends on the boundary
    being read rather than assumed.
    """
    hits = [match.group(0) for match in LEAD_LITERAL.finditer(f7_code["forecast.js"])]
    assert hits == [], (
        f"the F7 JS region types the lead literal(s) {hits}. Leads arrive as lead.lead_h and "
        f"the fitted boundary as the payload's own first extrapolated slot."
    )


@pytest.mark.parametrize(
    "bad",
    [
        "if (lead.lead_h > 24) return null;",
        "var leads = [6, 12, 24];",
        "text += 'at the 12 hour lead';",
        "for (var h = 6; h <= 24; h += 6) { }",
    ],
)
def test_lead_literal_positive_control(bad: str) -> None:
    """Every spelling a typed lead actually arrives in — comparison, list, prose, loop."""
    assert LEAD_LITERAL.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "head.appendChild(el('span', 'badge-pill', lead.lead_h + '-hour lead'));",
        "var pairs = Math.round(nTest * totalDays / testDays);",
        "if (!isFinite(n)) return null;",
        "improve.setAttribute('data-improve', tone);",
        "var x = 0.126;",
        "var slot = slots[idx];",
    ],
)
def test_lead_literal_stays_silent_on_the_real_js_shapes(sanctioned: str) -> None:
    """The shipped shapes, including a decimal that contains `12` and `6` as digits.

    `0.126` is here because a pattern without the dot in its look-around matches inside it,
    and a guard that fails the page for a decimal is a guard that gets deleted.
    """
    assert LEAD_LITERAL.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


def test_lead_literal_is_deliberately_not_applied_to_the_css_region() -> None:
    """WHY THE CSS REGION IS EXEMPT, proven rather than asserted in a comment.

    The spacing scale is named `--s-1` … `--s-10`, so `var(--s-6)` puts a bare `6` in the
    stylesheet with a non-word character in front of it and a non-word character behind it —
    exactly what this pattern matches. Running it over CSS would report a violation on a
    geometry token, and the guard, not the code, would be the thing that was wrong.

    So this is proven here instead: the pattern DOES match the token, which is the reason the
    scope above is the JS region alone. Applying it to CSS would not be stricter, it would be
    incorrect, and an incorrect guard gets suppressed and then deleted.
    """
    assert LEAD_LITERAL.search("padding: var(--s-6);") is not None
    assert LEAD_LITERAL.search("grid-template-columns: repeat(12, 1fr);") is not None
    assert LEAD_LITERAL.search("margin: var(--s-3) 0 0;") is None


# ==========================================================================================
# TASK 5.1 — no absolute value, no clamp, on a displayed improvement
# ==========================================================================================


def test_f7_js_region_takes_no_absolute_value(f7_code: dict[str, str]) -> None:
    """No absolute-value call in the F7 region outside a threshold comparison.

    F5's scanner, imported. A displayed improvement with its sign stripped tells the viewer a
    regression was a gain — and the fixture payload's 24-hour lead IS a regression, so this is
    a live case in the shipped data rather than a hypothetical one.
    """
    hits = forbidden_abs_uses(f7_code["forecast.js"])
    assert hits == [], (
        f"the F7 region takes an absolute value outside a threshold test: {hits}. A loss must "
        f"render as a loss, at the same visual weight as a win."
    )


def test_the_magnitude_fold_is_written_by_hand_and_is_actually_there(
    f7_code: dict[str, str],
) -> None:
    """PROOF: the sanctioned shape this guard tolerates is REALLY IN THE SHIPPED SOURCE.

    The region genuinely needs a magnitude — for a mean of absolute errors, where a miss two
    degrees high and a miss two degrees low are the same size of miss — and it folds it by
    hand, in the open, rather than reaching for the banned call. If that fold is ever replaced
    by the call, this proof goes red and says so instead of going quiet.
    """
    js = f7_code["forecast.js"]
    assert re.search(r"<\s*0\s*\?\s*-\s*\w+\s*:\s*\w+", js) is not None, (
        "the hand-written magnitude fold is gone from the F7 region; either the region no "
        "longer needs a magnitude or it now takes one the forbidden way"
    )
    assert ABS_CALL.search(js) is None, "the region calls the banned absolute-value helper"


@pytest.mark.parametrize(
    "bad",
    [
        "improve.textContent = fmt(Math.abs(pct), 1) + '%';",
        "var shown = Math.abs(delta);",
        "return Math.abs(a - b);",
        "parts.push(String(Math.abs(improvement)));",
    ],
)
def test_absolute_value_positive_control(bad: str) -> None:
    """Every shape in which a magnitude escapes to the DOM."""
    assert forbidden_abs_uses(bad), f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "return n < 0 ? -n : n;",
        "if (Math.abs(blendMae - inSample) < 0.01) return tieClause();",
        "var same = Math.abs(a - b) <= 0.05;",
        "improve.textContent = fmt(pct, 1, true);",
    ],
)
def test_absolute_value_stays_silent_on_the_hand_folded_and_threshold_shapes(
    sanctioned: str,
) -> None:
    """The hand-written fold and the two tie tests, all copied from the shipped shapes.

    A guard that fired on a tie threshold would be demanding the coincidence clause be
    deleted, and that clause is what stops the page claiming a win it did not measure.
    """
    assert forbidden_abs_uses(sanctioned) == [], f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — nothing in the region draws or names a spread
# ==========================================================================================

#: The four shapes that would turn a settled past measurement into a claim about a spread.
#: Case-insensitive substrings, so a class name, an element name and a variable all match.
SPREAD_SHAPE = re.compile(r"band|ribbon|envelope|whisker", re.I)


@pytest.mark.parametrize("name", REGION_NAMES)
def test_no_spread_shape_in_the_f7_region(name: str, f7_raw: dict[str, str]) -> None:
    """None of the four shapes appears in the F7 region — in code OR in a comment.

    Scanned RAW, which is stricter than F6's stripped scan and deliberate: F7's region has no
    comment that enumerates the forbidden shapes, so there is no legitimate reason for one of
    these words to be in this region at all, and a name written first in a comment is how it
    ends up in code.
    """
    hits = sorted({match.group(0).lower() for match in SPREAD_SHAPE.finditer(f7_raw[name])})
    assert hits == [], (
        f"{name}'s F7 region names a spread shape {hits}. Every figure in this region is a "
        f"past measurement over a stated window; a spread would claim something else."
    )


def test_spread_shape_guard_can_see_a_real_hit_in_this_very_file(f7_raw: dict[str, str]) -> None:
    """PROOF 4: the pattern matches REAL content in `forecast.js`, outside the F7 region.

    F5 writes a `data-band` attribute on the forecast strip. That occurrence is real, is in
    the same file, and is outside F7's markers — so the pattern reporting zero hits inside the
    region is a fact about the region, not a pattern that cannot fire. A synthesized-only
    control could not tell those two apart, and telling them apart is the whole point.
    """
    whole = FORECAST_JS.read_text(encoding="utf-8")
    region = f7_raw["forecast.js"]
    outside = whole.replace(region, "", 1)

    assert SPREAD_SHAPE.search(outside) is not None, (
        "forecast.js no longer names any of the four shapes outside the F7 region; this "
        "real-content proof of the guard has gone stale and must be re-based, not deleted"
    )
    assert SPREAD_SHAPE.search(region) is None
    assert len(outside) < len(whole), "the region was not actually excised from the copy"


@pytest.mark.parametrize(
    "bad",
    [
        "block.appendChild(el('div', 'skill-band'));",
        '<div class="skill-ribbon"></div>',
        ".skill-envelope { background: var(--surface-2); }",
        "var whiskerTop = mid + spread;",
        "el('div', 'SKILL-BAND')",
    ],
)
def test_spread_shape_positive_control(bad: str) -> None:
    """Class, element, variable and capitalised spellings all caught."""
    assert SPREAD_SHAPE.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "var head = el('div', 'skill-lead-head');",
        '.skill-improve[data-improve="win"]  { color: var(--success); }',
        "<p class=\"skill-extrapolated-link\" id=\"skill-extrapolated-link\"></p>",
        ".skill-lead-head .badge-pill { flex: none; }",
    ],
)
def test_spread_shape_stays_silent_on_the_real_f7_markup(sanctioned: str) -> None:
    """Lines from the shipped region. A guard that fires on `badge-pill` is noise."""
    assert SPREAD_SHAPE.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — visibility is attribute-keyed CSS, never an inline display write
# ==========================================================================================

#: A script write to the inline `display` style, in every spelling that reaches an element:
#: the property assignment, the `setProperty` form, and a wholesale inline-style attribute.
#:
#: DELIBERATELY SCOPED TO A WRITE. A stylesheet rule `display: none` is the SANCTIONED
#: mechanism — the region uses `:empty` to collapse an unfilled node — so the bare property
#: name must not be the thing matched, or the guard would forbid the correct implementation.
INLINE_DISPLAY_WRITE = re.compile(
    r"\.\s*style\s*\.\s*display\s*="
    r"|setProperty\s*\(\s*['\"]\s*display\s*['\"]"
    r"|setAttribute\s*\(\s*['\"]style['\"]"
)


@pytest.mark.parametrize("name", REGION_NAMES)
def test_f7_region_writes_no_inline_display_style(name: str, f7_code: dict[str, str]) -> None:
    """Nothing in the region hides or reveals a node by writing an inline style.

    The page's architecture is "markup always present, visibility keyed on an attribute or on
    :empty". A script that reaches in and sets `display` bypasses the stylesheet, cannot be
    themed, and leaves the DOM in a state no selector describes.
    """
    hit = INLINE_DISPLAY_WRITE.search(f7_code[name])
    assert hit is None, (
        f"{name}'s F7 region writes an inline display style: {hit.group(0)!r}. Visibility is "
        f"the stylesheet's job — set or remove the attribute and let a selector do the rest."
    )


@pytest.mark.parametrize(
    "bad",
    [
        "node.style.display = 'none';",
        "link.style.display='block';",
        "node . style . display = 'none';",
        "node.style.setProperty('display', 'none');",
        "node.setAttribute('style', 'display:none');",
    ],
)
def test_inline_display_write_positive_control(bad: str) -> None:
    """Every spelling of the write, including the spaced and `setProperty` forms."""
    assert INLINE_DISPLAY_WRITE.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        ".skill-extrapolated-link:empty { display: none; }",
        ".skill-lead-head { display: flex; align-items: baseline; }",
        "block.classList.add('is-hidden');",
        "head.appendChild(improve);",
    ],
)
def test_inline_display_write_stays_silent_on_the_stylesheets_own_rules(sanctioned: str) -> None:
    """The `:empty` collapse and the flex row are the sanctioned mechanism, not violations."""
    assert INLINE_DISPLAY_WRITE.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — a state attribute is set when it holds, and ABSENT otherwise
# ==========================================================================================

#: F5's pattern covers `data-stale` and `data-synthetic` by name. F7 introduces `data-improve`,
#: `data-lead-h` and `data-zero-weight`, so a second, broader pattern covers any `data-*`
#: attribute written with an off value. Both run: the imported one cannot drift, and the local
#: one reaches F7's own attribute names.
#:
#: DELIBERATELY LIMITED TO `data-*`. `aria-pressed` and `aria-disabled` MUST carry the off
#: string — ARIA has no "absent means false" for a toggle — and a guard that fired on those
#: would be demanding an accessibility bug.
DATA_ATTR_OFF_WRITE = re.compile(
    r"""setAttribute\s*\(\s*(['"])data-[\w-]+\1\s*,\s*(['"])\s*(?:false|off|none|no)\s*\2"""
    r"""|dataset\s*\.\s*[\w$]+\s*=\s*(['"])\s*(?:false|off|none|no)\s*\3""",
    re.I,
)


@pytest.mark.parametrize("name", REGION_NAMES)
def test_f7_region_never_writes_a_state_attribute_to_its_off_value(
    name: str, f7_code: dict[str, str]
) -> None:
    """An absent attribute is the off state. The off string is never written.

    The stylesheet selects on the value that means "on"; writing the off string produces
    markup that looks like it is doing something and is inert. Both the imported pattern and
    F7's broader one are run, so neither a drift upstream nor a new attribute name here can
    open a hole.
    """
    code = f7_code[name]
    imported_hit = STATE_ATTR_OFF_VALUE.search(code)
    assert imported_hit is None, (
        f"{name} writes the off value into a state attribute: {imported_hit.group(0)!r}"
    )
    local_hit = DATA_ATTR_OFF_WRITE.search(code)
    assert local_hit is None, (
        f"{name}'s F7 region writes the off value into a data attribute: "
        f"{local_hit.group(0)!r}. Set it when the condition holds; leave it ABSENT otherwise."
    )


@pytest.mark.parametrize(
    "bad",
    [
        "improve.setAttribute('data-improve', 'false');",
        'block.setAttribute("data-extrapolated", "no");',
        "mark.setAttribute('data-zero-weight', 'off');",
        "block.dataset.improve = 'false';",
    ],
)
def test_state_attribute_off_value_positive_control(bad: str) -> None:
    """The off string in each spelling that reaches the DOM."""
    assert DATA_ATTR_OFF_WRITE.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "improve.setAttribute('data-improve', tone);",
        "block.setAttribute('data-lead-h', lead.lead_h);",
        "mark.setAttribute('data-zero-weight', 'true');",
        "b.setAttribute('aria-pressed', 'false');",
        "button.setAttribute('aria-disabled', 'true');",
    ],
)
def test_state_attribute_guard_stays_silent_on_the_real_f7_writes(sanctioned: str) -> None:
    """The shipped writes, plus the two ARIA lines that legitimately carry the off string."""
    assert DATA_ATTR_OFF_WRITE.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"
    assert STATE_ATTR_OFF_VALUE.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — the fabricated-vs-measured statement: ONE BOOLEAN, AND NOTHING ELSE
# ==========================================================================================

#: On a fixture payload the panel puts a FABRICATED backtest figure and a genuinely MEASURED
#: realized figure inside the same `.skill-lead`. The realized figure arrives from the real
#: archive by a separate request that no fixture replaces, and the page banner makes a claim
#: about the FORECAST, not about the archive — so the mixture is unremarked, and both readings
#: a viewer can take are wrong in opposite directions. `COPY_SYNTHETIC_MIXING` says which
#: figure is which, and this section pins HOW it is switched on.
#:
#: The whole risk of this change is a SECOND SOURCE OF TRUTH. A statement gated on anything
#: other than the boolean the banner itself reads can disagree with the banner — a page saying
#: "synthetic" at the top and nothing beside the numbers, or the reverse, calling measured
#: figures fabricated. So the gate is pinned as one shape, and the alternatives are banned by
#: name below.
MIXING_CONSTANT = "COPY_SYNTHETIC_MIXING"
MIXING_CLASS = "skill-realized-mixing"
MIXING_FIELD = "is_synthetic"

#: The shipped gate, whitespace-collapsed. Pinned as a whole statement rather than as a loose
#: `is_synthetic` search: the field could be read into a variable, ORed with a second flag, or
#: compared against a string, and every one of those still contains the field name.
MIXING_GATE = (
    "if (state.meta.is_synthetic) { "
    "realized.appendChild(el('p', 'skill-realized-mixing', COPY_SYNTHETIC_MIXING)); "
    "}"
)

#: Every other way the statement could be switched on. Each is a second source of truth that
#: could disagree with the banner, and the DOM reads are worse than the rest: they depend on
#: `applySynthetic()` having already run, so a render-order change would silently drop the
#: statement while the banner stayed up.
SECOND_SOURCE_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("the attribute read back off the DOM", re.compile(r"getAttribute\s*\(\s*['\"]data-")),
    ("a dataset read of the same attribute", re.compile(r"dataset\s*\.\s*synthetic")),
    ("an attribute selector queried out of the DOM", re.compile(r"\[data-synthetic")),
    ("a string comparison instead of the boolean", re.compile(MIXING_FIELD + r"\s*[=!]==?\s*['\"]")),
    ("a second, locally derived flag", re.compile(r"\bisSynthetic\b|\bsynthetic[A-Z]\w*\b")),
    ("a fallback that ORs in another condition", re.compile(MIXING_FIELD + r"\s*\|\|")),
)


def test_the_mixing_statement_is_gated_on_meta_is_synthetic_alone(
    f7_code: dict[str, str],
) -> None:
    """THE ONE ASSERTION THIS SECTION EXISTS FOR: one field, read once, as a boolean.

    `state.meta.is_synthetic` is the SAME field `applySynthetic()` reads for the page banner
    (`frontend/forecast.js`, §3.3). Reading it here and nowhere else is what makes it
    impossible for the banner and the statement to disagree about the same payload.
    """
    js = f7_code["forecast.js"]
    collapsed = re.sub(r"\s+", " ", js)
    assert MIXING_GATE in collapsed, (
        f"the fabricated-vs-measured statement is no longer gated by the pinned shape "
        f"{MIXING_GATE!r}. If the gate has genuinely changed it has to be re-argued: any other "
        f"gate is a second source of truth that can disagree with the page banner."
    )
    occurrences = len(re.findall(re.escape(MIXING_FIELD), js))
    assert occurrences == 1, (
        f"{MIXING_FIELD!r} is read {occurrences} times in the F7 region. Exactly one read, in "
        f"the gate above — a second read is a second decision that can go the other way."
    )
    assert js.count(MIXING_CONSTANT) == 2, (
        f"{MIXING_CONSTANT} appears {js.count(MIXING_CONSTANT)} times, not twice (its "
        f"declaration in the pinned copy block and the single gated use)"
    )
    assert js.count(MIXING_CLASS) == 1, (
        f"the {MIXING_CLASS!r} node is built {js.count(MIXING_CLASS)} times; the statement is "
        f"built once per lead block, by the one gated call"
    )


@pytest.mark.parametrize(
    ("what", "pattern"), SECOND_SOURCE_SHAPES, ids=[what for what, _ in SECOND_SOURCE_SHAPES]
)
def test_no_second_source_of_truth_gates_the_statement(
    what: str, pattern: re.Pattern[str], f7_code: dict[str, str]
) -> None:
    """No DOM read, no second flag, no string compare, no OR-ed fallback anywhere in F7."""
    found = pattern.search(f7_code["forecast.js"])
    assert found is None, (
        f"{what} appears in the F7 region ({found.group(0)!r} if found) — the statement, or "
        f"something beside it, is deciding "
        f"'is this payload fabricated?' a second time"
    )


@pytest.mark.parametrize(
    ("what", "pattern", "bad"),
    [
        (w, p, b)
        for (w, p), b in zip(
            SECOND_SOURCE_SHAPES,
            [
                "if (document.documentElement.getAttribute('data-synthetic') === 'true') {",
                "if (document.documentElement.dataset.synthetic) {",
                "var on = document.querySelector('[data-synthetic=\"true\"]');",
                "if (state.meta.is_synthetic === 'true') {",
                "var isSynthetic = state.meta.is_synthetic; if (syntheticMode) {",
                "if (state.meta.is_synthetic || state.history.is_fixture) {",
            ],
        )
    ],
    ids=[what for what, _ in SECOND_SOURCE_SHAPES],
)
def test_second_source_of_truth_positive_control(
    what: str, pattern: re.Pattern[str], bad: str
) -> None:
    """Each banned shape proven visible on its own; a broken one cannot hide behind the rest."""
    assert pattern.search(bad) is not None, f"the {what} pattern cannot see {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "if (state.meta.is_synthetic) {",
        "realized.appendChild(el('p', 'skill-realized-mixing', COPY_SYNTHETIC_MIXING));",
        "var units = state.meta.units;",
    ],
)
def test_second_source_guard_stays_silent_on_the_shipped_gate(sanctioned: str) -> None:
    """The correct implementation trips none of the six. A guard that fired on it would be
    demanding the defect back."""
    for _, pattern in SECOND_SOURCE_SHAPES:
        assert pattern.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


def test_the_mixing_gate_pin_can_see_a_rewritten_gate(f7_code: dict[str, str]) -> None:
    """POSITIVE CONTROL for the pin: the same containment check, over a tampered region.

    Run in memory, on the extracted string. `frontend/` is never opened for writing.
    """
    collapsed = re.sub(r"\s+", " ", f7_code["forecast.js"])
    assert MIXING_GATE in collapsed, "the control is stale; the real gate is already gone"
    tampered = collapsed.replace(
        "if (state.meta.is_synthetic) {",
        "if (state.meta.is_synthetic || true) {",
        1,
    )
    assert MIXING_GATE not in tampered, (
        "the gate pin cannot tell a widened gate from the real one"
    )


def test_the_statement_is_absent_rather_than_emptied_on_a_real_payload(
    f7_code: dict[str, str], f7_raw: dict[str, str]
) -> None:
    """ABSENT MEANS ABSENT — no empty node, no placeholder, no dash, no display write.

    The node is BUILT inside the gate, so on a real payload it is never created. There is
    therefore nothing to hide: no `textContent = ''` reset for this class, no dash, and no
    script-written visibility, which the region-wide inline-display guard also covers.
    """
    js = f7_code["forecast.js"]
    gate_at = js.find("state.meta." + MIXING_FIELD)
    assert gate_at != -1, "the gate is gone from the F7 region"
    class_at = js.find(MIXING_CLASS)
    assert class_at != -1, f"the {MIXING_CLASS!r} node is gone from the F7 region"
    assert gate_at < class_at, (
        "the statement node is built before the field that gates it is read — it is not "
        "inside the gate at all"
    )
    css = f7_raw["forecast.css"]
    assert MIXING_CLASS in css, "the statement has no rule in the F7 CSS region"
    for placeholder in ("'—'", '"—"', "'n/a'", '"n/a"', "'-'"):
        assert placeholder not in js, (
            f"a placeholder {placeholder} appears in the F7 region; an absent statement is an "
            f"absent node, never a node carrying a dash"
        )


def test_the_statement_borrows_the_pages_existing_synthetic_tone(f7_raw: dict[str, str]) -> None:
    """The danger token, once, and no second green.

    "Fabricated" already has a colour on this page — the frame and the banner both use
    `--danger` (`frontend/tokens.css`). Reusing it means the word looks the same wherever the
    page says it. The `--success` count is asserted here too so this rule cannot be the second
    green the sibling guard forbids.
    """
    css = f7_raw["forecast.css"]
    rule = re.search(r"\." + MIXING_CLASS + r"\s*\{([^}]*)\}", css)
    assert rule is not None, f"the .{MIXING_CLASS} rule is gone from the F7 CSS region"
    assert "var(--danger)" in rule.group(1), (
        f"the .{MIXING_CLASS} rule no longer carries the page's synthetic tone: "
        f"{rule.group(1)!r}"
    )
    assert SUCCESS_TOKEN not in rule.group(1), "the statement rule spends the green"
    assert css.count(SUCCESS_TOKEN) <= 1, (
        f"the F7 CSS region now names {SUCCESS_TOKEN} more than once"
    )
    assert "data-synthetic" not in css, (
        "the F7 CSS region gates on the data-synthetic attribute — that is a second gate, "
        "keyed off the DOM, that can disagree with the renderer's one boolean"
    )


# ==========================================================================================
# TASK 5.1 — the green is spent once, and the stylesheet speaks no prose
# ==========================================================================================

SUCCESS_TOKEN = "--success"

#: A `content:` declaration, with the property name guarded against `justify-content`,
#: `align-content` and the `max-content` keyword by a look-behind that rejects `-` and word
#: characters. Without it the guard fires on layout code and gets deleted.
CSS_CONTENT_DECLARATION = re.compile(r"(?<![\w-])content\s*:\s*([^;}\n]*)")

#: `content: ""` — a decorative empty box. It says nothing to a screen reader and nothing to a
#: reader, so it is not prose and is not a violation.
EMPTY_CONTENT_VALUE = re.compile(r"""^(['"])\s*\1$""")


def content_prose(css: str) -> list[str]:
    """Every `content:` declaration whose value would put words or data on the page.

    Generated content is invisible to selection, to copy-and-paste and to most assistive
    technology, so a claim made in a stylesheet is a claim the page cannot be audited for.
    Every sentence in this panel is composed in `forecast.js`, where the copy module pins it.
    """
    found: list[str] = []
    for match in CSS_CONTENT_DECLARATION.finditer(css):
        value = match.group(1).strip().rstrip(";").strip()
        if EMPTY_CONTENT_VALUE.match(value):
            continue
        found.append(match.group(0).strip())
    return found


def test_success_token_appears_at_most_once_in_the_f7_css_region(f7_raw: dict[str, str]) -> None:
    """The green is spent on exactly one declaration, or not at all.

    A second green — a soft fill, a "fresh weights" badge, a tick — would make the panel read
    as an endorsement. The tone token belongs to the improvement figure alone, and only when
    the improvement is genuinely a win; freshness is not an achievement.
    """
    css = f7_raw["forecast.css"]
    assert len(css) >= MINIMUM_F7_REGION_BYTES["forecast.css"], "the CSS region read as a stub"
    count = css.count(SUCCESS_TOKEN)
    assert count <= 1, (
        f"the F7 CSS region names {SUCCESS_TOKEN} {count} times. One declaration, on the win "
        f"state of the improvement figure, and nowhere else."
    )


def test_success_token_counter_positive_control(f7_raw: dict[str, str]) -> None:
    """The same counting expression, over a region with a second green planted, must exceed 1.

    A count of zero and a count taken over an empty string look identical in a passing test,
    so the plant is run through the identical `str.count` call the assertion uses.
    """
    css = f7_raw["forecast.css"]
    poisoned = css + f"\n.skill-weights-fresh {{ color: var({SUCCESS_TOKEN}); }}\n"
    assert poisoned.count(SUCCESS_TOKEN) > 1, "the counter cannot see a planted second green"
    assert css.count(SUCCESS_TOKEN) <= 1, "the unplanted region was not clean"


def test_f7_css_region_carries_no_content_prose(f7_raw: dict[str, str]) -> None:
    """No words, no payload data, no counters injected from the stylesheet."""
    hits = content_prose(f7_raw["forecast.css"])
    assert hits == [], (
        f"the F7 CSS region speaks prose through generated content: {hits}. Every sentence in "
        f"this panel is composed in forecast.js, where it can be read, tested and pinned."
    )


@pytest.mark.parametrize(
    "bad",
    [
        '.skill-improve::after { content: " measured"; }',
        ".skill-lead::before { content: attr(data-lead-h); }",
        ".skill-improve[data-improve='win']::after { content: 'better'; }",
        ".skill-lead::before { content: counter(lead); }",
    ],
)
def test_content_prose_positive_control(bad: str) -> None:
    """Words, an attribute read and a counter — every way a stylesheet can say something."""
    assert content_prose(bad), f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        '.skill-lead-head::after { content: ""; }',
        ".skill-lead-head { display: flex; justify-content: space-between; }",
        ".skill-weights-note { width: max-content; }",
        ".skill-lead { align-content: start; }",
    ],
)
def test_content_prose_stays_silent_on_layout_and_the_empty_box(sanctioned: str) -> None:
    """`justify-content`, `align-content`, `max-content` and the empty decorative box.

    A naive `content:` search matches inside all four. A guard that fails a flex row is a
    guard that gets suppressed, and a suppressed guard catches nothing at all.
    """
    assert content_prose(sanctioned) == [], f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.2 — PROOF 5: the gate goes RED on a token injected inside the F7 region
# ==========================================================================================

#: A different banned token per file — an underscored key name, a plain word, and the
#: plus-or-minus character. One injection shape proving one alternative would be weaker.
F7_INJECTIONS = {
    "forecast.html": banned_word(BANNED_ALTERNATIVES[2]),
    "forecast.js": banned_word(BANNED_ALTERNATIVES[4]),
    "forecast.css": PLUS_MINUS,
}


@pytest.mark.parametrize("name", REGION_NAMES)
def test_gate_goes_red_on_a_token_injected_inside_the_f7_region(
    name: str, f7_raw: dict[str, str], tmp_path: Path, grep_binary: str
) -> None:
    """Copy the file in memory, poison the F7 region, prove the gate red — and the file intact.

    Injecting INSIDE the region rather than appending at end of file is the point: it proves
    the gate reaches the bytes F7 actually added, not merely the file's tail. The mutation
    lives on a string and reaches disk only under `tmp_path`; THE REAL FILE IS NEVER OPENED
    FOR WRITING, and its sha256 is compared before and after to prove it.

    The unpoisoned copy is proven clean FIRST, which is what makes this a control rather than
    an anecdote: a red below cannot then be blamed on the copy or on `tmp_path`.
    """
    path = REGION_DELIMITERS[name][0]
    original = path.read_text(encoding="utf-8")
    digest_before = hashlib.sha256(path.read_bytes()).hexdigest()

    baseline = tmp_path / f"baseline-{name}"
    baseline.write_text(original, encoding="utf-8")
    baseline_verdict, baseline_detail = gate_verdict(grep_binary, BANLIST_PATTERN, baseline)
    assert baseline_verdict == CLEAN, (
        f"the untouched copy of {name} already matches ({baseline_detail}); the injection "
        f"below would prove nothing"
    )

    region = f7_raw[name]
    assert region in original, f"{name}: the region is not a substring of the file it came from"
    token = F7_INJECTIONS[name]
    midpoint = len(region) // 2
    poisoned_region = region[:midpoint] + f" {token} " + region[midpoint:]
    mutated_text = original.replace(region, poisoned_region, 1)
    assert mutated_text != original, "the injection did not change the text"

    mutated = tmp_path / f"mutated-{name}"
    mutated.write_text(mutated_text, encoding="utf-8")
    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, mutated)

    assert verdict == MATCHED, (
        f"THE GATE CANNOT FAIL: a banned token injected into {name}'s F7 region still produced "
        f"verdict {verdict!r} ({detail!r}). A guard that cannot fail is not a guard."
    )
    assert token in detail, f"the gate fired, but not on the injected token: {detail!r}"
    assert BANLIST_RE.search(mutated_text) is not None, "the re cross-check missed the injection"

    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest_before, (
        f"{path} changed during the control — the real file must never be written"
    )


@pytest.mark.parametrize("name", REGION_NAMES)
def test_the_region_guards_go_red_on_a_shape_injected_inside_the_f7_region(
    name: str, f7_raw: dict[str, str]
) -> None:
    """The region-scoped guards fire too, on the same in-region injection, through their code.

    The ban-list gate above shells out to `grep`; these run in-process. Both must be proven,
    because a region that the gate can reach is not automatically a region these patterns are
    reading — the fixtures could still be handing them a stub.
    """
    region = f7_raw[name]
    midpoint = len(region) // 2
    poisoned = region[:midpoint] + "\nskill-envelope\n" + region[midpoint:]

    assert SPREAD_SHAPE.search(poisoned) is not None, "the shape guard missed an in-region plant"
    assert SPREAD_SHAPE.search(region) is None, "the unplanted region was not clean"


def test_the_js_region_guards_go_red_on_an_in_region_javascript_injection(
    f7_code: dict[str, str],
) -> None:
    """The JS-only guards fire on plants placed in a copy of the real stripped region."""
    js = f7_code["forecast.js"]
    assert baked_payload_literals(js + "\nvar best = 'HRRR';\n"), "payload guard missed a plant"
    assert LEAD_LITERAL.search(js + "\nif (lead.lead_h === 24) { }\n"), "lead guard missed a plant"
    assert forbidden_abs_uses(js + "\nvar shown = Math.abs(pct);\n"), "abs guard missed a plant"
    assert INLINE_DISPLAY_WRITE.search(js + "\nnode.style.display = 'none';\n") is not None
    assert DATA_ATTR_OFF_WRITE.search(js + "\nn.setAttribute('data-improve', 'false');\n")


# ==========================================================================================
# TASK 5.2 — PROOF 6: F6's region is byte-for-byte what it was before F7 landed
# ==========================================================================================

#: Length in UTF-8 bytes and full sha256 of F6's own region slice, captured from the working
#: tree BEFORE F7's regions were inserted, and verified byte-identical to the saved `.pre`
#: captures at the time this module was written. F7's JS and CSS are inserted ABOVE F6's
#: banner precisely so these do not move; if either changes, F7 landed inside F6's region and
#: F6's own guards are now reading F7's code.
F6_REGION_FINGERPRINT: dict[str, tuple[int, str]] = {
    "forecast.js": (
        13515,
        "6116d86cc5fbc7a2085a6fb2fddf0fecaac14a5bd2863650bed0388a6b2c1210",
    ),
    "forecast.css": (
        6047,
        "c31b2d45b9571d2fbdeda2aec12da1ac13bca262a64a8fa388d24bf2610fe788",
    ),
}


def f6_region_for(name: str) -> str:
    """F6's own slice, taken with F6's own imported extractor — never a re-implementation."""
    path = REGION_DELIMITERS[name][0]
    text = path.read_text(encoding="utf-8")
    if name == "forecast.html":
        return f6_region_from_marker(text, "<!--", "</section>")
    return f6_region_from_marker(text, "/*")


@pytest.mark.parametrize("name", REGION_NAMES)
def test_f6_region_still_extracts_above_its_own_floors(name: str) -> None:
    """F6's extractor still finds a substantial slice in each file, using F6's own floors.

    Run through the IMPORTED extractor and the IMPORTED floors. If F7's insertion had moved or
    broken F6's banner this would fail here rather than silently in F6's module, and it would
    name which file.
    """
    region = f6_region_for(name)
    floor = F6_MINIMUM_REGION_BYTES[name]
    assert len(region) >= floor, (
        f"{name}: F6's region now extracts {len(region)} bytes, under its own {floor} floor — "
        f"F7's insertion has disturbed the history region"
    )
    assert HISTORY_MARKER in region.upper()


@pytest.mark.parametrize("name", sorted(F6_REGION_FINGERPRINT))
def test_f6_region_is_byte_identical_to_the_pre_f7_capture(name: str) -> None:
    """F6's JS and CSS regions are unchanged, to the byte, from before F7 landed.

    Length and full digest, both. Length alone would miss an equal-length substitution and a
    digest alone would produce an unreadable failure message; together they say what changed
    and by how much.
    """
    expected_length, expected_digest = F6_REGION_FINGERPRINT[name]
    payload = f6_region_for(name).encode("utf-8")

    assert len(payload) == expected_length, (
        f"F6's {name} region is now {len(payload)} bytes, not {expected_length}. F7 must sit "
        f"ABOVE F6's banner; a region that grew means F7 code landed inside it, where F6's own "
        f"guards will read it and F6's floors no longer describe it."
    )
    assert hashlib.sha256(payload).hexdigest() == expected_digest, (
        f"F6's {name} region is the right length but not the right bytes — something was "
        f"substituted inside the history region"
    )


#: The pre-F7 captures, if this checkout still has the scratchpad they were written to. An
#: OPTIONAL cross-check: the fingerprint above is the durable pin and always runs, so nothing
#: here is vacuous when these files are gone.
F6_PRE_CAPTURES: dict[str, Path] = {
    "forecast.js": Path(
        "/private/tmp/claude-501/-Users-sanjaygupta-Projects-Bhar"
        "/44424d57-2c7f-440c-a0b3-2de306202dcb/scratchpad/f6_region_forecast.js.pre"
    ),
    "forecast.css": Path(
        "/private/tmp/claude-501/-Users-sanjaygupta-Projects-Bhar"
        "/44424d57-2c7f-440c-a0b3-2de306202dcb/scratchpad/f6_region_forecast.css.pre"
    ),
}


@pytest.mark.parametrize("name", sorted(F6_PRE_CAPTURES))
def test_f6_region_matches_the_saved_pre_capture_when_it_is_present(name: str) -> None:
    """The same claim again, against the saved capture rather than a recorded digest.

    Skipped where the capture is gone — a session scratchpad does not survive the checkout.
    The skip is safe ONLY because the fingerprint test above makes the identical assertion
    from a value committed alongside this file; without that pin this would be a guard that
    passes by not running, which is the failure mode this whole module exists to prevent.
    """
    capture = F6_PRE_CAPTURES[name]
    if not capture.is_file():
        pytest.skip(f"the pre-F7 capture {capture.name} is not in this checkout")
    assert capture.read_bytes() == f6_region_for(name).encode("utf-8"), (
        f"F6's {name} region differs from the pre-F7 capture"
    )


NESTED_RUN_FLAG = "BHAR_F7_S5_NESTED"

TEST_COUNT = re.compile(r"(\d+) passed")


def test_f6_guard_module_still_passes() -> None:
    """F6's guard module is executed and required to pass, with a non-zero test count.

    Asserting the count matters as much as asserting the exit status: pytest exits 0 when it
    collects nothing under some invocations, and "the F6 guards still pass" would then mean
    "the F6 guards did not run". Run in a subprocess so this module's own collection is not
    re-entered, with a flag set against any future recursion.
    """
    if os.environ.get(NESTED_RUN_FLAG):
        pytest.skip("already inside the nested guard run")

    target = REPO / "tests" / "test_forecast_history_ui_guards.py"
    assert target.is_file(), f"{target} is missing — F6's guards cannot be re-run"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(target)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, NESTED_RUN_FLAG: "1"},
    )
    output = f"{result.stdout}\n{result.stderr}".strip()
    assert result.returncode == 0, f"F6's guard module no longer passes:\n{output}"

    matched = TEST_COUNT.search(output)
    assert matched is not None, f"could not read a test count from the nested run:\n{output}"
    assert int(matched.group(1)) > 0, "the nested run passed by collecting nothing"
