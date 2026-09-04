"""F6 Stream 5 — the back-arrow history region's own guards, and the proofs they can fail.

WHY THIS FILE EXISTS AND WHY IT IMPORTS RATHER THAN RE-DERIVES
--------------------------------------------------------------
F5 left three guard modules that are protected: `tests/test_forecast_ui_guards.py`,
`tests/test_forecast_api_guards.py` and `tests/test_live_guards.py`. F6 appends a whole
region to all three shipped frontend files, so it needs its own module — and the single most
likely way for that module to be worthless is for it to RE-TYPE F5's patterns slightly
differently and then enforce something subtly other than what it claims.

So the BANLIST pattern, the comment strippers, the payload-literal scanner, the
absolute-value scanner, the grep runner and its exit-status classifier are all IMPORTED from
`tests/test_forecast_ui_guards.py`. That file is read-only from here; nothing below writes to
it, and a drift in it fails this module loudly rather than silently diverging from it.

THE FAILURE MODE THIS STREAM EXISTS TO PREVENT
----------------------------------------------
Three guards in this project looked real and were not: F1's gate, F4's phantom AST check, and
the demo team's `prefers-color-scheme` split. Each greped or parsed something that could not
produce a hit, and each reported green forever. So every guard here carries a POSITIVE
CONTROL — a synthesized violation the pattern is proven to match — and the haystack itself is
asserted: the files exist, are non-empty, are exactly three, and the extracted history region
is proven to be a real, substantial slice of each rather than an empty string produced by a
marker that has been re-worded.

    PROOF 1 — the haystack is real. `test_haystack_*` and `test_region_*` assert the three
    files exist above a byte floor, that the region extractor finds a real slice of each
    above its own floor, and that a MISSING MARKER RAISES rather than yielding the whole
    document or an empty one. A typo'd marker scans nothing and passes silently; that exact
    failure is named in the `forecast-api` and `demo-overview` retrospectives.

    PROOF 2 — the patterns fire. Every guard below is fed a deliberately bad sample and
    proven to match it, and where it could plausibly over-fire it is fed the real sanctioned
    shape and proven silent.

    PROOF 3 — the BANLIST gate goes red on the F6 content. Each file is copied in memory, a
    banned token is injected INSIDE THE HISTORY REGION, and the gate is re-run over the copy
    through the same `gate_verdict` the real gate uses. The real file's digest is compared
    before and after; `frontend/` is never opened for writing.

    PROOF 4 — the shape guard can see a real hit. `forecast.js` names all four forbidden
    shapes (band, ribbon, envelope, whisker) in the comment that FORBIDS them. The raw region
    matches all four and the comment-stripped region matches none, so this guard is
    demonstrably looking at real content and demonstrably able to see a hit — it just
    declines to count a prohibition as a violation.

    PROOF 5 — the off-limits diff guard observes real modifications. The same `git diff
    --numstat` invocation the guard uses is pointed at `frontend/forecast.js`, which F6
    genuinely rewrote, and is asserted to report a non-zero change. An empty result from a
    typo'd pathspec and an empty result from an unmodified path are indistinguishable
    otherwise, and that is precisely the vacuous form.

SCOPE AND SAFETY
----------------
Nothing here starts a server, opens a socket, or writes to `frontend/`, `backend/`, `score/`,
`docs/` or `data/`. Every mutation happens on an in-memory string or under `tmp_path`. The
only files opened at all outside `tmp_path` are opened for reading.

No banned string is typed literally in this source, for the same reason F5 does not type one:
a future run of the BANLIST gate over `tests/` would otherwise trip on its own guard. The
tokens are imported from F5, which assembles them from escapes.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_forecast_ui_guards import (
    ABS_CALL,
    ALTERNATIVE_IDS,
    BANLIST_PATTERN,
    BANLIST_RE,
    BANNED_ALTERNATIVES,
    CLEAN,
    CSS_THEME_ATTRIBUTE_BLOCK,
    ERROR,
    FORECAST_CSS,
    FORECAST_HTML,
    FORECAST_JS,
    FRONTEND,
    MATCHED,
    MINIMUM_SCANNED_BYTES,
    MINUS_SUBSTITUTION,
    MODEL_TOKEN_DECLARATION_PATTERN,
    PLUS_MINUS,
    REPO,
    SCANNED,
    TRUE_MINUS,
    baked_payload_literals,
    banned_word,
    forbidden_abs_uses,
    gate_verdict,
    grep_lines,
    parse_numstat,
    strip_css,
    strip_html,
    strip_js,
)

# ==========================================================================================
# The history region — where it starts, where it ends, and how that is proven non-empty
# ==========================================================================================

#: The banner all three files carry at the head of the F6 append. Matched case-insensitively
#: because the HTML spells it in sentence case and the other two in capitals.
HISTORY_MARKER = "BACK-ARROW HISTORY REGION"

#: Per-file raw region floors. Generous — the point is to catch an empty or near-empty slice
#: produced by a re-worded marker, not to pin the region's exact size.
MINIMUM_REGION_BYTES = {"forecast.html": 1500, "forecast.js": 6000, "forecast.css": 2500}

#: The same floors after comment stripping. Every static guard below reads the stripped text,
#: so a stripper that ate the whole region would make all of them vacuous. This is what stops
#: that: the code that survives stripping is asserted to be substantial in its own right.
MINIMUM_REGION_CODE_BYTES = {"forecast.html": 400, "forecast.js": 4000, "forecast.css": 1200}


@pytest.fixture(scope="session")
def grep_binary() -> str:
    """The `grep` the gate shells out to — or a clean skip where there is none.

    Declared here rather than imported from `tests/test_forecast_ui_guards.py` for one
    mechanical reason: pytest resolves a fixture by the name bound in the module, and an
    imported name shadowed by a same-named test parameter is a lint error. There is no
    pattern here to drift — the whole body is a PATH lookup — so nothing is re-derived. The
    BANLIST pattern, the strippers and the scanners, all of which COULD drift, are imported.
    """
    found = shutil.which("grep")
    if found is None:
        pytest.skip("grep is not available on PATH")
    return found


def region_from_marker(text: str, opener: str, closer: str | None = None) -> str:
    """The slice of `text` starting at the comment that carries `HISTORY_MARKER`.

    `opener` is the comment delimiter to rewind to, so the region begins with a BALANCED
    comment and the strippers can remove it. Starting at the marker word itself would leave a
    dangling `*/` or `-->`, the stripper would not recognise the block, and every
    comment-stripped guard below would then scan prose it was never meant to see — which is
    how PROOF 4 would quietly stop meaning anything.

    `closer`, when given, ends the region at the first occurrence AFTER the marker (the HTML
    region is one `<section>`); when omitted the region runs to end of file, which is what the
    F6 appends to `forecast.js` and `forecast.css` are.

    Raises rather than returning "" or the whole document when the marker is gone: a silent
    empty region is the vacuous-scan bug, and a silent whole-document region would make the
    region-scoped guards fire on unrelated F5 content.
    """
    index = text.upper().find(HISTORY_MARKER)
    assert index != -1, (
        f"the {HISTORY_MARKER!r} banner is gone — every region-scoped guard in this module "
        f"would be scanning nothing, and a scan of nothing reports exactly the same green"
    )
    start = text.rfind(opener, 0, index)
    assert start != -1, f"no {opener!r} precedes the region banner; the region is unbounded"
    if closer is None:
        return text[start:]
    stop = text.find(closer, index)
    assert stop != -1, f"no {closer!r} closes the region after the banner"
    return text[start : stop + len(closer)]


@pytest.fixture(scope="module")
def region_raw() -> dict[str, str]:
    """The three history regions as written, comments included."""
    return {
        "forecast.html": region_from_marker(
            FORECAST_HTML.read_text(encoding="utf-8"), "<!--", "</section>"
        ),
        "forecast.js": region_from_marker(FORECAST_JS.read_text(encoding="utf-8"), "/*"),
        "forecast.css": region_from_marker(FORECAST_CSS.read_text(encoding="utf-8"), "/*"),
    }


@pytest.fixture(scope="module")
def region_code(region_raw: dict[str, str]) -> dict[str, str]:
    """The three history regions reduced to code: comments out, string literals kept."""
    return {
        "forecast.html": strip_html(region_raw["forecast.html"]),
        "forecast.js": strip_js(region_raw["forecast.js"]),
        "forecast.css": strip_css(region_raw["forecast.css"]),
    }


@pytest.fixture(scope="module")
def whole_code() -> dict[str, str]:
    """The three whole files reduced to code, for the guards that are file-wide by contract."""
    return {
        "forecast.html": strip_html(FORECAST_HTML.read_text(encoding="utf-8")),
        "forecast.js": strip_js(FORECAST_JS.read_text(encoding="utf-8")),
        "forecast.css": strip_css(FORECAST_CSS.read_text(encoding="utf-8")),
    }


# ==========================================================================================
# TASK 5.1 — PROOF 1: the haystack is real, and so is the region cut out of it
# ==========================================================================================


def test_haystack_is_exactly_three_files_and_f6_added_no_fourth() -> None:
    """Three scanned files, by name, no more and no fewer.

    F6 was a set of APPENDS. If it had grown a fourth page file — `history.html`, a second
    script — that file would carry the region's content and none of the guards below would
    look at it, so the module would report green over a page half of which was never scanned.
    """
    assert len(SCANNED) == 3, f"expected exactly 3 scanned files, got {len(SCANNED)}: {SCANNED}"
    assert len(set(SCANNED)) == 3, f"the scanned set contains a duplicate: {SCANNED}"
    assert [path.name for path in SCANNED] == ["forecast.html", "forecast.js", "forecast.css"]
    assert all(path.parent == FRONTEND for path in SCANNED), SCANNED


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_haystack_each_file_exists_and_is_not_empty(path: Path) -> None:
    """Each scanned path exists under `frontend/` and carries real content.

    A TYPO'D PATH SCANS NOTHING AND PASSES SILENTLY. The byte floor is what distinguishes
    "read the shipped file and found nothing banned" from "read a stub, or nothing at all".
    """
    assert path.is_file(), f"{path} does not exist — every guard below it would be vacuous"
    size = path.stat().st_size
    assert size >= MINIMUM_SCANNED_BYTES, (
        f"{path.name} is {size} bytes, below the {MINIMUM_SCANNED_BYTES}-byte floor"
    )
    assert path.read_text(encoding="utf-8").strip(), f"{path.name} is whitespace only"


@pytest.mark.parametrize("name", ["forecast.html", "forecast.js", "forecast.css"])
def test_region_is_a_real_substantial_slice(name: str, region_raw: dict[str, str]) -> None:
    """The extracted region is a real slice of a real file, above a per-file byte floor.

    Every guard in Task 5.1 that says "in the history region" is only as good as this. An
    empty string satisfies "contains no banned token", "declares no model colour token" and
    "renders no band" all at once, and reports the same green as a clean region.
    """
    region = region_raw[name]
    floor = MINIMUM_REGION_BYTES[name]
    assert len(region) >= floor, (
        f"the {name} history region is {len(region)} bytes, below its {floor}-byte floor — "
        f"either the region shrank to a stub or the marker no longer bounds what it should"
    )
    assert HISTORY_MARKER in region.upper(), f"{name}: the region does not carry its own banner"


@pytest.mark.parametrize("name", ["forecast.html", "forecast.js", "forecast.css"])
def test_region_survives_comment_stripping_with_code_left(
    name: str, region_code: dict[str, str]
) -> None:
    """Comment-stripping the region leaves substantial CODE, not an empty string.

    The region opens with a long explanatory comment in all three files. A stripper that
    mis-lexed it would take the code with it, and every stripped-text guard below would then
    be scanning nothing while still passing.
    """
    stripped = region_code[name]
    floor = MINIMUM_REGION_CODE_BYTES[name]
    assert len(stripped) >= floor, (
        f"the stripped {name} history region is {len(stripped)} bytes, below its {floor}-byte "
        f"floor — the stripper has eaten the code, and every guard reading it is vacuous"
    )


def test_region_code_carries_its_landmarks(region_code: dict[str, str]) -> None:
    """Named landmarks from each region, asserted present after stripping.

    Cheap, specific insurance that what survived stripping is the F6 code and not, say, the
    tail of F5's file reached by a marker that moved.
    """
    html = region_code["forecast.html"]
    assert 'id="history-section"' in html
    assert 'id="day-pill"' in html

    js = region_code["forecast.js"]
    assert "renderHistory" in js
    assert "meta.best_single_model_by_lead" in js
    assert "leadsPresent" in js

    css = region_code["forecast.css"]
    assert ".history-section" in css
    assert 'html[data-history="ready"]' in css


def test_region_extractor_positive_control() -> None:
    """The extractor itself: proven to cut the right slice, and to RAISE on a missing marker.

    The third case is the important one. An extractor that answers "" for an absent marker
    turns every region-scoped guard into a no-op, and an extractor that answers the whole
    document turns them into false alarms on F5's content. It must do neither.
    """
    js_sample = "before();\n/* the BACK-ARROW HISTORY REGION banner */\nafter();\n"
    assert region_from_marker(js_sample, "/*") == (
        "/* the BACK-ARROW HISTORY REGION banner */\nafter();\n"
    )

    html_sample = "<p>a</p>\n<!-- back-arrow history region -->\n<section>x</section>\n<p>b</p>"
    assert region_from_marker(html_sample, "<!--", "</section>") == (
        "<!-- back-arrow history region -->\n<section>x</section>"
    )

    with pytest.raises(AssertionError):
        region_from_marker("a document with no banner at all", "/*")
    with pytest.raises(AssertionError):
        region_from_marker("BACK-ARROW HISTORY REGION with no opener before it", "/*")
    with pytest.raises(AssertionError):
        region_from_marker("/* BACK-ARROW HISTORY REGION */ never closed", "/*", "</section>")


# ==========================================================================================
# TASK 5.1 — the BANLIST gate still holds after F6's additions
# ==========================================================================================


def test_banlist_pattern_was_imported_not_retyped() -> None:
    """The pattern under test is F5's, not a copy of it that has drifted.

    Asserted rather than assumed because "the guard enforces a slightly different rule than
    the one it names" is the quietest way for a gate to stop being the gate.
    """
    assert len(BANNED_ALTERNATIVES) == 11, f"expected 11 alternatives, got {BANNED_ALTERNATIVES}"
    assert BANLIST_PATTERN == "|".join(BANNED_ALTERNATIVES)
    assert BANLIST_RE.pattern == BANLIST_PATTERN
    assert PLUS_MINUS in BANNED_ALTERNATIVES, "the plus-or-minus alternative is gone"


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_banlist_gate_is_still_clean_after_the_history_additions(
    path: Path, grep_binary: str
) -> None:
    """F6 appended to all three files; none of them may now match the BANLIST pattern.

    Exit 1 (no match) is the only passing outcome. Exit 2 — an unreadable or absent path — is
    an ERROR and fails here, because an errored scan is not a clean scan and treating it as
    one is the vacuous pass this module exists to make impossible.
    """
    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, path)

    assert verdict != ERROR, (
        f"the gate could not scan {path.name}: {detail}. grep exit 2 means the file was never "
        f"read — a failure, never a pass"
    )
    assert verdict == CLEAN, (
        f"{path.name} contains banned content after F6's additions:\n{detail}\n"
        f"The history region states measured, settled history — never a hedge on it."
    )

    text = path.read_text(encoding="utf-8")
    assert len(text) >= MINIMUM_SCANNED_BYTES, "the cross-check read a stub"
    hit = BANLIST_RE.search(text)
    assert hit is None, f"the re cross-check disagrees with grep on {path.name}: {hit!r}"


@pytest.mark.parametrize("alternative", BANNED_ALTERNATIVES, ids=ALTERNATIVE_IDS)
def test_banlist_positive_control_every_alternative_still_fires(
    alternative: str, tmp_path: Path, grep_binary: str
) -> None:
    """Positive control: each alternative matches ON ITS OWN, through the real gate.

    One case per alternative, not one case over a sample carrying all eleven: the latter
    stays green while a single branch is broken, because the other ten still fire.
    """
    word = banned_word(alternative)
    sample = tmp_path / "sample.txt"
    sample.write_text(f"ordinary prose\nand then {word} sitting in it\ntail\n", encoding="utf-8")

    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, sample)

    assert verdict == MATCHED, (
        f"the BANLIST pattern did not fire on alternative {alternative!r} (verdict {verdict}, "
        f"{detail!r}) — that branch would let its token through the gate"
    )
    assert word in detail, f"the gate matched, but not on the planted token: {detail!r}"


#: A different banned token per file: an underscored key name, a plain word, and the
#: plus-or-minus character. One injection shape proving one alternative would be weaker.
REGION_INJECTIONS = {
    "forecast.html": banned_word(BANNED_ALTERNATIVES[6]),
    "forecast.js": banned_word(BANNED_ALTERNATIVES[3]),
    "forecast.css": PLUS_MINUS,
}


@pytest.mark.parametrize("name", ["forecast.html", "forecast.js", "forecast.css"])
def test_banlist_positive_control_goes_red_on_an_injection_inside_the_region(
    name: str, region_raw: dict[str, str], tmp_path: Path, grep_binary: str
) -> None:
    """Copy the file in memory, inject a banned token INSIDE the F6 region, prove the gate red.

    Injecting inside the region rather than appending at end of file is the point: it proves
    the gate reaches the bytes F6 actually added, not merely the file's tail. The mutation
    lives on a string and reaches disk only under `tmp_path`; THE REAL FILE IS NEVER OPENED
    FOR WRITING, and its digest is compared before and after to prove it.

    The unmutated copy is proven clean FIRST, which is what makes this a control rather than
    an anecdote: a red below cannot then be blamed on the copy or on `tmp_path`.
    """
    paths = {
        "forecast.html": FORECAST_HTML,
        "forecast.js": FORECAST_JS,
        "forecast.css": FORECAST_CSS,
    }
    path = paths[name]
    original = path.read_text(encoding="utf-8")
    digest_before = hashlib.sha256(path.read_bytes()).hexdigest()

    baseline = tmp_path / f"baseline-{name}"
    baseline.write_text(original, encoding="utf-8")
    baseline_verdict, baseline_detail = gate_verdict(grep_binary, BANLIST_PATTERN, baseline)
    assert baseline_verdict == CLEAN, (
        f"the untouched copy of {name} already matches ({baseline_detail}); the injection "
        f"below would prove nothing"
    )

    region = region_raw[name]
    assert region in original, f"{name}: the region is not a substring of the file it came from"
    token = REGION_INJECTIONS[name]
    midpoint = len(region) // 2
    poisoned_region = region[:midpoint] + f" {token} " + region[midpoint:]
    mutated_text = original.replace(region, poisoned_region, 1)
    assert mutated_text != original, "the injection did not change the text"

    mutated = tmp_path / f"mutated-{name}"
    mutated.write_text(mutated_text, encoding="utf-8")

    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, mutated)

    assert verdict == MATCHED, (
        f"THE GATE CANNOT FAIL: a banned token injected into {name}'s history region still "
        f"produced verdict {verdict!r} ({detail!r}). A guard that cannot fail is not a guard."
    )
    assert token in detail, f"the gate fired, but not on the injected token: {detail!r}"
    assert BANLIST_RE.search(mutated_text) is not None, "the re cross-check missed the injection"

    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest_before, (
        f"{path} changed during the control — the real file must never be written"
    )


@pytest.mark.parametrize("name", ["forecast.html", "forecast.js", "forecast.css"])
def test_no_plus_or_minus_character_in_the_new_copy(name: str, region_raw: dict[str, str]) -> None:
    """U+00B1 appears nowhere in the F6 region — not in code, not in prose, not in a comment.

    Scanned RAW rather than stripped, deliberately: the ban is on the character reaching the
    page or the source at all. The design says "30-minute window" in words for exactly this
    reason. A plus-or-minus attached to a settled, observed value would claim a spread the
    backtest never computed.
    """
    region = region_raw[name]
    assert len(region) >= MINIMUM_REGION_BYTES[name], "the region read as a stub"
    assert PLUS_MINUS not in region, (
        f"{name}'s history region carries the plus-or-minus character at offset "
        f"{region.find(PLUS_MINUS)} — every value in this region is settled, not hedged"
    )


def test_no_plus_or_minus_positive_control(region_raw: dict[str, str]) -> None:
    """The same membership test, over a region with the character planted in it, must fire.

    Without this, "the character is not in the region" is indistinguishable from "the region
    is an empty string", which is the whole reason this module asserts its haystack.
    """
    poisoned = region_raw["forecast.js"] + f"\n// planted {PLUS_MINUS} 0.5\n"
    assert PLUS_MINUS in poisoned, "the membership test cannot see a planted character"
    assert BANLIST_RE.search(poisoned) is not None, "the BANLIST pattern missed the same plant"
    assert PLUS_MINUS not in region_raw["forecast.js"], "the unplanted region was not clean"


# ==========================================================================================
# TASK 5.1 — no payload literal, no lead literal, no model name typed into the page
# ==========================================================================================

#: The three archive leads, as bare numbers not part of a longer number or identifier. They
#: are the payload's `meta.leads_available`; typing one here would survive a refetch at a
#: different lead set and the page would then state a lead the archive does not carry.
LEAD_LITERAL = re.compile(r"(?<![\w.])(?:6|12|24)(?![\w.])")


def test_history_region_bakes_in_no_payload_literal(region_code: dict[str, str]) -> None:
    """No model name, no site name, no cell count in the F6 region.

    F5's scanner, imported rather than re-derived. A refit that drops a model, or a move to a
    second site, must not leave a stale name behind in the past view — the page would then
    state something the history document does not.
    """
    hits = baked_payload_literals(region_code["forecast.js"])
    assert hits == [], (
        f"the history region bakes in payload literals {hits}. Model names arrive in "
        f"meta.best_single_model_by_lead, the site in meta.site, the counts in the payload."
    )


def test_whole_forecast_js_still_bakes_in_no_payload_literal(whole_code: dict[str, str]) -> None:
    """...and F6 did not smuggle one into the F5 half of the file either."""
    hits = baked_payload_literals(whole_code["forecast.js"])
    assert hits == [], f"forecast.js bakes in payload literals {hits}"


def test_history_region_types_no_lead_literal(region_code: dict[str, str]) -> None:
    """The archive's leads are never typed. `6`, `12` and `24` all come from the payload.

    The lead list reaches the page through `meta.leads_available` and each row's own
    `entry.lead_h`; the sentence that names them is joined from that list. A typed `24` would
    outlive a change to the fetch window and quietly misdescribe the archive.
    """
    hits = [match.group(0) for match in LEAD_LITERAL.finditer(region_code["forecast.js"])]
    assert hits == [], (
        f"the history region types the lead literal(s) {hits}. Leads come from "
        f"meta.leads_available and entry.lead_h — never from a number typed on the page."
    )


@pytest.mark.parametrize(
    "bad",
    [
        "var LEADS = [6, 12, 24];",
        "if (entry.lead_h === 24) { return 'day-ahead'; }",
        "host.textContent = 'the archive is 6, 12 and 24 hours';",
        "var lead = 12;",
        "mae[24] = v;",
    ],
)
def test_lead_literal_positive_control(bad: str) -> None:
    """Every shape a typed lead actually takes — an array, a comparison, prose, a subscript."""
    assert LEAD_LITERAL.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "return fmt(entry.error_f, 1, true);",
        "var word = countWord(leads.length);",
        "note.textContent = String(join.tolerance_min) + '-minute window';",
        "if (parts.length < 2) return parts.join('');",
        "var x = 0.125;",
        "var d = new Date('2026-09-04T12:00Z'.slice(0, 10));",
        "row.appendChild(el('td', 'num history-time', utcStamp(entry.valid_time)));",
    ],
)
def test_lead_literal_guard_stays_silent_on_the_real_shapes(sanctioned: str) -> None:
    """Lines copied from the shipped region. A guard that fails the page for a decimal, an
    ISO stamp or a `toFixed` precision is a guard that gets deleted, so it is proven quiet on
    all of them — including `0.125` and `2026-09-04T12:00Z`, where a naive pattern hits.
    """
    assert LEAD_LITERAL.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


#: The read, as code: the comparison model is looked up on the payload's meta, never named.
BEST_SINGLE_READ = re.compile(r"meta\s*\.\s*best_single_model_by_lead")


def test_best_single_model_is_read_from_the_payload(region_code: dict[str, str]) -> None:
    """The comparison model is `meta.best_single_model_by_lead`, read, not typed.

    The backtest may pick a different single model at a different lead, and may pick a
    different one entirely after a refit. A column header naming a model the payload no
    longer names is the page stating something the data does not.
    """
    js = region_code["forecast.js"]
    assert BEST_SINGLE_READ.search(js) is not None, (
        "the history region no longer reads meta.best_single_model_by_lead — if the "
        "comparison model is now typed, the header will outlive the next refit"
    )
    assert baked_payload_literals(js) == [], "a model name is typed alongside the payload read"


@pytest.mark.parametrize(
    "bad",
    [
        "var best = 'Best single (NBM)';",
        "var names = ['gfs', 'hrrr'];",
        'headRow.appendChild(el("th", "", "NAM"));',
        "var site = 'Omaha Eppley Airfield';",
    ],
)
def test_baked_model_name_positive_control(bad: str) -> None:
    """F5's scanner, proven to fire on the shapes a typed comparison model would take."""
    assert baked_payload_literals(bad), f"guard missed {bad!r}"


def test_best_single_read_positive_control() -> None:
    """The read pattern fires on the real shape and stays silent on a typed replacement."""
    assert BEST_SINGLE_READ.search("var byLead = meta.best_single_model_by_lead || {};")
    assert BEST_SINGLE_READ.search("meta . best_single_model_by_lead") is not None
    assert BEST_SINGLE_READ.search("var byLead = {'6': 'nbm', '12': 'nbm'};") is None


# ==========================================================================================
# TASK 5.1 — the "three leads, not a downsample" sentence
# ==========================================================================================

#: The substantive halves of the sentence, asserted on meaning rather than on a full-string
#: match: a full-string match breaks on a comma and teaches the next author to delete it.
THREE_LEADS_FRAGMENTS = (
    "leads is what the archive was fetched at",
    "it is not a downsample of the forward view",
    "and that is v2",
)

#: A count word typed immediately before "leads" — the thing that must NOT be in the source,
#: because the count is `countWord(leads.length)` and a typed one would survive a refetch at
#: two leads or four.
TYPED_LEAD_COUNT = re.compile(
    r"\b(?:no|one|two|three|four|five|six|seven|eight|nine)\s+leads\b", re.I
)

#: The composition itself: the count comes from the payload's own lead list.
COMPOSED_COUNT = re.compile(r"countWord\(\s*leads\s*\.\s*length\s*\)")


def missing_fragments(text: str, required: tuple[str, ...]) -> list[str]:
    """Which of `required` are absent from `text`."""
    return [fragment for fragment in required if fragment not in text]


def test_three_leads_sentence_is_present_in_the_rendered_region(
    region_code: dict[str, str],
) -> None:
    """The sentence that stops a viewer reading the past view as a thinned forward view.

    This is the one place a viewer would otherwise conclude the archive is the forward strip
    with rows removed. Asserted on the substantive halves — why three leads, and what the
    alternative would cost — not on a full-string match that a comma would break.
    """
    js = region_code["forecast.js"]
    absent = missing_fragments(js, THREE_LEADS_FRAGMENTS)
    assert absent == [], (
        f"the history region has lost part of the three-leads sentence: {absent}. Without it "
        f"the past view reads as a downsample of the forward view, which it is not."
    )


def test_the_lead_count_in_that_sentence_is_composed_not_typed(
    region_code: dict[str, str],
) -> None:
    """"Three" is `countWord(leads.length)`, never the word typed into the copy.

    Refetch the archive at two leads or four and the typed sentence would keep saying three.
    Both halves are asserted: the composition is present, and no count word sits adjacent to
    "leads" anywhere in the region's code.
    """
    js = region_code["forecast.js"]
    assert COMPOSED_COUNT.search(js) is not None, (
        "the sentence's count is no longer composed from the payload's lead list"
    )
    hit = TYPED_LEAD_COUNT.search(js)
    assert hit is None, (
        f"the history region types a lead count into its copy: {hit.group(0)!r} — it must "
        f"come from countWord(leads.length), so a refetch cannot leave the sentence lying"
    )
    assert "meta.leads_available" in js, "the lead list is no longer read from the payload"


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("", list(THREE_LEADS_FRAGMENTS)),
        ("leads is what the archive was fetched at", list(THREE_LEADS_FRAGMENTS[1:])),
        ("it is not a downsample of the forward view and that is v2", [THREE_LEADS_FRAGMENTS[0]]),
    ],
)
def test_three_leads_sentence_positive_control(sample: str, expected: list[str]) -> None:
    """The presence check reports exactly what is missing, including "all of it"."""
    assert missing_fragments(sample, THREE_LEADS_FRAGMENTS) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "var text = 'The past view shows three leads because three leads is what';",
        'host.textContent = "two leads were fetched";',
        "text += ' Four Leads. ';",
    ],
)
def test_typed_lead_count_positive_control(bad: str) -> None:
    """A count typed into the copy is caught in every casing and both quote styles."""
    assert TYPED_LEAD_COUNT.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "var text = 'The past view shows ' + word + ' leads because ' + word + ' leads is';",
        "text += ' The archive is ' + joinList(leads) + ' hours.';",
        "var word = countWord(leads.length);",
    ],
)
def test_typed_lead_count_stays_silent_on_the_composed_form(sanctioned: str) -> None:
    """The real composition, copied from the shipped file, must not be flagged."""
    assert TYPED_LEAD_COUNT.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — the signed error: no absolute value, and a real U+2212 minus
# ==========================================================================================

#: The magnitude taken of the error specifically. Written as its own pattern alongside F5's
#: general scanner so the failure message names the actual sin.
ABS_ON_ERROR = re.compile(r"Math\s*\.\s*abs\s*\(\s*[^)]*error_f")

#: The value, through the shared formatter, with the signed flag set.
SIGNED_ERROR_FORMAT = re.compile(r"fmt\(\s*entry\s*\.\s*error_f\s*,\s*\d+\s*,\s*true\s*\)")

#: A string literal that is exactly one ASCII hyphen — a hand-rolled sign. `'-hourly'` and
#: `'-minute nearest-observation window'` are real literals in this region and must not match,
#: which is why the pattern requires the hyphen to be the WHOLE literal.
HAND_ROLLED_ASCII_SIGN = re.compile(r"""(['"])-\1""")


def test_history_region_takes_no_absolute_value(region_code: dict[str, str]) -> None:
    """No magnitude anywhere in the region, of the error or of anything else.

    Stripping the sign off a displayed error turns a cold bias and a warm bias into the same
    number, and the direction is the only thing a grower can act on. The region has no tie
    threshold in it, so the sanctioned use F5 tolerates does not arise here and the stricter
    rule — no call at all — is the correct one.
    """
    js = region_code["forecast.js"]
    assert ABS_ON_ERROR.search(js) is None, "the region takes the magnitude of error_f"
    assert ABS_CALL.search(js) is None, (
        "the history region calls the absolute-value function. Every value here is signed, "
        "and the sign is what says whether we ran warm or cold."
    )
    assert forbidden_abs_uses(js) == [], "F5's scanner disagrees with the stricter check above"


@pytest.mark.parametrize(
    "bad",
    [
        "cell.appendChild(el('span', '', fmt(Math.abs(entry.error_f), 1)));",
        "var e = Math.abs(entry.error_f);",
        "var e = Math . abs ( Number(entry.error_f) ) ;",
        "return Math.abs(day.mae_f[key]);",
    ],
)
def test_absolute_value_positive_control(bad: str) -> None:
    """Both scanners fire on a magnitude taken of a displayed value. Neither may go quiet."""
    assert ABS_CALL.search(bad) is not None, f"the general scanner missed {bad!r}"
    assert forbidden_abs_uses(bad), f"F5's scanner missed {bad!r}"


@pytest.mark.parametrize(
    "bad",
    [
        "Math.abs(entry.error_f)",
        "Math.abs( entry.error_f )",
        "Math . abs (Number(entry.error_f))",
    ],
)
def test_absolute_value_on_the_error_positive_control(bad: str) -> None:
    """The error-specific pattern, proven to fire on the error-specific sin."""
    assert ABS_ON_ERROR.search(bad) is not None, f"guard missed {bad!r}"


def test_absolute_value_on_the_error_stays_silent_on_the_real_shape() -> None:
    """The shipped call site takes no magnitude, and the pattern must not invent one."""
    assert ABS_ON_ERROR.search("withUnit(fmt(entry.error_f, 1, true), meta.units)") is None
    assert ABS_ON_ERROR.search("var value = Number(entry.error_f);") is None


def test_the_rendered_minus_is_the_real_one(
    region_code: dict[str, str], whole_code: dict[str, str]
) -> None:
    """Negatives render as U+2212, put there once by the shared formatter and at no call site.

    `toFixed` emits an ASCII hyphen, which is narrower than a digit even in a tabular face, so
    a negative error stops lining up in its column — and the sign is the one character a
    presenter cannot afford to lose when pasting a number into a chat window.

    Three assertions, because there are three ways to lose it: the character could vanish
    from the file, the substitution could vanish, or a call site could roll its own sign and
    reintroduce the hyphen the formatter exists to remove.
    """
    js = whole_code["forecast.js"]
    region = region_code["forecast.js"]

    assert TRUE_MINUS != "-", "the escape resolved to an ASCII hyphen"
    assert TRUE_MINUS in js, "forecast.js no longer carries U+2212"
    assert MINUS_SUBSTITUTION.search(js) is not None, "the minus substitution is gone"

    assert SIGNED_ERROR_FORMAT.search(region) is not None, (
        "the error value no longer goes through the shared signed formatter — whatever "
        "renders it now is not the thing that substitutes the real minus"
    )
    assert MINUS_SUBSTITUTION.search(region) is None, (
        "the history region re-does the minus substitution. It happens in one place; a second "
        "one is how the two drift apart."
    )
    hit = HAND_ROLLED_ASCII_SIGN.search(region)
    assert hit is None, (
        f"the history region carries a bare ASCII hyphen literal at offset {region.find('-')} "
        f"({hit.group(0) if hit else ''!r}) — a hand-rolled sign, which is the hyphen back"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "var sign = (v < 0 ? '-' : '+');",
        'cell.textContent = "-" + String(mag);',
    ],
)
def test_hand_rolled_sign_positive_control(bad: str) -> None:
    """A sign assembled at a call site is caught in both quote styles."""
    assert HAND_ROLLED_ASCII_SIGN.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "var step = String(state.meta.step_h) + '-hourly';",
        "note.textContent = String(join.tolerance_min) + '-minute nearest-observation window';",
        "row.appendChild(el('td', 'num history-offset', fmt(entry.obs_offset_min, 0, true)));",
    ],
)
def test_hand_rolled_sign_stays_silent_on_the_real_literals(sanctioned: str) -> None:
    """`-hourly` and `-minute` are real literals in the shipped region and are not signs."""
    assert HAND_ROLLED_ASCII_SIGN.search(sanctioned) is None, f"over-fired on {sanctioned!r}"


def test_signed_error_format_positive_control() -> None:
    """The formatter check fires on the real shape and goes quiet when the flag is dropped."""
    assert SIGNED_ERROR_FORMAT.search("fmt(entry.error_f, 1, true)") is not None
    assert SIGNED_ERROR_FORMAT.search("fmt( entry . error_f , 2 , true )") is not None
    assert SIGNED_ERROR_FORMAT.search("fmt(entry.error_f, 1)") is None
    assert SIGNED_ERROR_FORMAT.search("String(entry.error_f)") is None


# ==========================================================================================
# TASK 5.1 — no band, no ribbon, no envelope, no whisker
# ==========================================================================================

#: The four shapes that would turn a settled observation into a claim about a spread. Matched
#: case-insensitively and as substrings, so a class name (`history-band`), an element name and
#: a variable are all caught.
SPREAD_SHAPE = re.compile(r"band|ribbon|envelope|whisker", re.I)


@pytest.mark.parametrize("name", ["forecast.html", "forecast.js", "forecast.css"])
def test_no_spread_shape_in_the_history_region(name: str, region_code: dict[str, str]) -> None:
    """Nothing in this region draws a spread. Every number here is settled, not estimated.

    Read on comment-stripped source: `forecast.js` names all four shapes in the comment that
    forbids them, and `test_spread_shape_guard_can_see_a_real_hit` below proves the raw region
    matches while the stripped one does not — so this guard is demonstrably able to see a hit
    in real content and correctly declines to count a prohibition as a violation.
    """
    hits = sorted({match.group(0).lower() for match in SPREAD_SHAPE.finditer(region_code[name])})
    assert hits == [], (
        f"{name}'s history region draws or names a spread shape {hits}. Every value in this "
        f"region has already been settled by an observation; a spread would claim otherwise."
    )


def test_spread_shape_guard_can_see_a_real_hit(
    region_raw: dict[str, str], region_code: dict[str, str]
) -> None:
    """PROOF 4: the raw JS region matches all four shapes; the stripped region matches none.

    This is a positive control drawn from REAL CONTENT rather than a synthesized string. The
    shipped comment enumerates the four forbidden shapes, so the guard is proven to fire on
    this very file — the stripping is the only reason it does not fire on the shipped copy.
    If that comment is ever re-worded, this proof goes red and says so instead of going quiet.
    """
    raw = region_raw["forecast.js"]
    stripped = region_code["forecast.js"]

    found = sorted({match.group(0).lower() for match in SPREAD_SHAPE.finditer(raw)})
    assert found == ["band", "envelope", "ribbon", "whisker"], (
        f"forecast.js no longer names all four forbidden shapes in the comment that forbids "
        f"them (found {found}); this real-content proof of the guard has gone stale"
    )
    assert SPREAD_SHAPE.search(stripped) is None
    assert len(stripped) < len(raw)


@pytest.mark.parametrize(
    "bad",
    [
        "cell.appendChild(el('span', 'history-band'));",
        '<div class="history-ribbon"></div>',
        ".history-envelope { background: var(--surface-2); }",
        "var whiskerTop = mid + spread;",
        "el('div', 'ERROR-BAND')",
    ],
)
def test_spread_shape_positive_control(bad: str) -> None:
    """Every spelling a spread element actually arrives in — class, element, variable, caps."""
    assert SPREAD_SHAPE.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "var card = el('section', 'card history-day-card');",
        "row.appendChild(el('td', 'num history-error-cell'));",
        ".history-table-wrap { overflow-x: auto; }",
    ],
)
def test_spread_shape_stays_silent_on_the_real_markup(sanctioned: str) -> None:
    """Lines from the shipped region. A guard that fires on `history-day-card` is noise."""
    assert SPREAD_SHAPE.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — the state attribute, set when it holds and ABSENT otherwise
# ==========================================================================================

#: `data-history` set to anything that means "not ready", in every spelling that reaches the
#: DOM: an HTML attribute, a `setAttribute` pair, a `dataset` assignment, a CSS selector.
HISTORY_ATTR_OFF_VALUE = re.compile(
    r"""data-history\s*["']?\s*[,=:]\s*["']?\s*(?:false|none|off|not-ready|empty|absent)"""
    r"""|dataset\s*\.\s*history\s*=\s*["']?\s*(?:false|none|off)""",
    re.I,
)

HISTORY_ATTR_SET = re.compile(r"""setAttribute\(\s*['"]data-history['"]\s*,\s*['"]ready['"]\s*\)""")


def test_history_state_attribute_is_set_only_when_the_days_render(
    region_code: dict[str, str], whole_code: dict[str, str]
) -> None:
    """`html[data-history="ready"]` is written by JS when days render, and never falsified.

    An absent attribute is the off state. The CSS selects on `"ready"`, which does not match
    an off string — so writing one produces markup that looks like it is doing something and
    is inert. It must also not appear in the shipped HTML: typing it there would raise the
    stepper before any payload landed.
    """
    js = region_code["forecast.js"]
    assert HISTORY_ATTR_SET.search(js) is not None, (
        "the history region no longer sets html[data-history=\"ready\"]; the stepper will "
        "stay hidden however well the payload renders"
    )
    assert "data-history" not in whole_code["forecast.html"], (
        "forecast.html types the history state attribute into its markup — the region would "
        "then reveal itself before any payload had landed"
    )
    for name in ("forecast.html", "forecast.js", "forecast.css"):
        hit = HISTORY_ATTR_OFF_VALUE.search(region_code[name])
        assert hit is None, (
            f"{name} writes an off value into the history state attribute: "
            f"{hit.group(0) if hit else ''!r}. Set it when the condition holds; leave it ABSENT."
        )


@pytest.mark.parametrize(
    "bad",
    [
        '<html data-history="false">',
        "root.setAttribute('data-history', 'none');",
        'el.setAttribute("data-history", "not-ready");',
        "document.documentElement.dataset.history = 'false';",
        "html[data-history=empty] .history-controls { display: none }",
    ],
)
def test_history_state_attribute_off_value_positive_control(bad: str) -> None:
    """Every spelling of a falsified state attribute, caught."""
    assert HISTORY_ATTR_OFF_VALUE.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "document.documentElement.setAttribute('data-history', 'ready');",
        'html[data-history="ready"] .history-controls { display: flex; }',
        "if (atEnd) button.setAttribute('aria-disabled', 'true');",
    ],
)
def test_history_state_attribute_guard_stays_silent_on_the_real_writes(sanctioned: str) -> None:
    """The shipped write and the shipped selector, asserted silent."""
    assert HISTORY_ATTR_OFF_VALUE.search(sanctioned) is None, f"over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.1 — every hook Stream 4 added is actually there
# ==========================================================================================

#: The ids `forecast.js` looks up by name. A renamed id is a silently empty region: `$(id)`
#: returns null, the render function returns early, and the page shows nothing with no error.
HISTORY_IDS = (
    "history-section",
    "history-heading",
    "history-controls",
    "day-stepper",
    "day-prev",
    "day-pill",
    "day-next",
    "history-leads-note",
    "history-days",
    "history-omitted",
    "history-unavailable",
)

#: The classes the region is styled and built with, checked across the three files together:
#: some are only ever written by the script, some only ever styled by the sheet.
HISTORY_CLASSES = (
    "history-section",
    "history-heading",
    "history-controls",
    "day-stepper",
    "day-step",
    "day-pill",
    "history-leads-note",
    "history-day-card",
    "history-mae",
    "history-table-wrap",
    "history-tbl",
    "history-time",
    "history-value",
    "history-secondary",
    "history-offset",
    "history-error-cell",
    "history-error-value",
    "history-error-word",
    "history-offset-note",
    "history-omitted-item",
)


def test_every_history_id_is_in_the_markup(region_code: dict[str, str]) -> None:
    """The eleven ids exist in the HTML region, spelled exactly as the script looks them up.

    A renamed id fails silently and expensively: the lookup returns null, the render returns
    early, and the region is blank with a clean console.
    """
    html = region_code["forecast.html"]
    missing = [name for name in HISTORY_IDS if f'id="{name}"' not in html]
    assert missing == [], f"the history markup has lost the id(s) {missing}"


def test_every_history_class_is_used_or_styled(region_code: dict[str, str]) -> None:
    """Each class appears in at least one of the three regions.

    Checked across all three together on purpose: a class written by the script and never
    styled, or styled and never written, is a real defect, but which file carries it is an
    implementation detail this guard has no business pinning.
    """
    combined = "".join(region_code[name] for name in region_code)
    missing = [name for name in HISTORY_CLASSES if name not in combined]
    assert missing == [], f"the history region has lost the class hook(s) {missing}"


def test_hook_presence_check_positive_control() -> None:
    """The presence check reports what is absent, including everything."""
    assert [name for name in HISTORY_IDS if f'id="{name}"' not in ""] == list(HISTORY_IDS)
    assert [name for name in HISTORY_CLASSES if name not in ""] == list(HISTORY_CLASSES)
    sample = "".join(f'id="{name}" ' for name in HISTORY_IDS[:-1])
    assert [name for name in HISTORY_IDS if f'id="{name}"' not in sample] == [HISTORY_IDS[-1]]


# ==========================================================================================
# TASK 5.1 — what forecast.css may NOT have gained
# ==========================================================================================

#: `.num` at the HEAD of a selector — the whole-class restatement. `.tbl .num` and
#: `.skill-weights-age .num` are pre-existing SCOPED rules that layer on top of the token
#: doc's class rather than replacing it, and they are correct; this pattern must not match
#: them, which `test_num_restatement_stays_silent_on_a_scoped_rule` proves.
NUM_SELECTOR_HEAD = re.compile(r"(?:^|[},])\s*\.num(?![\w-])\s*[,{]", re.M)


def test_forecast_css_history_region_declares_no_model_colour_token(
    region_code: dict[str, str], grep_binary: str
) -> None:
    """The model colour map lives in `tokens.css`; this region may only reference it.

    Re-declaring one here would fork the map: the token doc's dark-theme values would stop
    applying to the history table and a model would change colour when the toggle is used.
    Asserted twice — once over the region text, once through the same exit-status-aware grep
    F5 uses over the whole file, so a grep error cannot masquerade as zero hits.
    """
    assert "--model-" not in region_code["forecast.css"], (
        "the history region mentions a model colour token; the map belongs to tokens.css"
    )
    hits = grep_lines(grep_binary, MODEL_TOKEN_DECLARATION_PATTERN, FORECAST_CSS)
    assert hits == [], f"forecast.css declares a model colour token: {hits}"


def test_model_colour_token_positive_control(tmp_path: Path, grep_binary: str) -> None:
    """The same grep, over a sample that DOES declare one, must find it.

    Without this the assertion above is indistinguishable from a grep that never ran. The
    real `tokens.css` is used as a second, real-content sample, because it genuinely carries
    the declarations this pattern looks for.
    """
    sample = tmp_path / "sample.css"
    sample.write_text(":root {\n  --model-gfs: var(--orange-500);\n}\n", encoding="utf-8")
    assert grep_lines(grep_binary, MODEL_TOKEN_DECLARATION_PATTERN, sample), "guard missed a sample"

    tokens = FRONTEND / "tokens.css"
    assert tokens.is_file(), f"{tokens} is missing — the real-content half of this proof is gone"
    assert grep_lines(grep_binary, MODEL_TOKEN_DECLARATION_PATTERN, tokens), (
        "tokens.css no longer declares the model colour map; either the map moved or this "
        "pattern has gone stale against real content"
    )


def test_forecast_css_history_region_has_no_theme_attribute_block(
    region_code: dict[str, str], whole_code: dict[str, str]
) -> None:
    """Theme forking belongs in the token doc. This file styles layout, not palettes.

    A theme-attribute block here would cascade after `tokens.css` and silently win, which is
    how a page ends up with one component that ignores the toggle. Asserted on the region and
    on the whole file, because F6 could have added one anywhere in it.
    """
    scopes = (
        ("history region", region_code["forecast.css"]),
        ("whole file", whole_code["forecast.css"]),
    )
    for label, text in scopes:
        hit = CSS_THEME_ATTRIBUTE_BLOCK.search(text)
        assert hit is None, f"the forecast.css {label} forks on the theme attribute: {hit!r}"


@pytest.mark.parametrize(
    "bad",
    [
        'html[data-theme="dark"] .history-day-card { background: #111 }',
        ":root[ data-theme='dark'] { --x: 1 }",
        "[data-theme=dark] .history-error-value { }",
    ],
)
def test_css_theme_block_positive_control(bad: str) -> None:
    """F5's pattern, re-proven against history-region selectors."""
    assert CSS_THEME_ATTRIBUTE_BLOCK.search(bad) is not None, f"guard missed {bad!r}"


def test_css_theme_block_stays_silent_on_the_history_state_selector() -> None:
    """`html[data-history="ready"]` is a state hook, not a theme fork, and must stay quiet."""
    assert CSS_THEME_ATTRIBUTE_BLOCK.search('html[data-history="ready"] .day-stepper { }') is None


def test_forecast_css_history_region_does_not_restate_num(region_code: dict[str, str]) -> None:
    """`.num` is `tokens.css`'s class; the region layers on it and never redefines it.

    A whole-class restatement here would cascade after the token doc and win, so the mono
    tabular figures the rest of the page shares would silently diverge in this one region.
    Both the narrow head-of-selector pattern and the blunt membership test are asserted: the
    region does not restate `.num`, and in fact does not name it at all.
    """
    css = region_code["forecast.css"]
    hit = NUM_SELECTOR_HEAD.search(css)
    assert hit is None, f"the history region restates .num: {hit.group(0) if hit else ''!r}"
    assert ".num" not in css, (
        "the history region names .num. Every numeric cell in it takes the class and sets "
        "only what it changes on top; the class itself belongs to tokens.css."
    )


@pytest.mark.parametrize(
    "bad",
    [
        ".num { font-family: var(--font-mono); }",
        ".history-time,\n.num { text-align: right }",
        ".day-pill { color: red }\n.num{ font-size: 12px }",
        ".num , .mono-value { font-variant-numeric: tabular-nums }",
    ],
)
def test_num_restatement_positive_control(bad: str) -> None:
    """A whole-class restatement is caught first in a block, mid-list, and after a brace."""
    assert NUM_SELECTOR_HEAD.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        ".tbl .num { font-variant-numeric: tabular-nums; }",
        ".skill-weights-age .num,\n.skill-weights-age .mono-value { text-align: left; }",
        ".history-tbl .num { font-size: 12.5px }",
        ".numeral { color: red }",
    ],
)
def test_num_restatement_stays_silent_on_a_scoped_rule(sanctioned: str) -> None:
    """The two pre-existing scoped rules layer on the class; they do not restate it.

    Copied from the shipped `forecast.css`. A guard that failed the page for `.tbl .num`
    would be demanding the removal of the correct thing, and would be deleted within a day.
    """
    assert NUM_SELECTOR_HEAD.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


# ==========================================================================================
# TASK 5.2 — the off-limits paths, unmodified against the branch point
# ==========================================================================================
#
# WHAT THIS GATE IS FOR. F6 is a frontend-and-`forecast/` ticket. It has no business touching
# the API module, the app entrypoint, the scoring package, the docs, or the scored payload —
# and "no business touching" is exactly the kind of claim that gets checked by a reviewer's
# eye once and never again. This turns it into a test.
#
# WHY IT IS NOT VACUOUS. Three separate assertions make the empty result mean something:
#
#   (1) `test_off_limits_paths_are_real` proves every path in the list EXISTS and is TRACKED
#       by git. A typo'd pathspec diffs nothing and passes, which is this project's most
#       frequently repeated retrospective finding.
#   (2) `test_off_limits_diff_control_sees_a_real_modification` runs the SAME invocation
#       against `frontend/forecast.js`, which F6 genuinely rewrote, and asserts it reports a
#       non-zero change. An empty answer from a broken command and an empty answer from an
#       unmodified tree are otherwise identical.
#   (3) `test_numstat_parser_control` proves the parser reports a violation when handed one.
#
# The diff has NO second ref on purpose, so it compares the branch point to the WORKING TREE:
# a claim about the files as they exist on disk right now, not about two commits that happen
# to be the same commit.

#: The commit F6 branched from. Measured, not assumed: against this ref every path below is
#: unchanged in the working tree, `backend/main.py` included.
BRANCH_POINT = "6d54325"

#: F4's base for `backend/main.py`. Against THIS ref the file legitimately differs by exactly
#: two added lines — one import and one `include_router` call, already committed before F6
#: started. Pinned here so the accepted delta is recorded rather than rediscovered, and so a
#: third moved line fails loudly.
MAIN_PY_F4_BASE = "740dfb0"
EXPECTED_MAIN_NUMSTAT_AGAINST_F4_BASE = (2, 0)

#: Everything F6 may not have touched.
OFF_LIMITS_PATHS = (
    "backend/forecast_api.py",
    "backend/main.py",
    "score",
    "docs",
    "data/results.json",
)

#: A path F6 DID rewrite, used as the real-content control for the diff invocation.
CHANGED_CONTROL_PATH = "frontend/forecast.js"

RESULTS_JSON = REPO / "data" / "results.json"
EXPECTED_RESULTS_SHA256 = "3b113a995b084da41e593af9c70214e8efb76170056bc42e0b84413b1644aa8c"


def git(*args: str) -> subprocess.CompletedProcess:
    """Run a read-only `git` command in this repository.

    F5's shape, carried rather than shared: `tests/test_live_guards.py` is off limits and
    `tests/test_forecast_ui_guards.py` is protected. Every call site below is a read; nothing
    in this module mutates git state or the working tree.
    """
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)


@pytest.fixture()
def git_repo() -> None:
    """Skip when `git` is genuinely unavailable — and only then.

    A missing `git` binary or a non-checkout is an environment this gate cannot run in, and a
    skip says so out loud. A MISSING REF is not that: it means the branch point this gate is
    pinned to has gone, which is a real failure and is asserted as one below rather than
    skipped, because a skipped guard and a passing guard read the same in a summary line.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not available on PATH")
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip(f"{REPO} is not a git working tree")


def resolved(ref: str) -> str:
    """`ref` as a full sha. FAILS, never skips, when the ref is absent."""
    result = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    assert result.returncode == 0 and result.stdout.strip(), (
        f"{ref} is not a commit in this checkout: {result.stderr.strip()!r}. This gate is "
        f"pinned to it; without it nothing below is verifying anything, so it fails rather "
        f"than passing or skipping quietly."
    )
    return result.stdout.strip()


def numstat_against(base: str, *paths: str) -> dict[str, tuple[int, int]]:
    """`{path: (added, deleted)}` for `paths` between `base` and the WORKING TREE.

    No second ref: the comparison reaches disk. A commit-to-commit form would report clean for
    a file edited but not committed, which is the state a stray edit is actually caught in.
    """
    result = git("diff", "--numstat", base, "--", *paths)
    assert result.returncode == 0, f"git diff failed: {result.stderr.strip()!r}"
    return parse_numstat(result.stdout)


@pytest.mark.usefixtures("git_repo")
def test_off_limits_paths_are_real() -> None:
    """Every path in the list exists on disk AND is tracked by git.

    A TYPO'D PATHSPEC DIFFS NOTHING AND PASSES. This is the assertion that makes the empty
    diff below mean "nothing changed" rather than "nothing was looked at" — and an untracked
    path would be just as silent as a misspelled one.
    """
    assert OFF_LIMITS_PATHS, "the off-limits list is empty; the gate would be a no-op"
    for path in OFF_LIMITS_PATHS:
        assert (REPO / path).exists(), f"{path} does not exist — the gate is scanning nothing"
        listed = git("ls-files", "--", path)
        assert listed.returncode == 0, listed.stderr
        assert listed.stdout.strip(), (
            f"{path} is not tracked by git, so `git diff` will never report a change to it. "
            f"A misspelled pathspec looks exactly like this."
        )


@pytest.mark.usefixtures("git_repo")
def test_off_limits_paths_are_unmodified_against_the_branch_point() -> None:
    """The API module, the entrypoint, `score/`, `docs/` and the scored payload are untouched.

    F6 adds a page region and a `forecast/` module. Anything it changed here is a stray edit,
    and this fails on it rather than depending on a reviewer noticing an extra file in a diff.
    """
    base = resolved(BRANCH_POINT)
    changed = numstat_against(base, *OFF_LIMITS_PATHS)
    assert changed == {}, (
        f"F6 modified off-limits path(s) since {base[:7]}: {changed}. This ticket touches "
        f"frontend/forecast.*, forecast/ and tests/ — nothing else."
    )


@pytest.mark.usefixtures("git_repo")
def test_off_limits_paths_have_no_untracked_additions() -> None:
    """...and nothing NEW appeared under them either.

    `git diff` cannot see an untracked file, so a new module dropped into `score/` would slip
    past the assertion above entirely. `git status` is the half that sees it.
    """
    result = git("status", "--porcelain", "--", *OFF_LIMITS_PATHS)
    assert result.returncode == 0, result.stderr
    entries = [line for line in result.stdout.splitlines() if line.strip()]
    assert entries == [], "off-limits paths carry uncommitted entries:\n" + "\n".join(entries)


@pytest.mark.usefixtures("git_repo")
def test_backend_main_is_unchanged_against_the_branch_point() -> None:
    """`backend/main.py` against `BRANCH_POINT`: no change at all. Measured, not assumed.

    The file's two-line difference is against F4's base, not this one — those lines were
    already committed when F6 branched. Stated as its own test so the two refs cannot be
    confused later.
    """
    base = resolved(BRANCH_POINT)
    changed = numstat_against(base, "backend/main.py")
    assert changed == {}, (
        f"backend/main.py changed since {base[:7]}: {changed}. Against the branch point it "
        f"must be byte-identical; the accepted two-line delta is against {MAIN_PY_F4_BASE}."
    )


@pytest.mark.usefixtures("git_repo")
def test_backend_main_carries_exactly_the_accepted_f4_delta() -> None:
    """`backend/main.py` against F4's base: exactly two added lines, none deleted.

    One import and one `include_router` call is the entire permitted change, and it predates
    F6. Pinned so that a third moved line — which would mean something else went with it —
    fails here rather than passing as "roughly the same file".
    """
    base = resolved(MAIN_PY_F4_BASE)
    changed = numstat_against(base, "backend/main.py")
    assert changed.get("backend/main.py") == EXPECTED_MAIN_NUMSTAT_AGAINST_F4_BASE, (
        f"backend/main.py must be exactly {EXPECTED_MAIN_NUMSTAT_AGAINST_F4_BASE} "
        f"(added, deleted) against {base[:7]}; measured {changed.get('backend/main.py')}"
    )


@pytest.mark.usefixtures("git_repo")
def test_off_limits_diff_control_sees_a_real_modification() -> None:
    """POSITIVE CONTROL: the same invocation, pointed at a file F6 really did rewrite.

    `frontend/forecast.js` gained the whole history region. If this reports nothing, the diff
    command above is broken or its pathspec never resolves, and every green in this section is
    worthless. This is the assertion that tells the two apart, and it costs one subprocess.
    """
    base = resolved(BRANCH_POINT)
    changed = numstat_against(base, CHANGED_CONTROL_PATH)

    assert CHANGED_CONTROL_PATH in changed, (
        f"the diff invocation reported no change to {CHANGED_CONTROL_PATH}, which F6 rewrote. "
        f"The command or its pathspec is broken, so the off-limits assertions above prove "
        f"nothing — an empty diff from a broken command reads exactly like a clean tree."
    )
    added, deleted = changed[CHANGED_CONTROL_PATH]
    assert added > 0, f"expected added lines in {CHANGED_CONTROL_PATH}, got {(added, deleted)}"


def test_numstat_parser_control() -> None:
    """The parser this gate trusts, proven to report a violation when handed one.

    F5 proves the same parser on its own cases; this repeats the one shape that matters here
    — an off-limits path with a non-zero change — so a future edit to the parser cannot make
    this module quietly tolerant.
    """
    assert parse_numstat("") == {}
    assert parse_numstat("3\t1\tscore/run.py\n") == {"score/run.py": (3, 1)}
    assert parse_numstat("2\t0\tbackend/main.py\n0\t9\tdocs/SPEC.md\n") == {
        "backend/main.py": (2, 0),
        "docs/SPEC.md": (0, 9),
    }
    assert parse_numstat("-\t-\tdata/blob.parquet\n") == {}


def test_results_json_is_byte_identical() -> None:
    """`data/results.json` is unchanged, asserted on its SHA-256.

    The scored document is the demo's payload. F6 reads a different file entirely
    (`data/forecast_history.json`) and regenerates nothing. Read-only: hashed from bytes,
    never opened for writing, never copied, never moved.
    """
    assert RESULTS_JSON.is_file(), (
        f"{RESULTS_JSON} is missing — this gate cannot verify what is not there, and an "
        f"absent payload is a bigger problem than a changed one"
    )
    digest = hashlib.sha256(RESULTS_JSON.read_bytes()).hexdigest()
    assert digest == EXPECTED_RESULTS_SHA256, (
        f"data/results.json changed: {digest} != {EXPECTED_RESULTS_SHA256}"
    )


def test_results_json_digest_control(tmp_path: Path) -> None:
    """The digest comparison, proven to notice a single changed byte.

    A hash check that cannot fail is the same bug as a grep that cannot match. Run on a copy
    under `tmp_path`; the real payload is never written.
    """
    original = RESULTS_JSON.read_bytes()
    digest_before = hashlib.sha256(original).hexdigest()

    copy = tmp_path / "results.json"
    copy.write_bytes(original + b" ")
    assert hashlib.sha256(copy.read_bytes()).hexdigest() != EXPECTED_RESULTS_SHA256, (
        "a one-byte change did not move the digest — the comparison cannot fail"
    )

    assert hashlib.sha256(RESULTS_JSON.read_bytes()).hexdigest() == digest_before, (
        "data/results.json changed during its own control; it must never be written"
    )


def test_off_limits_scope_is_pinned() -> None:
    """The gate's scope, asserted, so a path cannot be quietly dropped from it.

    Removing an entry from `OFF_LIMITS_PATHS` would leave every test above green while the
    thing they protect stopped being protected. Nothing else in this module would notice.
    """
    assert OFF_LIMITS_PATHS == (
        "backend/forecast_api.py",
        "backend/main.py",
        "score",
        "docs",
        "data/results.json",
    )
    assert CHANGED_CONTROL_PATH not in OFF_LIMITS_PATHS, (
        "the positive control's path is inside the gate's own scope; it would have to be both "
        "changed and unchanged"
    )
