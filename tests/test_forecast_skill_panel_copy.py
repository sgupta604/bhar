"""F7 Stream 6 — the trust panel's COPY GUARD, and an honest account of what it cannot see.

FORECAST-SPEC §6 is enforced in prose, and prose is the one thing this project has no runner
for: there is no JS test harness (SPEC §13), so the panel's sentences are checkable only at
source level. That is what this module does — and the first job of its docstring is to say
where that stops being enough.

WHAT THIS GUARD CANNOT CATCH
----------------------------
1. IT NEVER READS THE RENDERED DOM. Every assertion below is made against `frontend/*` as
   TEXT. A file whose copy is byte-perfect and whose renderer never appends the node, or
   appends it into the wrong parent, passes this module completely. Nothing here proves a
   sentence reached a screen.
2. IT CANNOT CATCH A CLAIM PHRASED IN WORDS NOBODY BLACKLISTED. "We'd be surprised by more
   than two degrees" is a forward-looking promise and matches none of the patterns in
   `PROMISE_BLACKLIST`. Layer 3 is a TRIPWIRE FOR DRIFT, not a semantic judge. The real
   defence is Layer 2: the copy is pinned byte-for-byte, so any rewording — honest or not —
   fails and has to be re-argued.
3. IT CANNOT POLICE FUTURE SERVER PAYLOADS. `skill.basis` and `skill.note` are authored by
   the backend and rendered verbatim. The blacklist runs over the TWO COMMITTED payloads only
   (`data/forecast.json`, `data/forecast.fixture.json`). A future refit that shipped a
   promise-shaped note would render it, and this module would never see it. Closing that gap
   is a value-level contract change in `forecast/contract.py`, queued as a separate quickfix
   and deliberately NOT made here.
4. IT SEES CSS PROSE ONLY BECAUSE THE F7 CSS REGION IS SCANNED. A `content:` string added to
   `frontend/forecast.css` outside the F7 region is invisible to `test_layer3_css_*`.

WHAT IS EXTERNALLY ANCHORED, AND WHAT IS ONLY PINNED
----------------------------------------------------
A guard that pins whatever happens to be in the file proves only that nobody edited the file.
So the load-bearing sentences are anchored to a document this module does not control:

  * the three per-lead sentences — reconstructed here from the PINNED templates with the LIVE
    payload values substituted, and asserted BYTE-IDENTICAL to the three blockquotes in
    `.claude/features/forecast-page/design-target.md` §4;
  * the `.skill-basis` sample-size sentence — same treatment, against §4's own blockquote;
  * `#skill-beyond-fitted`'s text node — asserted byte-identical to §4's verbatim sentence.

THREE STRINGS HAVE NO §4 COUNTERPART AND ARE THEREFORE ONLY PINNED, NOT ANCHORED: the realized
caveat (`copyRealizedCaveat`), the panel→strip cross-link (`copyCrossLink`) and the
fabricated-vs-measured statement (`COPY_SYNTHETIC_MIXING`). §1.5 describes the cross-link's
SHAPE ("the shaded cells from a 27-hour lead onward on the strip above") but publishes no
verbatim string for any of them, and the statement post-dates the design target entirely — it
answers a defect found in the RENDERED page, not a line in §4. So what this module asserts
about the three is (a) they are byte-identical to what was authored, (b) they satisfy Layer
3's semantic markers, and, for the statement, (c) the condition it asserts is true of the
fixture payload and false of the live one. Saying they are "verified against the design
target" would be an overclaim, and a guard that overclaims is worse than no guard.

THE FOUR LAYERS
---------------
    LAYER 1 — CONTAINMENT (`test_layer1_*`). Everything else scans the PANEL COPY block. If
    that block can be silently shrunk — by rewording a marker, or by a sentence migrating out
    into the renderer — layers 2 to 4 scan a subset of the copy and report a comforting
    green. That is the fake-green shape this project has hit repeatedly. So: a missing marker
    RAISES rather than falling back to the whole file; the block carries a byte floor; and no
    string literal longer than `OUTSIDE_LITERAL_MAX` characters may exist anywhere in the F7
    JS region OUTSIDE the block, which is what stops a sentence from escaping it.

    LAYER 2 — BYTE-PINNED COPY (`test_layer2_*`). Every string literal in the block, in
    order, against `COPY_LITERALS`. Editing one character of panel prose fails this module.

    LAYER 3 — ALLOWLISTED BLACKLIST + MARKERS (`test_layer3_*`). Promise-shaped phrasings,
    with an allowlist that is proven in BOTH directions.

    LAYER 4 — DERIVED-VALUE CROSS-CHECKS (`test_layer4_*`). The payload facts the copy is
    parameterised on, over both payloads, plus the re-split reproduction.

WHY THE ALLOWLIST IS NOT A LOOPHOLE
-----------------------------------
The required copy literally contains "not a promise about this forecast", and the live
payload's note literally contains "not a prediction about this forecast". A plain blacklist
FALSE-POSITIVES ON EXACTLY THE HONEST SENTENCES IT EXISTS TO PROTECT. So every hit must be
covered by a phrase in `SANCTIONED`, matched verbatim and spanning the hit — and both
directions are proven: `test_layer3_sanctioned_phrases_do_trip_the_blacklist` asserts each
sanctioned phrase really does produce a hit (an allowlist entry that matches nothing is dead
weight hiding a broken pattern), and `test_layer3_unsanctioned_promise_is_rejected` asserts a
promise-shaped phrase that is not in `SANCTIONED` fails.

NO BANNED STRING IS TYPED LITERALLY IN THIS FILE
------------------------------------------------
`tests/test_forecast_ui_guards.py`'s file-wide BANLIST would trip on a test module that names
the tokens it bans, so — as in the F5 and F6 guard modules — the one blacklist alternative
that collides with a banned word is assembled from an escaped first character.

SCOPE AND SAFETY
----------------
Nothing here starts a server, opens a socket, or writes anywhere outside `tmp_path` (and it
does not use `tmp_path` at all — every negative control is an in-memory string). The only
files opened are opened for READING: the three `frontend/forecast.*` files, the design target,
and the three committed JSON payloads. The strippers and the path constants are IMPORTED from
`tests/test_forecast_ui_guards.py` rather than re-typed, so a drift there fails loudly here.
The region extractor below is new because F6's is hardcoded to F6's own marker word.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from test_forecast_ui_guards import (
    FORECAST_CSS,
    FORECAST_HTML,
    FORECAST_JS,
    REPO,
    TRUE_MINUS,
    strip_css,
    strip_html,
    strip_js,
)

DESIGN_TARGET = REPO / ".claude" / "features" / "forecast-page" / "design-target.md"
LIVE_PAYLOAD = REPO / "data" / "forecast.json"
FIXTURE_PAYLOAD = REPO / "data" / "forecast.fixture.json"
HISTORY_PAYLOAD = REPO / "data" / "forecast_history.json"

#: The F7 region banner, searched case-insensitively, and its closer.
F7_MARKER = "SKILL PANEL CONTENT — F7"
F7_END_MARKER = "END SKILL PANEL CONTENT — F7"

#: The pinned-prose block inside the F7 JS region.
COPY_MARKER = "PANEL COPY"
COPY_END_MARKER = "END PANEL COPY"

#: Floors, not equalities. The point is that a re-worded marker yields an empty or near-empty
#: slice, and an empty slice is exactly what a vacuous scan looks like from the inside.
MINIMUM_F7_JS_REGION_BYTES = 10000
MINIMUM_COPY_BLOCK_BYTES = 5000
MINIMUM_COPY_CODE_BYTES = 3000

#: The containment ceiling. Every sentence belongs inside the copy block; a long literal
#: outside it is a sentence that escaped. The longest legitimate literal in the renderer is
#: `Historical, out of sample.` at 26 characters, so this leaves real headroom while still
#: being far below any panel sentence.
OUTSIDE_LITERAL_MAX = 40


# ==========================================================================================
# Region extraction — a missing marker RAISES, it never falls back to the whole file
# ==========================================================================================


def region_between(text: str, opener: str, closer: str, comment_open: str = "/*") -> str:
    """The slice from the comment carrying `opener` through the comment carrying `closer`.

    Rewinds to `comment_open` so the slice begins with a BALANCED comment: starting at the
    marker word itself would leave a dangling `*/`, the comment stripper would not recognise
    the block, and every stripped-text guard below would then scan explanatory prose it was
    never meant to see.

    RAISES when either marker is gone. Returning `""` would make layers 2 to 4 pass over
    nothing; returning the whole document would make them pass over unrelated F5 and F6 code.
    Both are green, and neither means anything — which is the entire reason this function
    asserts instead of falling back.
    """
    upper = text.upper()
    stop_at = upper.find(closer.upper())
    assert stop_at != -1, (
        f"the {closer!r} marker is gone — the extracted region would be unbounded, and a "
        f"guard that scans the wrong bytes reports exactly the same green as one that passes"
    )
    start_at = upper.find(opener.upper())
    assert start_at != -1 and start_at < stop_at, (
        f"the {opener!r} marker is gone — every copy assertion in this module would be "
        f"scanning nothing, and a scan of nothing is indistinguishable from a clean scan"
    )
    begin = text.rfind(comment_open, 0, start_at)
    assert begin != -1, f"no {comment_open!r} precedes the {opener!r} marker; region unbounded"
    end = text.find("*/", stop_at) if comment_open == "/*" else text.find("-->", stop_at)
    assert end != -1, f"no comment close follows the {closer!r} marker; region unbounded"
    return text[begin : end + (2 if comment_open == "/*" else 3)]


def js_string_literals(js: str) -> list[str]:
    """Every string literal in `js`, in source order, with its escapes resolved.

    Fed COMMENT-STRIPPED text, so a sentence quoted inside an explanatory comment is not
    mistaken for shipped copy. Escapes are resolved so the pinned tuple below reads as prose
    rather than as source: `\\'` in the file is an apostrophe on the page.
    """
    out: list[str] = []
    index = 0
    length = len(js)
    while index < length:
        char = js[index]
        if char not in "'\"`":
            index += 1
            continue
        quote = char
        cursor = index + 1
        buf: list[str] = []
        while cursor < length:
            here = js[cursor]
            if here == "\\" and cursor + 1 < length:
                nxt = js[cursor + 1]
                buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                cursor += 2
                continue
            if here == quote:
                break
            buf.append(here)
            cursor += 1
        out.append("".join(buf))
        index = cursor + 1
    return out


@pytest.fixture(scope="module")
def js_text() -> str:
    return FORECAST_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html_text() -> str:
    return FORECAST_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css_text() -> str:
    return FORECAST_CSS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def f7_js_region(js_text: str) -> str:
    return region_between(js_text, F7_MARKER, F7_END_MARKER)


@pytest.fixture(scope="module")
def f7_css_region(css_text: str) -> str:
    return region_between(css_text, F7_MARKER, F7_END_MARKER)


@pytest.fixture(scope="module")
def copy_block(f7_js_region: str) -> str:
    return region_between(f7_js_region, COPY_MARKER, COPY_END_MARKER)


@pytest.fixture(scope="module")
def copy_code(copy_block: str) -> str:
    return strip_js(copy_block)


@pytest.fixture(scope="module")
def outside_copy_code(f7_js_region: str, copy_block: str) -> str:
    """The F7 JS region with the pinned block cut out, comments removed. The renderer."""
    at = f7_js_region.find(copy_block)
    assert at != -1, "the copy block is not a slice of the F7 region — extraction is broken"
    return strip_js(f7_js_region[:at] + f7_js_region[at + len(copy_block) :])


@pytest.fixture(scope="module")
def live() -> dict:
    return json.loads(LIVE_PAYLOAD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE_PAYLOAD.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def history() -> dict:
    return json.loads(HISTORY_PAYLOAD.read_text(encoding="utf-8"))


# ==========================================================================================
# LAYER 1 — CONTAINMENT
# ==========================================================================================


def test_layer1_f7_js_region_is_a_real_slice(f7_js_region: str, js_text: str) -> None:
    """The region is a substantial slice of a substantial file, not a stub."""
    assert len(js_text) > MINIMUM_F7_JS_REGION_BYTES, "forecast.js read as a stub"
    assert len(f7_js_region) >= MINIMUM_F7_JS_REGION_BYTES, (
        f"the F7 JS region is {len(f7_js_region)} bytes, below its "
        f"{MINIMUM_F7_JS_REGION_BYTES}-byte floor — the markers have moved or the region "
        f"has been gutted, and every guard below would be scanning almost nothing"
    )
    assert f7_js_region in js_text


def test_layer1_copy_block_is_a_real_slice(copy_block: str, copy_code: str) -> None:
    """The pinned block clears a byte floor both raw and comment-stripped.

    Both floors matter. The raw floor catches a re-worded marker that collapses the slice;
    the stripped floor catches the subtler case where the block is all comment and no copy,
    which would make Layer 2's literal pin trivially satisfied by an empty tuple.
    """
    assert len(copy_block) >= MINIMUM_COPY_BLOCK_BYTES, (
        f"the PANEL COPY block is {len(copy_block)} bytes, below its "
        f"{MINIMUM_COPY_BLOCK_BYTES}-byte floor"
    )
    assert len(copy_code) >= MINIMUM_COPY_CODE_BYTES, (
        f"the PANEL COPY block is {len(copy_code)} bytes of code, below its "
        f"{MINIMUM_COPY_CODE_BYTES}-byte floor — the block may be all comment"
    )


@pytest.mark.parametrize(
    ("text", "opener", "closer"),
    [
        ("var x = 1;\n/* ══ END PANEL COPY ══ */\n", COPY_MARKER, COPY_END_MARKER),
        ("/* ══ PANEL COPY ══ */\nvar x = 1;\n", COPY_MARKER, COPY_END_MARKER),
        ("nothing here at all\n", F7_MARKER, F7_END_MARKER),
    ],
)
def test_layer1_positive_control_a_missing_marker_raises(
    text: str, opener: str, closer: str
) -> None:
    """A gone marker fails loudly. It never yields "" and never yields the whole document."""
    with pytest.raises(AssertionError):
        region_between(text, opener, closer)


def test_layer1_no_long_literal_escapes_the_copy_block(outside_copy_code: str) -> None:
    """No sentence lives in the renderer.

    THIS IS THE ASSERTION THAT MAKES LAYERS 2 TO 4 MEAN ANYTHING. Without it, a sentence
    could be moved out of the pinned block into the renderer beside it, and every remaining
    layer would scan a shrunken block and report green over copy nobody is checking.
    """
    offenders = [
        literal
        for literal in js_string_literals(outside_copy_code)
        if len(literal) > OUTSIDE_LITERAL_MAX
    ]
    assert offenders == [], (
        f"string literals longer than {OUTSIDE_LITERAL_MAX} characters exist in the F7 JS "
        f"region OUTSIDE the pinned PANEL COPY block: {offenders!r}. Panel prose belongs "
        f"inside the block, where it is pinned; a sentence out here is unchecked."
    )


SYNTHETIC_REGION_TEMPLATE = (
    "/* {marker} */\n"
    "function renderSomething() {{ var s = {planted!r}; return s; }}\n"
    "/* {copy} */\n"
    "var COPY_CLOSER = 'short';\n"
    "/* {copy_end} */\n"
    "function renderMore() {{ return 1; }}\n"
    "/* {marker_end} */\n"
)


def test_layer1_positive_control_a_planted_literal_outside_the_block_fails() -> None:
    """The same code path, over a synthesized region, goes red on a planted sentence.

    A guard that has never been observed to fail is indistinguishable from one that cannot.
    """
    planted = "Tomorrow's number will land within two degrees of this one, we find."
    assert len(planted) > OUTSIDE_LITERAL_MAX
    sample = SYNTHETIC_REGION_TEMPLATE.format(
        marker=F7_MARKER,
        marker_end=F7_END_MARKER,
        copy=COPY_MARKER,
        copy_end=COPY_END_MARKER,
        planted=planted,
    )
    region = region_between(sample, F7_MARKER, F7_END_MARKER)
    block = region_between(region, COPY_MARKER, COPY_END_MARKER)
    at = region.find(block)
    outside = strip_js(region[:at] + region[at + len(block) :])
    offenders = [
        lit for lit in js_string_literals(outside) if len(lit) > OUTSIDE_LITERAL_MAX
    ]
    assert offenders == [planted], (
        "the containment scan did not see a sentence planted outside the block; "
        "it cannot be trusted to see a real one"
    )


def test_layer1_positive_control_a_clean_synthetic_region_passes() -> None:
    """The same path stays silent on a region whose only long literal is inside the block."""
    sample = SYNTHETIC_REGION_TEMPLATE.format(
        marker=F7_MARKER,
        marker_end=F7_END_MARKER,
        copy=COPY_MARKER,
        copy_end=COPY_END_MARKER,
        planted="short one",
    )
    region = region_between(sample, F7_MARKER, F7_END_MARKER)
    block = region_between(region, COPY_MARKER, COPY_END_MARKER)
    at = region.find(block)
    outside = strip_js(region[:at] + region[at + len(block) :])
    assert [lit for lit in js_string_literals(outside) if len(lit) > OUTSIDE_LITERAL_MAX] == []


#: Prose in, prose out. A DOM handle inside the pinned block is the beginning of a renderer
#: growing there, and a renderer that grows there is a place for a sentence to hide from the
#: literal pin above.
DOM_IN_COPY = (
    ("a document reference", re.compile(r"\bdocument\b")),
    ("the element builder", re.compile(r"\bel\s*\(")),
    ("a node insertion", re.compile(r"\bappendChild\b")),
    ("a read of page state", re.compile(r"\bstate\s*\.")),
)


@pytest.mark.parametrize(("what", "pattern"), DOM_IN_COPY, ids=[w for w, _ in DOM_IN_COPY])
def test_layer1_copy_block_contains_no_dom(
    what: str, pattern: re.Pattern[str], copy_code: str
) -> None:
    hit = pattern.search(copy_code)
    assert hit is None, (
        f"{what} appears inside the PANEL COPY block at offset {hit.start() if hit else -1} — "
        f"the block is string constants and pure templates only"
    )


@pytest.mark.parametrize(
    ("what", "pattern", "sample"),
    [
        (w, p, s)
        for (w, p), s in zip(
            DOM_IN_COPY,
            [
                "var n = document.getElementById('x');",
                "host.appendChild(el('p', 'c', 'text'));",
                "host.appendChild(node);",
                "var d = state.data.skill;",
            ],
        )
    ],
    ids=[w for w, _ in DOM_IN_COPY],
)
def test_layer1_positive_control_dom_patterns_fire(
    what: str, pattern: re.Pattern[str], sample: str
) -> None:
    assert pattern.search(sample) is not None, f"the {what} pattern cannot see a real hit"


# ==========================================================================================
# LAYER 2 — BYTE-PINNED COPY
# ==========================================================================================

#: EVERY string literal in the PANEL COPY block, in source order, escapes resolved.
#:
#: This is the ticket's actual deliverable. FORECAST-SPEC §6 lives in these bytes: the past
#: tense, the named window, the named lead, the labelled in-sample figure that is never
#: promoted, the sample-size correction, and the closer that refuses to become a forecast.
#: Editing one character of panel prose fails `test_layer2_copy_literals_are_byte_identical`.
#:
#: All three comparison variants are here, and all three are shipped. On the fixture payload
#: the 24 h blend came out WORSE than the best single model, so a lone "better than" template
#: would read fine on the live payload and say something untrue on the other one.
COPY_LITERALS: tuple[str, ...] = (
    "tie",
    "win",
    "loss",
    "tie",
    "better than the best single model",
    "level with the best single model",
    "worse than the best single model",
    " (",
    ", ",
    ") over the same period.",
    "Over the last ",
    " days at ",
    ", this blend's typical miss at a ",
    "-hour lead was ",
    " — ",
    "In-sample, on the ",
    " days the weights were fitted on, it was ",
    ".",
    "In-sample, on the ",
    " days the weights were fitted on, it was also ",
    "; the two differ by less than ",
    ", and at this lead the fit did not degrade on unseen days. That is a ",
    "-sample coincidence, not evidence that the fit generalised ",
    "better than it was measured to.",
    "That is ",
    " scored forecasts, which is roughly ",
    " independent days, not ",
    ".",
    "That is history, not a promise about this forecast.",
    "Several",
    " initialisations a day over ",
    " days share a weather regime, so the ~",
    " forecast-observation pairs at each lead are closer to ~",
    " independent days.",
    "The blend and best-single figures above are fabricated. The realized miss ",
    "below was measured from real observations at this site, so the two are not ",
    "comparable and the difference between them means nothing.",
    "Against the observations already in, the blend's realized miss at ",
    "this lead came out at ",
    ".",
    "That pools all ",
    " archived days, including the ",
    " the weights were fitted on, so it is not comparable to the ",
    "out-of-sample figure beside it, and neither number says anything about ",
    "this forecast.",
    "Those are the shaded cells from a ",
    "-hour lead onward on the strip above.",
    " ",
    " ",
    " ",
)


def test_layer2_copy_literals_are_byte_identical(copy_code: str) -> None:
    """Every panel sentence, byte for byte, in order.

    Order is part of the pin: a clause moved between templates changes which sentence reads
    which way round, and an unordered set comparison would not notice.
    """
    found = tuple(js_string_literals(copy_code))
    assert found == COPY_LITERALS, (
        "the pinned panel copy changed.\n"
        f"  in the file : {found!r}\n"
        f"  pinned here : {COPY_LITERALS!r}\n"
        "Panel prose is FORECAST-SPEC §6's enforcement surface. If this edit is intended, it "
        "has to be argued against §6 and against design-target §4, not just re-pinned."
    )


def copy_prose(copy_code: str) -> str:
    """The block's literals as one searchable blob, for the shape assertions below."""
    return "\n".join(js_string_literals(copy_code))


def test_layer2_all_three_comparison_variants_are_present(copy_code: str) -> None:
    """Better, level and worse — all shipped, all reachable, none a fallback."""
    for variant in ("better than", "level with", "worse than"):
        assert f"{variant} the best single model" in copy_prose(copy_code), (
            f"the {variant!r} comparison variant is gone; one of the two committed payloads "
            f"needs it, and without it that payload's panel would state something untrue"
        )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("typical miss", "typical error"),
        ("not a promise about this forecast.", "not a promise about this forecast!"),
        ("worse than the best single model", "level with the best single model"),
        (" independent days, not ", " independent days, or "),
    ],
)
def test_layer2_positive_control_one_edited_character_fails_the_pin(
    before: str, after: str, copy_block: str
) -> None:
    """ACCEPTANCE. Editing panel prose fails this module — proven, in memory, not asserted.

    `frontend/` is never opened for writing; the mutation happens on the extracted string and
    is run back through the SAME extractor the real pin uses.
    """
    assert before in copy_block, f"{before!r} is no longer in the block; the control is stale"
    tampered = tuple(js_string_literals(strip_js(copy_block.replace(before, after, 1))))
    assert tampered != COPY_LITERALS, (
        f"replacing {before!r} with {after!r} did not fail the byte pin; the pin cannot see "
        f"a real edit and is therefore worthless"
    )


# ------------------------------------------------------------------------------------------
# The non-circular anchor: the pinned templates, the live values, and design-target §4
# ------------------------------------------------------------------------------------------


def js_fmt(value: float, dp: int, signed: bool = False) -> str:
    """`fmt(v, dp, signed)` from `frontend/forecast.js:56-61`, mirrored.

    The mirror is pinned to the original by `test_layer2_the_formatter_mirror_matches_source`
    below, so it cannot silently diverge from the function it stands in for.
    """
    number = float(value)
    body = f"{number:.{dp}f}"
    return (("+" if (signed and number > 0) else "") + body).replace("-", TRUE_MINUS)


def js_unit(units: str) -> str:
    """`unitSymbol()` — `degF` becomes the degree glyph plus `F`, never retyped."""
    return re.sub(r"^deg", "°", str(units))


def with_unit(text: str, units: str) -> str:
    return f"{text} {js_unit(units)}"


COUNT_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def build_lead_sentence(payload: dict, lead: dict) -> str:
    """The per-lead sentence, assembled from `COPY_LITERALS` and the payload's own values.

    Deliberately assembled from the PINNED literals rather than from freshly typed prose: if
    the pin and this reconstruction were typed independently, the anchor test below would be
    comparing two of my own strings and proving nothing about the file.
    """
    meta = payload["meta"]
    units = meta["units"]
    days = payload["skill"]["window"]["days"]
    split = meta["weights_source"]["split"]
    pct = float(lead["improvement_pct"])
    tone = 1 if pct > 0.05 else (2 if pct < -0.05 else 0)
    comparison = COPY_LITERALS[4 + (0 if tone == 1 else (2 if tone == 2 else 1))]

    opening = (
        COPY_LITERALS[10]
        + str(days)
        + COPY_LITERALS[11]
        + str(meta["site"]["id"])
        + COPY_LITERALS[12]
        + str(lead["lead_h"])
        + COPY_LITERALS[13]
        + with_unit(js_fmt(lead["blend_mae"], 2), units)
        + COPY_LITERALS[14]
    )
    clause = (
        comparison
        + COPY_LITERALS[7]
        + str(lead["best_single_model"])
        + COPY_LITERALS[8]
        + with_unit(js_fmt(lead["best_single_mae"], 2), units)
        + COPY_LITERALS[9]
    )
    in_sample_text = with_unit(js_fmt(lead["blend_mae_in_sample"], 2), units)
    out_mae = float(lead["blend_mae"])
    fitted_mae = float(lead["blend_mae_in_sample"])
    if out_mae <= fitted_mae and (fitted_mae - out_mae) < 0.01:
        in_sample = (
            COPY_LITERALS[18]
            + str(split["train_days"])
            + COPY_LITERALS[19]
            + in_sample_text
            + COPY_LITERALS[20]
            + with_unit(js_fmt(0.01, 2), units)
            + COPY_LITERALS[21]
            + str(lead["n_test"])
            + COPY_LITERALS[22]
            + COPY_LITERALS[23]
        )
    else:
        in_sample = (
            COPY_LITERALS[15]
            + str(split["train_days"])
            + COPY_LITERALS[16]
            + in_sample_text
            + COPY_LITERALS[17]
        )
    sample = (
        COPY_LITERALS[24]
        + str(lead["n_test"])
        + COPY_LITERALS[25]
        + str(lead["independent_days_approx"])
        + COPY_LITERALS[26]
        + str(pairs_per_lead(lead["n_test"], split["train_days"], split["test_days"]))
        + COPY_LITERALS[27]
    )
    return " ".join([opening + clause, in_sample, sample, COPY_LITERALS[28]])


def build_basis_sentence(payload: dict) -> str:
    """`.skill-basis`'s sample-size sentence, from the pinned literals and the payload."""
    split = payload["meta"]["weights_source"]["split"]
    days = payload["skill"]["window"]["days"]
    first = payload["skill"]["by_lead"][0]
    pairs = pairs_per_lead(first["n_test"], split["train_days"], split["test_days"])
    runs = pairs / days
    opener = (
        COUNT_WORDS[int(runs)].capitalize()
        if float(runs).is_integer() and int(runs) < len(COUNT_WORDS)
        else COPY_LITERALS[29]
    )
    return (
        opener
        + COPY_LITERALS[30]
        + str(days)
        + COPY_LITERALS[31]
        + str(pairs)
        + COPY_LITERALS[32]
        + str(first["independent_days_approx"])
        + COPY_LITERALS[33]
    )


def pairs_per_lead(n_test: int, train_days: int, test_days: int) -> int:
    """`pairsPerLead()` — the whole window's pair count, from the test-split row count."""
    return round(n_test * (train_days + test_days) / test_days)


def blockquotes(section: str) -> list[str]:
    """The `>` blockquote paragraphs of a markdown section, unwrapped to single lines."""
    out: list[str] = []
    current: list[str] = []
    for line in section.splitlines():
        if line.startswith(">"):
            current.append(line[1:].strip())
        elif current:
            out.append(" ".join(current))
            current = []
    if current:
        out.append(" ".join(current))
    return out


@pytest.fixture(scope="module")
def design_target() -> str:
    return DESIGN_TARGET.read_text(encoding="utf-8")


def section_between(text: str, start: str, stop: str) -> str:
    begin = text.find(start)
    assert begin != -1, f"design-target §4 landmark {start!r} is gone; the anchor is unmoored"
    end = text.find(stop, begin)
    assert end != -1, f"design-target §4 landmark {stop!r} is gone; the anchor is unmoored"
    return text[begin:end]


def test_layer2_anchor_lead_sentences_reproduce_design_target_section_4(
    live: dict, design_target: str
) -> None:
    """THE NON-CIRCULAR ANCHOR.

    The pinned templates, with the LIVE payload's own values substituted in Python, must
    reproduce §4's three blockquotes byte for byte. Without this, Layer 2 would prove only
    that nobody edited `forecast.js` — it would pin whatever happened to be there. With it,
    the copy is pinned to a document written before the code and maintained separately.
    """
    section = section_between(
        design_target, "#### The three lead statements", "**The sample-size reason, once"
    )
    quoted = blockquotes(section)
    assert len(quoted) == 3, (
        f"design-target §4 no longer carries exactly three lead blockquotes (found "
        f"{len(quoted)}) — the anchor cannot be checked and must not be assumed"
    )
    built = [build_lead_sentence(live, lead) for lead in live["skill"]["by_lead"]]
    assert built == quoted, (
        "the panel copy, with the live payload's values substituted, no longer reproduces "
        "design-target §4 verbatim.\n"
        f"  built : {built!r}\n"
        f"  §4    : {quoted!r}"
    )


def test_layer2_anchor_basis_sentence_reproduces_design_target_section_4(
    live: dict, design_target: str
) -> None:
    """The `.skill-basis` sample-size sentence, anchored the same way."""
    section = section_between(
        design_target, "**The sample-size reason, once", "#### The 12-hour ordering"
    )
    quoted = blockquotes(section)
    assert len(quoted) == 1, "design-target §4's sample-size blockquote is gone"
    assert build_basis_sentence(live) == quoted[0], (
        f"the basis sentence no longer reproduces §4.\n"
        f"  built : {build_basis_sentence(live)!r}\n"
        f"  §4    : {quoted[0]!r}"
    )


def test_layer2_anchor_would_notice_a_reworded_template(live: dict, design_target: str) -> None:
    """Positive control for the anchor: a one-word change fails it.

    An anchor test that compares two strings neither of which can move is decoration.
    """
    section = section_between(
        design_target, "#### The three lead statements", "**The sample-size reason, once"
    )
    quoted = blockquotes(section)
    tampered = build_lead_sentence(live, live["skill"]["by_lead"][0]).replace(
        "typical miss", "expected miss", 1
    )
    assert tampered != quoted[0], "the anchor cannot tell a reworded sentence from the real one"


def test_layer2_the_formatter_mirror_matches_source(js_text: str) -> None:
    """`js_fmt` above stands in for `fmt()` in the file; pin the original so it cannot drift.

    If `forecast.js` changed how it rounds or how it signs a value, the anchor test would
    still pass — it would just be comparing the design target against a stale mirror. This is
    what stops that.
    """
    source = strip_js(js_text)
    body = re.search(
        r"var fmt = function \(v, dp, signed\) \{(.*?)\};", source, re.S
    )
    assert body is not None, "the shared formatter is gone from forecast.js"
    collapsed = re.sub(r"\s+", " ", body.group(1)).strip()
    assert collapsed == (
        "var n = Number(v); if (!isFinite(n)) return ''; "
        "return ((signed && n > 0) ? '+' : '') + n.toFixed(dp).replace('-', MINUS);"
    ), f"the formatter changed shape; js_fmt() in this module is now a stale mirror: {collapsed!r}"


def test_layer2_formatter_mirror_reproduces_the_published_display_values(live: dict) -> None:
    """Two decimals in prose, one on the improvement, and a REAL minus on a loss."""
    lead = live["skill"]["by_lead"][0]
    assert js_fmt(lead["blend_mae"], 2) == "1.92"
    assert js_fmt(lead["best_single_mae"], 2) == "2.11"
    assert js_fmt(lead["improvement_pct"], 1, True) == "+9.0"
    assert js_fmt(-12.5, 1, True) == f"{TRUE_MINUS}12.5"
    assert "-" not in js_fmt(-12.5, 1, True), "a loss rendered with an ASCII hyphen"


# ------------------------------------------------------------------------------------------
# The numeric cells beside the prose — pinned as derivations, never as baked strings
# ------------------------------------------------------------------------------------------

#: `exactValue()` — `String(Number(v))`, whatever precision the payload carries and not one
#: digit more. The 12 h in-sample figure is `1.973` in the payload and renders `1.973`,
#: DELIBERATELY NOT `1.9730`: a fixed decimal count would print a trailing zero the backtest
#: never measured. Python's `repr` and JS's `String(Number(...))` both emit the shortest
#: round-tripping decimal, which is why this mirror is sound for these values.
def js_exact_value(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def test_layer2_in_sample_cell_keeps_the_payloads_own_precision(live: dict) -> None:
    twelve = next(lead for lead in live["skill"]["by_lead"] if lead["lead_h"] == 12)
    assert js_exact_value(twelve["blend_mae_in_sample"]) == "1.973"
    assert js_exact_value(twelve["blend_mae"]) == "1.9661"


@pytest.mark.parametrize("baked", ["1.9730", "1.9661", "2.1066", "+9.0%", "1.973"])
def test_layer2_no_display_value_is_baked_into_the_frontend(baked: str) -> None:
    """The rendered figures are derived from the payload, never typed into the page.

    A baked value reads correctly on the payload it was copied from and lies about the other
    one. Both committed payloads are rendered by these same three files.
    """
    for path in (FORECAST_JS, FORECAST_CSS, FORECAST_HTML):
        assert baked not in path.read_text(encoding="utf-8"), (
            f"{baked!r} is typed into {path.name}; it would lie on the other payload"
        )


def test_layer2_improvement_cell_carries_the_percent_sign(outside_copy_code: str) -> None:
    """The IMPROVEMENT cell is a signed percentage and says so.

    `improveText` is `fmt(pct, 1, true)` — the one shared formatter, so the sign is a real
    U+2212 on a loss — and the unit is appended in the renderer, never inside a sentence.
    """
    collapsed = re.sub(r"\s+", " ", outside_copy_code)
    assert "skillNumCell(nums, 'IMPROVEMENT', improveText + '%');" in collapsed, (
        "the IMPROVEMENT cell no longer renders its value with a trailing percent sign"
    )


def test_layer2_improvement_cell_text_is_derived_for_both_payloads(
    live: dict, fixture: dict
) -> None:
    """`+9.0%` on the live 6 h win, `−12.5%` on the fixture 24 h loss — same code path.

    A loss is not de-emphasised, not clamped and not stripped of its sign; the only thing that
    differs between the two is the number and its tone token.
    """
    six = next(lead for lead in live["skill"]["by_lead"] if lead["lead_h"] == 6)
    assert js_fmt(six["improvement_pct"], 1, True) + "%" == "+9.0%"
    twenty_four = next(lead for lead in fixture["skill"]["by_lead"] if lead["lead_h"] == 24)
    assert js_fmt(twenty_four["improvement_pct"], 1, True) + "%" == f"{TRUE_MINUS}12.5%"


def test_layer2_the_exact_value_helper_adds_no_precision(outside_copy_code: str) -> None:
    """`String(Number(v))`, never `toFixed`.

    The 12 h in-sample figure is `1.973`. A fixed decimal count would render `1.9730` — a
    trailing zero the backtest never measured, on a figure whose fourth decimal place is the
    only thing that makes the 12 h ordering inspectable at all.
    """
    body = re.search(
        r"function exactValue\(v\) \{(.*?)\n  \}", outside_copy_code, re.S
    )
    assert body is not None, "exactValue() is gone from the F7 renderer"
    collapsed = re.sub(r"\s+", " ", body.group(1)).strip()
    assert collapsed == "var n = Number(v); return isFinite(n) ? String(n) : '';", (
        f"exactValue() changed shape and may now add or drop precision: {collapsed!r}"
    )


def test_layer2_the_percent_sign_never_lives_in_the_pinned_copy(
    copy_code: str, outside_copy_code: str
) -> None:
    """The improvement cell carries a `%`; the sentences do not.

    The panel states the comparison in WORDS in the prose and shows the signed percentage in
    a labelled numeric cell. A percent sign appearing inside the pinned block would mean a
    figure had migrated into a sentence, where its sign and its rounding stop being governed
    by the one shared formatter.
    """
    assert "%" not in copy_code, (
        "a percent sign appeared inside the PANEL COPY block — a numeric figure has migrated "
        "into panel prose"
    )
    assert "IMPROVEMENT" in outside_copy_code, (
        "the IMPROVEMENT cell label is gone from the F7 renderer"
    )


# ------------------------------------------------------------------------------------------
# #skill-beyond-fitted — the verbatim sentence and its digit scan
# ------------------------------------------------------------------------------------------

BEYOND_FITTED_ELEMENT = re.compile(
    r'<div class="skill-extrapolated" id="skill-beyond-fitted">(.*?)</div>', re.S
)


def test_layer2_beyond_fitted_text_node_is_design_target_section_4_verbatim(
    html_text: str, design_target: str
) -> None:
    """Leads past the fitted range: one sentence, and it is §4's, character for character."""
    found = BEYOND_FITTED_ELEMENT.search(html_text)
    assert found is not None, "#skill-beyond-fitted is gone from forecast.html"
    section = section_between(
        design_target, "#### Leads beyond 24 hours", "**No number appears"
    )
    quoted = blockquotes(section)
    assert len(quoted) == 1, "design-target §4's beyond-the-fitted-range blockquote is gone"
    assert found.group(1) == quoted[0], (
        f"#skill-beyond-fitted no longer carries §4's sentence verbatim.\n"
        f"  in html : {found.group(1)!r}\n"
        f"  §4      : {quoted[0]!r}"
    )


def test_layer4_no_digit_but_the_sentences_own_appears_near_beyond_fitted(
    html_text: str,
) -> None:
    """No MAE, no improvement figure, no sample size, no "roughly" — and no OTHER DIGIT.

    FORECAST-SPEC §7 is absolute here: the backtest measured nothing past 24 h, so the page
    has nothing to report there. The scan runs from the element through the end of the F7
    HTML region, comment-stripped, and the only digit runs permitted are the two `24`s in the
    sentence itself. An interpolated figure for a 42-hour lead is exactly the tuning §15 bans.
    """
    start = html_text.find('<div class="skill-extrapolated" id="skill-beyond-fitted">')
    assert start != -1, "#skill-beyond-fitted is gone from forecast.html"
    end_marker = html_text.upper().find(F7_END_MARKER.upper(), start)
    assert end_marker != -1, "the F7 HTML end marker is gone; the digit scan is unbounded"
    stop = html_text.find("-->", end_marker) + 3
    scanned = strip_html(html_text[start:stop])
    assert len(scanned.strip()) > 100, "the digit-scan slice read as a stub"
    assert re.findall(r"\d+", scanned) == ["24", "24"], (
        f"a digit other than the sentence's own two `24`s appears in or beside "
        f"#skill-beyond-fitted: {re.findall(r'[0-9]+', scanned)!r}"
    )


@pytest.mark.parametrize(
    "planted",
    [
        '<div id="skill-beyond-fitted">... beyond a 24-hour lead, roughly 3.1 °F.</div>',
        '<div id="skill-beyond-fitted">... 24-hour weights</div><p>42 hours: 2.4</p>',
    ],
)
def test_layer4_positive_control_the_digit_scan_fires(planted: str) -> None:
    assert re.findall(r"\d+", strip_html(planted)) != ["24", "24"], (
        "the digit scan cannot see a number smuggled in beside the extrapolation sentence"
    )


# ==========================================================================================
# LAYER 3 — the allowlisted blacklist, the semantic markers, and the CSS prose
# ==========================================================================================

#: The letter `c`, written as an escape. `\bconfiden` would otherwise put a BANLIST word into
#: this source, and a later run of F5's file-wide gate over `tests/` would trip on its own
#: guard. Same device F5 and F6 use, for the same reason.
_C = "\x63"

#: Promise-shaped phrasings. FORECAST-SPEC §6: nothing on this page is phrased as a
#: probability or a promise, and no skill statement leaves the past tense.
#:
#: THIS IS A TRIPWIRE, NOT A SEMANTIC JUDGE. See limit 2 in the module docstring.
PROMISE_BLACKLIST: tuple[str, ...] = (
    r"will\s+(be|have|stay)",
    r"going to",
    r"\bexpect",
    r"\bpredict",
    r"\banticipate",
    r"accurate to",
    r"within \d",
    r"margin of error",
    r"plus or minus",
    r"give or take",
    r"\bchance\b",
    r"\bodds\b",
    r"\blikely\b",
    r"\b" + _C + r"onfiden",
    r"\bguarantee",
    r"\bpromis",
    r"\bshould be\b",
    r"\btypically within\b",
)

BLACKLIST_IDS = [f"promise{index}" for index in range(len(PROMISE_BLACKLIST))]

#: One sample per alternative, so a single mangled boundary cannot hide behind the others.
BLACKLIST_SAMPLES: tuple[str, ...] = (
    "the value will be close to this one",
    "it is going to land near here",
    "we expect it to hold",
    "the model predicts a warm afternoon",
    "we anticipate a small miss",
    "accurate to half a degree",
    "within 2 degrees, reliably",
    "quoted with a margin of error",
    "give or take two degrees, plus or minus a little",
    "give or take two degrees",
    "there is a good chance of that",
    "the odds are good",
    "a warm afternoon is likely",
    "we are " + _C + "onfident in this figure",
    "we guarantee this number",
    "we promise it lands here",
    "it should be about right",
    "typically within a degree",
)


def test_layer3_every_alternative_has_a_sample() -> None:
    """`zip` truncates silently; an unpaired alternative would never be positive-controlled."""
    assert len(BLACKLIST_SAMPLES) == len(PROMISE_BLACKLIST)

#: EVERY blacklist hit in the scanned prose must be covered by one of these, matched verbatim
#: and spanning the hit. Both entries are honest, past-tense sentences that a plain blacklist
#: would reject — which is exactly why the allowlist exists and exactly why it is pinned.
#:
#:   * the first is `COPY_CLOSER`, the closer on every per-lead sentence;
#:   * the second is the LIVE payload's server-authored `skill.note`.
#:
#: Nothing is allowlisted by pattern. A phrase not in this tuple fails, whatever it means.
SANCTIONED: tuple[str, ...] = (
    "That is history, not a promise about this forecast.",
    "History, not a prediction about this forecast.",
)


def blacklist_hits(text: str) -> list[tuple[str, int, int, str]]:
    """Every `(pattern, start, end, matched)` the blacklist finds, case-insensitively."""
    out: list[tuple[str, int, int, str]] = []
    for pattern in PROMISE_BLACKLIST:
        for found in re.finditer(pattern, text, re.I):
            out.append((pattern, found.start(), found.end(), found.group(0)))
    return sorted(out, key=lambda hit: (hit[1], hit[2]))


def unsanctioned_hits(text: str) -> list[tuple[str, int, int, str]]:
    """The hits NOT covered by a `SANCTIONED` phrase occurring verbatim across them.

    Span-based on purpose. Allowlisting the matched token alone would let "we promise a
    two-degree miss" through on the strength of the closer's "not a promise about this
    forecast"; requiring a sanctioned phrase to physically cover the hit does not.
    """
    spans: list[tuple[int, int]] = []
    for phrase in SANCTIONED:
        at = text.find(phrase)
        while at != -1:
            spans.append((at, at + len(phrase)))
            at = text.find(phrase, at + 1)
    return [
        hit
        for hit in blacklist_hits(text)
        if not any(begin <= hit[1] and hit[2] <= end for begin, end in spans)
    ]


@pytest.mark.parametrize(
    ("pattern", "sample"), list(zip(PROMISE_BLACKLIST, BLACKLIST_SAMPLES)), ids=BLACKLIST_IDS
)
def test_layer3_positive_control_every_alternative_fires(pattern: str, sample: str) -> None:
    """Each alternative proven to match on its own — a broken one cannot hide behind the rest."""
    assert re.search(pattern, sample, re.I) is not None, (
        f"the {pattern!r} alternative matches nothing; it is decoration"
    )


def test_layer3_panel_copy_carries_no_unsanctioned_promise(copy_code: str) -> None:
    hits = unsanctioned_hits("\n".join(js_string_literals(copy_code)))
    assert hits == [], (
        f"promise-shaped phrasing in the panel copy: {[hit[3] for hit in hits]!r}. Every skill "
        f"statement is past tense and stops there (FORECAST-SPEC §6)."
    )


def test_layer3_sanctioned_phrases_do_trip_the_blacklist() -> None:
    """DIRECTION ONE. Each allowlist entry really is a false positive being excused.

    An entry that matches nothing would mean the pattern it was written for is broken, and
    the allowlist would be quietly covering for it.
    """
    for phrase in SANCTIONED:
        assert blacklist_hits(phrase), (
            f"{phrase!r} is allowlisted but trips no blacklist alternative — either the "
            f"phrase is stale or the pattern it excuses has stopped working"
        )


def test_layer3_sanctioned_phrases_are_allowed() -> None:
    """DIRECTION TWO. The honest sentences the blacklist rejects are let through."""
    for phrase in SANCTIONED:
        assert unsanctioned_hits(phrase) == [], f"{phrase!r} is sanctioned but still rejected"


@pytest.mark.parametrize(
    "promise",
    [
        "This blend will be within 2 degrees of the observation.",
        "We are " + _C + "onfident tomorrow's number is accurate to half a degree.",
        "That is history, and a promise about this forecast.",
        "There is a good chance this holds.",
    ],
)
def test_layer3_unsanctioned_promise_is_rejected(promise: str) -> None:
    """The allowlist is not a loophole: a promise not in `SANCTIONED` fails."""
    assert unsanctioned_hits(promise) != [], (
        f"{promise!r} passed the allowlisted blacklist; the allowlist has become a loophole"
    )


def test_layer3_allowlist_does_not_excuse_a_promise_that_merely_shares_a_word() -> None:
    """A sanctioned phrase covers ITS OWN span and no other occurrence of the same token."""
    text = SANCTIONED[0] + " We also promise it lands within 2 degrees."
    hits = unsanctioned_hits(text)
    assert [hit[3].lower() for hit in hits] == ["promis", "within 2"], (
        f"the span check let a second, unsanctioned use through: {hits!r}"
    )


@pytest.mark.parametrize("field", ["basis", "note"])
def test_layer3_server_authored_prose_carries_no_unsanctioned_promise(
    field: str, live: dict, fixture: dict
) -> None:
    """`skill.basis` and `skill.note` reach the page verbatim, so they are scanned too.

    READ-ONLY, and over the TWO COMMITTED payloads only — see limit 3 in the module
    docstring. This module cannot police a payload that does not exist yet.
    """
    for name, payload in (("live", live), ("fixture", fixture)):
        value = payload["skill"].get(field)
        if value is None:
            continue
        hits = unsanctioned_hits(str(value))
        assert hits == [], (
            f"promise-shaped phrasing in the {name} payload's skill.{field}: "
            f"{[hit[3] for hit in hits]!r} — it renders verbatim on the page"
        )


def test_layer3_the_fixture_note_reaches_the_page_saying_it_is_fabricated(
    fixture: dict,
) -> None:
    """The one server string whose whole job is to be believed."""
    assert fixture["skill"]["note"].startswith("FABRICATED. Nothing here was measured."), (
        "the fixture's disclaimer changed; a synthetic payload that does not say so is worse "
        "than no fixture at all"
    )


def test_layer3_the_server_prose_scan_is_not_scanning_nothing(live: dict, fixture: dict) -> None:
    """The haystack proof for the payload scan: both notes are real, substantial strings."""
    for name, payload in (("live", live), ("fixture", fixture)):
        note = payload["skill"].get("note")
        assert isinstance(note, str) and len(note) > 60, f"{name} skill.note read as a stub"


# ------------------------------------------------------------------------------------------
# CSS prose — the only reason a `content:` string is visible to this module at all
# ------------------------------------------------------------------------------------------

CSS_CONTENT = re.compile(r"content\s*:\s*(['\"])(.*?)\1", re.S)


def test_layer3_css_content_prose_carries_no_unsanctioned_promise(f7_css_region: str) -> None:
    """A `content:` string is copy the stylesheet writes. Scanned — inside the F7 region only."""
    for _, value in CSS_CONTENT.findall(strip_css(f7_css_region)):
        assert unsanctioned_hits(value) == [], (
            f"promise-shaped phrasing in a CSS content string: {value!r}"
        )


def test_layer3_positive_control_the_css_content_extractor_finds_a_planted_string() -> None:
    """The extractor is proven able to see one, since the real region currently has none."""
    planted = '.x::after { content: "we expect a small miss"; }'
    found = CSS_CONTENT.findall(strip_css(planted))
    assert [value for _, value in found] == ["we expect a small miss"]
    assert unsanctioned_hits(found[0][1]) != [], "CSS prose is not actually being blacklisted"


# ------------------------------------------------------------------------------------------
# Layer 4's semantic markers on the lead template
# ------------------------------------------------------------------------------------------

#: The load-bearing shapes of the per-lead sentence: it names its window, states the measured
#: value in the past tense, labels the in-sample figure, corrects the sample size, and closes
#: by refusing to become a forecast. A rewrite that dropped any one of them would still be
#: byte-pinned by Layer 2 — this is what says WHY each pinned phrase is there.
LEAD_MARKERS: tuple[tuple[str, str], ...] = (
    ("names the window", "Over the last "),
    ("states the measured value in the past tense", " was "),
    ("labels the in-sample figure", "In-sample, on the "),
    ("corrects the sample size", " independent days, not "),
    ("refuses to become a forecast", "That is history, not a promise about this forecast."),
)


@pytest.mark.parametrize(
    ("what", "marker"), LEAD_MARKERS, ids=[what for what, _ in LEAD_MARKERS]
)
def test_layer3_lead_sentence_carries_its_marker(
    what: str, marker: str, live: dict, fixture: dict
) -> None:
    """Every lead, on BOTH payloads — including the fixture's 24 h loss."""
    for name, payload in (("live", live), ("fixture", fixture)):
        for lead in payload["skill"]["by_lead"]:
            built = build_lead_sentence(payload, lead)
            assert marker in built, (
                f"the {name} payload's {lead['lead_h']} h sentence no longer {what}: {built!r}"
            )


@pytest.mark.parametrize(
    ("what", "marker"), LEAD_MARKERS, ids=[what for what, _ in LEAD_MARKERS]
)
def test_layer3_positive_control_marker_absence_is_detectable(what: str, marker: str) -> None:
    assert marker not in "a sentence that carries none of the required shapes at all"


# ------------------------------------------------------------------------------------------
# The fabricated-vs-measured statement, and the two misreadings it exists to close
# ------------------------------------------------------------------------------------------

#: `COPY_SYNTHETIC_MIXING`, reassembled from the PINNED literals rather than retyped, for the
#: same reason `build_lead_sentence` is: a retyped copy would let this section pass against a
#: sentence that is no longer the one in the file.
#:
#: WHY THE SENTENCE EXISTS. On a fixture payload the panel shows a FABRICATED backtest figure
#: and, in the same `.skill-lead`, a realized figure loaded from the real archive by a
#: separate request that no fixture replaces. The page banner says the FORECAST is synthetic
#: and says nothing about the archive, so it leaves both available readings wrong: a viewer
#: who trusts the banner discards a real measurement, and a viewer reading the two figures
#: side by side draws a conclusion from the difference between an invention and an
#: observation. FORECAST-SPEC §15 calls a fixture mistakable for a real forecast the worst
#: failure of this page; an unremarked mixture is that failure wearing a banner.
MIXING_STATEMENT = "".join(COPY_LITERALS[34:37])


def test_layer2_the_mixing_statement_slice_is_the_right_three_literals() -> None:
    """The slice above really is the statement, not three neighbouring fragments.

    `MIXING_STATEMENT` is an index slice, and an index slice silently follows any literal
    inserted before it. Every assertion in this section would then be made about the wrong
    string while still reporting green, which is the fake-green shape this module exists to
    refuse.
    """
    assert MIXING_STATEMENT.startswith("The blend and best-single figures above are fabricated.")
    assert MIXING_STATEMENT.endswith("the difference between them means nothing.")
    assert len(MIXING_STATEMENT) > 150, "the mixing statement slice collapsed to a fragment"


def test_layer2_the_mixing_statement_lives_inside_the_pinned_block(
    copy_code: str, outside_copy_code: str
) -> None:
    """Prose in the pinned block, its gate in the renderer — and never the other way round.

    The statement is the only new sentence in the panel that a reader is asked to trust ABOUT
    the other sentences, so it is the last one that may sit unpinned in the renderer.
    """
    assert MIXING_STATEMENT in "".join(js_string_literals(copy_code)), (
        "the fabricated-vs-measured statement is not composed inside the PANEL COPY block"
    )
    assert "fabricated" not in outside_copy_code, (
        "the word 'fabricated' appears in the F7 renderer; the statement, or a second copy of "
        "it, has escaped the pinned block where it can be checked"
    )


#: LAYER 4's per-sentence markers for the statement — the load-bearing shapes, each one of
#: which the ticket named and any one of which a rewrite could quietly drop while staying
#: byte-pinned by Layer 2. This is what says WHY each pinned phrase is there.
MIXING_MARKERS: tuple[tuple[str, str], ...] = (
    ("names the figures above as fabricated", "figures above are fabricated"),
    ("names the realized figure as measured, in the past tense", "was measured from real "),
    ("says the measurement came from observations", "observations at this site"),
    ("refuses the comparison outright", "the two are not comparable"),
    ("says the difference carries no meaning", "the difference between them means nothing"),
)


@pytest.mark.parametrize(
    ("what", "marker"), MIXING_MARKERS, ids=[what for what, _ in MIXING_MARKERS]
)
def test_layer3_mixing_statement_carries_its_marker(what: str, marker: str) -> None:
    assert marker in MIXING_STATEMENT, (
        f"the fabricated-vs-measured statement no longer {what}: {MIXING_STATEMENT!r}"
    )


@pytest.mark.parametrize(
    ("what", "marker"), MIXING_MARKERS, ids=[what for what, _ in MIXING_MARKERS]
)
def test_layer3_positive_control_mixing_marker_absence_is_detectable(
    what: str, marker: str
) -> None:
    """Each marker proven absent from a sentence that carries none of the required shapes."""
    assert marker not in "This block mixes two kinds of number, which is worth knowing."


def test_layer3_mixing_statement_trips_no_blacklist_alternative_at_all() -> None:
    """DIRECTION ONE. It passes the claims blacklist OUTRIGHT, not by allowlist.

    `SANCTIONED` exists for honest sentences a blunt pattern cannot help catching, and every
    entry in it is a standing hole in the tripwire. This sentence needed no such hole, so it
    was written not to need one — and that is asserted rather than assumed, because the
    cheapest way to make a new sentence "pass" would have been to add it to the allowlist.
    """
    assert blacklist_hits(MIXING_STATEMENT) == [], (
        f"the fabricated-vs-measured statement trips the claims blacklist: "
        f"{[hit[3] for hit in blacklist_hits(MIXING_STATEMENT)]!r}"
    )
    assert unsanctioned_hits(MIXING_STATEMENT) == []
    assert MIXING_STATEMENT not in SANCTIONED, (
        "the statement was added to the allowlist rather than written to pass the blacklist"
    )


@pytest.mark.parametrize(
    "rewritten",
    [
        "The figures above are fabricated, so the realized miss below is likely closer.",
        "The figures above are fabricated; we expect the realized miss to be the honest one.",
        "The figures above are fabricated. The realized miss below is accurate to half a "
        "degree, so read that one.",
        "The figures above are fabricated, and the real forecast will be within 2 degrees.",
    ],
)
def test_layer3_positive_control_a_promise_shaped_rewrite_is_rejected(rewritten: str) -> None:
    """DIRECTION TWO. The blacklist really is running over this sentence's shape.

    A sentence that trips nothing proves nothing on its own — it could be a sentence the
    scanner never saw. These are the same sentence, rewritten into a claim, and every one of
    them must fail the identical call the assertion above makes.
    """
    assert unsanctioned_hits(rewritten) != [], (
        f"a promise-shaped version of the statement passed the blacklist: {rewritten!r}"
    )


def test_layer3_mixing_statement_names_no_payload_value(fixture: dict, live: dict) -> None:
    """No model, no site, no lead hour, no figure — nothing that differs between payloads.

    A statement about which numbers are fabricated must be true on both payloads it renders
    against, and it renders against exactly one of them. A typed payload value would make it
    read correctly beside one figure and wrongly beside the next.
    """
    assert re.search(r"\d", MIXING_STATEMENT) is None, (
        f"a digit appears in the statement: {MIXING_STATEMENT!r}"
    )
    assert "%" not in MIXING_STATEMENT
    assert TRUE_MINUS not in MIXING_STATEMENT
    lowered = MIXING_STATEMENT.lower()
    for payload in (live, fixture):
        for model in payload["meta"]["models_included"]:
            assert model.lower() not in lowered, f"{model!r} is typed into the statement"
        site = payload["meta"]["site"]
        assert str(site["id"]).lower() not in lowered
        assert str(site.get("name", "\x00")).lower() not in lowered


def test_layer3_mixing_statement_is_only_true_when_the_payload_is_synthetic(
    live: dict, fixture: dict
) -> None:
    """THE CONDITION THE SENTENCE ASSERTS, CHECKED AGAINST THE TWO COMMITTED PAYLOADS.

    The statement says the backtest figures are fabricated. That is true of the fixture and
    FALSE of the live payload, which is why it may never render on the live one — a page that
    called measured figures fabricated would be lying in the other direction, and discarding
    real work is not the safe failure it looks like.
    """
    assert fixture["meta"]["is_synthetic"] is True, (
        "the fixture no longer declares itself synthetic; the statement's gate would never "
        "fire and the mixture would render unremarked"
    )
    assert live["meta"]["is_synthetic"] is False, (
        "the live payload now declares itself synthetic; the statement would render over "
        "measured figures and call them fabricated"
    )


# ==========================================================================================
# LAYER 4 — both-payload cross-checks, and the per-lead re-split
# ==========================================================================================


def test_layer4_best_single_model_varies_by_lead_on_the_fixture(
    fixture: dict, live: dict
) -> None:
    """A hardcoded model name would read fine on one payload and lie on the other.

    The brief's intuition was that NOAA's own blend would win. On the live payload the same
    model wins at all three leads; on the fixture three DIFFERENT models do. The name is read
    from `best_single_model` and rendered, and the copy follows the data either way.
    """
    fixture_names = [lead["best_single_model"] for lead in fixture["skill"]["by_lead"]]
    assert len(set(fixture_names)) == 3, (
        f"the fixture's best single model no longer varies by lead ({fixture_names!r}) — the "
        f"payload that proves a typed model name would lie has stopped proving it"
    )
    live_names = [lead["best_single_model"] for lead in live["skill"]["by_lead"]]
    assert len(set(live_names)) == 1, (
        f"the live payload's best single model is no longer the same at all three leads "
        f"({live_names!r}); §4's table and this cross-check have diverged"
    )


def test_layer4_the_fixture_carries_a_loss_at_the_longest_fitted_lead(fixture: dict) -> None:
    """§4's "better than the best single model" is FALSE on one committed payload.

    That is the whole reason all three comparison variants ship. It also has to render at the
    same size, position and weight as a win — a rule the CSS guard module enforces; here the
    only claim is that the loss exists and that the copy has a sentence for it.
    """
    by_lead = {lead["lead_h"]: lead for lead in fixture["skill"]["by_lead"]}
    assert by_lead[24]["improvement_pct"] == -12.5
    assert by_lead[24]["blend_mae"] > by_lead[24]["best_single_mae"]
    built = build_lead_sentence(fixture, by_lead[24])
    assert "worse than the best single model" in built, (
        f"the fixture's 24 h loss did not select the loss variant: {built!r}"
    )
    assert TRUE_MINUS + "12.5" == js_fmt(by_lead[24]["improvement_pct"], 1, True)


def test_layer4_improvement_is_positive_at_every_live_lead(live: dict) -> None:
    for lead in live["skill"]["by_lead"]:
        assert lead["improvement_pct"] > 0
        assert "better than the best single model" in build_lead_sentence(live, lead)


def test_layer4_sample_sizes_differ_between_the_payloads(live: dict, fixture: dict) -> None:
    """A typed sample size lies on one of the two payloads."""
    live_sizes = {(lead["n_test"], lead["independent_days_approx"]) for lead in live["skill"]["by_lead"]}
    fixture_sizes = {
        (lead["n_test"], lead["independent_days_approx"]) for lead in fixture["skill"]["by_lead"]
    }
    assert live_sizes == {(40, 30)}
    assert fixture_sizes == {(44, 33)}
    assert live_sizes.isdisjoint(fixture_sizes)


def test_layer4_pair_count_is_derived_not_typed(live: dict, fixture: dict) -> None:
    """`round(n_test * (train + test) / test)` — 120 live, 132 fixture."""
    for payload, expected in ((live, 120), (fixture, 132)):
        split = payload["meta"]["weights_source"]["split"]
        for lead in payload["skill"]["by_lead"]:
            assert (
                pairs_per_lead(lead["n_test"], split["train_days"], split["test_days"]) == expected
            )


def test_layer4_runs_per_day_is_integral_live_and_not_on_the_fixture(
    live: dict, fixture: dict
) -> None:
    """WHY BOTH BASIS VARIANTS SHIP.

    120 pairs over 30 days is 4 a day, a whole number, and the sentence can say "Four". 132
    over 30 days is 4.4, and a sentence that rounded it to "Four" would state a cadence the
    payload does not carry. Hence the unquantified opener.
    """
    live_runs = 120 / live["skill"]["window"]["days"]
    fixture_runs = 132 / fixture["skill"]["window"]["days"]
    assert live_runs == 4.0 and float(live_runs).is_integer()
    assert fixture_runs == 4.4 and not float(fixture_runs).is_integer()
    assert build_basis_sentence(live).startswith("Four initialisations a day over 30 days")
    assert build_basis_sentence(fixture).startswith("Several initialisations a day over 30 days")


def test_layer4_coincidence_clause_is_gated_on_the_data_not_on_a_lead_hour(
    live: dict, fixture: dict
) -> None:
    """It fires at 12 h on the live payload and NOWHERE on the fixture.

    A gate written as `lead === 12` would print the coincidence sentence on a refit where the
    coincidence had gone — a sentence about a specific 40-sample accident, asserted as a
    standing property of the 12-hour lead.
    """
    fired = [
        lead["lead_h"]
        for lead in live["skill"]["by_lead"]
        if "-sample coincidence" in build_lead_sentence(live, lead)
    ]
    assert fired == [12]
    assert [
        lead["lead_h"]
        for lead in fixture["skill"]["by_lead"]
        if "-sample coincidence" in build_lead_sentence(fixture, lead)
    ] == []
    twelve = next(lead for lead in live["skill"]["by_lead"] if lead["lead_h"] == 12)
    assert twelve["blend_mae"] < twelve["blend_mae_in_sample"], (
        "the 12 h ordering that the coincidence clause exists to explain has changed"
    )


# ------------------------------------------------------------------------------------------
# The realized figure, and the derivation that would have been wrong
# ------------------------------------------------------------------------------------------

#: `mean(|error_f|)` pooled over every archived entry at that lead — THE CORRECT DERIVATION.
POOLED_REALIZED_MAE = {6: 1.825250, 12: 1.971250, 24: 2.045500}

#: The mean of the per-day `mae_f` summaries — THE WRONG ONE. Named and tested rather than
#: merely avoided: the two agree closely enough at 24 h (2.0455 against 2.0052) that a
#: reviewer could take the difference for rounding, and the 12 h gap (1.9713 against 2.2713)
#: is what shows it is not. Day 1 is partial and carries no 24 h key at all, so a mean of
#: daily means silently reweights a short day equal to a full one.
MEAN_OF_DAILY_MAE = {6: 1.8958, 12: 2.2713, 24: 2.0052}

REALIZED_ROWS_PER_LEAD = 120


def entries_by_lead(history: dict) -> dict[int, list[dict]]:
    rows: dict[int, list[dict]] = {}
    for day in history["days"]:
        for entry in day["entries"]:
            rows.setdefault(int(entry["lead_h"]), []).append(entry)
    return rows


def test_layer4_pooled_realized_mae_is_the_published_derivation(history: dict) -> None:
    rows = entries_by_lead(history)
    assert sorted(rows) == [6, 12, 24]
    for lead, expected in POOLED_REALIZED_MAE.items():
        entries = rows[lead]
        assert len(entries) == REALIZED_ROWS_PER_LEAD, (
            f"lead {lead} carries {len(entries)} archived rows, not {REALIZED_ROWS_PER_LEAD} — "
            f"an unasserted join count is how an empty series scores perfectly"
        )
        pooled = sum(abs(float(entry["error_f"])) for entry in entries) / len(entries)
        assert round(pooled, 6) == expected


def test_layer4_the_mean_of_daily_means_is_a_different_number(history: dict) -> None:
    """The wrong derivation, named and asserted DIFFERENT, so the distinction is not luck."""
    for lead, expected in MEAN_OF_DAILY_MAE.items():
        daily = [
            float(day["mae_f"][str(lead)])
            for day in history["days"]
            if str(lead) in (day.get("mae_f") or {})
        ]
        assert len(daily) == 31, f"lead {lead} has {len(daily)} daily summaries, not 31"
        assert round(sum(daily) / len(daily), 4) == expected
        assert expected != round(POOLED_REALIZED_MAE[lead], 4), (
            f"the two derivations agree at lead {lead}; the distinction this module claims to "
            f"test has become a coincidence rather than a difference"
        )


def test_layer4_the_first_archived_day_is_partial_and_is_never_padded(history: dict) -> None:
    """Partial days are real. Skip them; never interpolate one into existence."""
    assert history["days"][0]["mae_f"] == {"6": 6.1, "12": 14.47}
    assert "24" not in history["days"][0]["mae_f"]
    assert len(history["days"]) == 32


# ------------------------------------------------------------------------------------------
# The re-split cross-check — A TEST, NEVER A DISPLAY
# ------------------------------------------------------------------------------------------

#: Reproducing the published in/out figures from the archived rows, per lead, with the
#: boundary at that lead's own first paired `valid_time` plus 20 days.
#:
#: THIS IS NOT RENDERED ANYWHERE, and `test_layer4_the_resplit_numbers_are_nowhere_in_the_page`
#: asserts it. It is a check that the published split is reproducible from the archive, not a
#: second set of numbers for the panel to quote.
RESPLIT_TOLERANCE = 0.002
RESPLIT_EXPECTED = {
    6: (1.7792, 1.9172),
    12: (1.9730, 1.9677),
    24: (2.0150, 2.1065),
}
PUBLISHED_SPLIT = {
    6: (1.7793, 1.9173),
    12: (1.9730, 1.9661),
    24: (2.0141, 2.1066),
}
RESPLIT_COUNTS = (80, 40)

#: THE GLOBAL BOUNDARY, AND WHY 6 h IS NOT LISTED HERE.
#:
#: A boundary taken from the EARLIEST paired `valid_time` across ALL leads reproduces the
#: per-lead split at 6 h EXACTLY — identical counts, identical figures. That is not a near
#: miss to be tolerated, it is arithmetic: 6 h is the shortest lead, so its first paired valid
#: time IS the global minimum, and the two boundaries are the same instant. Asserting "the
#: global boundary differs at every lead" would therefore be a FALSE claim that fails.
#:
#: It differs at 12 h and 24 h, where the archive starts later than the global minimum, and
#: those are the leads asserted below.
GLOBAL_BOUNDARY_DIFFERS = {
    12: ((79, 41), (1.9572, 1.9983)),
    24: ((77, 43), (2.0336, 2.0667)),
}

VALID_TIME = "%Y-%m-%dT%H:%M:%SZ"


def mean_abs_error(entries: list[dict]) -> float:
    assert entries, "an empty split scores perfectly and is fake — assert on the count first"
    return sum(abs(float(entry["error_f"])) for entry in entries) / len(entries)


def split_at(entries: list[dict], boundary: str) -> tuple[list[dict], list[dict]]:
    train = [entry for entry in entries if entry["valid_time"] < boundary]
    test = [entry for entry in entries if entry["valid_time"] >= boundary]
    return train, test


def boundary_after(first_valid_time: str, days: int = 20) -> str:
    from datetime import datetime, timedelta

    return (datetime.strptime(first_valid_time, VALID_TIME) + timedelta(days=days)).strftime(
        VALID_TIME
    )


def test_layer4_per_lead_resplit_reproduces_the_published_figures(history: dict) -> None:
    """Each lead's own first paired instant, plus 20 days, reproduces its published split."""
    rows = entries_by_lead(history)
    for lead, (want_in, want_out) in RESPLIT_EXPECTED.items():
        entries = sorted(rows[lead], key=lambda entry: entry["valid_time"])
        train, test = split_at(entries, boundary_after(entries[0]["valid_time"]))
        assert (len(train), len(test)) == RESPLIT_COUNTS, (
            f"lead {lead} re-split as {(len(train), len(test))}, not {RESPLIT_COUNTS}"
        )
        assert round(mean_abs_error(train), 4) == want_in
        assert round(mean_abs_error(test), 4) == want_out
        published_in, published_out = PUBLISHED_SPLIT[lead]
        assert abs(mean_abs_error(train) - published_in) <= RESPLIT_TOLERANCE
        assert abs(mean_abs_error(test) - published_out) <= RESPLIT_TOLERANCE


def test_layer4_a_global_boundary_differs_at_12h_and_24h(history: dict) -> None:
    """And COINCIDES at 6 h by construction — see `GLOBAL_BOUNDARY_DIFFERS` above.

    The plan for this ticket recorded the 6 h case as differing too (79/41, 77/43 quoted
    against all three leads). Recomputed, it does not: 6 h is the earliest lead and therefore
    sets the global minimum, so the two boundaries are the same instant there. Reported as the
    data says it, not as the plan wanted it.
    """
    rows = entries_by_lead(history)
    earliest = min(entry["valid_time"] for entries in rows.values() for entry in entries)
    boundary = boundary_after(earliest)

    six = sorted(rows[6], key=lambda entry: entry["valid_time"])
    assert six[0]["valid_time"] == earliest, "6 h is no longer the earliest lead in the archive"
    global_train, global_test = split_at(six, boundary)
    per_lead_train, per_lead_test = split_at(six, boundary_after(six[0]["valid_time"]))
    assert (len(global_train), len(global_test)) == RESPLIT_COUNTS
    assert round(mean_abs_error(global_train), 4) == RESPLIT_EXPECTED[6][0]
    assert round(mean_abs_error(global_test), 4) == RESPLIT_EXPECTED[6][1]
    assert len(global_train) == len(per_lead_train) and len(global_test) == len(per_lead_test)

    for lead, (counts, figures) in GLOBAL_BOUNDARY_DIFFERS.items():
        entries = sorted(rows[lead], key=lambda entry: entry["valid_time"])
        train, test = split_at(entries, boundary)
        assert (len(train), len(test)) == counts, (
            f"lead {lead} under a global boundary split as {(len(train), len(test))}, not "
            f"{counts} — the distinction between the two boundaries has changed"
        )
        assert (round(mean_abs_error(train), 4), round(mean_abs_error(test), 4)) == figures
        assert (len(train), len(test)) != RESPLIT_COUNTS


def test_layer4_the_resplit_numbers_are_nowhere_in_the_page() -> None:
    """A cross-check is not a second set of figures for the panel to quote.

    Any of these appearing in the shipped page would mean a number this module derived for
    verification had been promoted into copy, where it would sit beside the published split
    disagreeing with it in the fourth decimal place.
    """
    forbidden = [
        f"{value:.4f}"
        for pair in list(RESPLIT_EXPECTED.values())
        + [figures for _, figures in GLOBAL_BOUNDARY_DIFFERS.values()]
        for value in pair
    ] + [f"{value:.6f}" for value in POOLED_REALIZED_MAE.values()]
    for path in (FORECAST_JS, FORECAST_CSS, FORECAST_HTML):
        text = path.read_text(encoding="utf-8")
        hits = [value for value in forbidden if value in text]
        assert hits == [], f"re-split cross-check figures leaked into {path.name}: {hits!r}"


def test_layer4_the_leak_scan_is_not_scanning_nothing() -> None:
    """Haystack proof for the scan above: the three files exist and are substantial."""
    for path in (FORECAST_JS, FORECAST_CSS, FORECAST_HTML):
        assert isinstance(path, Path) and path.is_file()
        assert len(path.read_text(encoding="utf-8")) > 2000, f"{path.name} read as a stub"
