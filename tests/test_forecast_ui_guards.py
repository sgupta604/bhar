"""F5 Task 1.4 — the forecast page's UI gate, and the proofs that it is not vacuous.

WHY THIS FILE OPENS WITH AN ARGUMENT INSTEAD OF A TEST
-----------------------------------------------------
An earlier ticket's BANLIST gate could prove itself for free: the document it scanned
(`.claude/features/forecast-page/design-target.md`) *contains* the ban list, so running the
pattern over the unstripped file produces hits and the gate's own machinery is exercised by
its own subject.

`frontend/forecast.html`, `frontend/forecast.js` and `frontend/forecast.css` have no such
block and must contain ZERO banned strings by design. "The unstripped scan found hits" is
therefore structurally impossible here — and that is the whole problem, because a gate that
greps three files and finds nothing is indistinguishable, from its output alone, from a gate
that greps *nothing* and finds nothing. This project has shipped a guard that could not fail
three times. The proofs below are what stop it happening a fourth.

    PROOF 1 — the haystack is real.  `test_haystack_*` asserts the scanned set is exactly
    three paths, that each resolves under `frontend/`, exists, and is non-empty, with a
    positive minimum byte size on each. A typo'd path greps nothing and passes silently; that
    exact failure is named in two of this project's retrospectives.

    PROOF 2 — the pattern fires.  Every alternative in the BANLIST pattern is proven to match
    on its own, one parametrized case each, against a synthesized scratch file — so a single
    subtly broken alternative (a mangled word boundary, a typo) cannot hide behind the ten
    that still work. The pattern is then run against the real `design-target.md`, whose ban
    block does carry hits, proving it has not gone stale against real content, and it is
    proven byte-identical to the pattern recorded in that document.

    PROOF 3 — the gate goes red.  Each of the three real files is copied, the copy is proven
    clean, one banned token is injected into the copy, and the gate is re-run over it through
    the SAME code path the real gate uses. Three separate assertions, three observed
    failures. A guard that cannot fail is not a guard.

    PROOF 4 — the comment-aware guards can see a real hit.  Two of the static guards below
    would fire on the shipped files if they read raw text, because those files quote the very
    markup they forbid inside explanatory comments. `test_stripper_*_removes_real_content`
    asserts the raw file matches and the stripped file does not — a guard demonstrably able
    to see a hit in real content, which then correctly declines to count a comment as one.

MECHANISM: SUBPROCESS `grep`, NOT PYTHON `re`
---------------------------------------------
The gate shells out to `grep -nE` because the exit status is the contract and it is checked
explicitly: 1 = clean (no match, the only passing outcome), 0 = a banned string is present
(FAIL), and anything else — 2 in practice — is a grep ERROR and is ALSO A FAILURE. A gate
that treats exit 2 as success is the vacuous-pass bug in its purest form, so
`test_gate_treats_a_grep_error_as_a_failure_not_a_pass` runs the gate against a path that
does not exist and asserts it reports `error`, never `clean`.

A Python `re` cross-check runs alongside and must agree, and it reads the file text itself,
so the non-emptiness of what was scanned is asserted on the same bytes the verdict came from.

The word-boundary alternatives are verified working under both `/usr/bin/grep` and the
`ugrep 7.8.4` this machine resolves `grep` to. They are not to be "fixed".

NO BANNED STRING IS TYPED LITERALLY IN THIS FILE
------------------------------------------------
A test file that names the tokens it bans is a liability: a future run of this very gate over
`tests/` would trip on its own guard. So every banned token is assembled at import time from
an escaped first character (`_C`, `_P`, `_U`, `_E` below), and the plus-or-minus character is
written as a unicode escape and never as the glyph. Grepping this source for any banned
string returns nothing; grepping the values it *builds* returns all of them.

SCOPE
-----
`tests/test_live_guards.py` is deliberately NOT imported from and NOT edited — F2, F3 and F4
all left it alone and that precedent holds. The `git()` helper, the `git_repo` skip fixture
and `parse_numstat` below are F4's shapes, copied rather than shared, for the same reason.
Nothing here starts a server, opens a socket, or writes to `frontend/`. The only file under
`data/` it touches is `data/results.json`, read-only, to hash it.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"

#: The three files under test. Resolved from this file's location, never from the working
#: directory, so pytest's invocation cannot change what gets scanned.
FORECAST_HTML = FRONTEND / "forecast.html"
FORECAST_JS = FRONTEND / "forecast.js"
FORECAST_CSS = FRONTEND / "forecast.css"
SCANNED: tuple[Path, ...] = (FORECAST_HTML, FORECAST_JS, FORECAST_CSS)

#: The design document that records the ban. Read-only here, always.
DESIGN_TARGET = REPO / ".claude" / "features" / "forecast-page" / "design-target.md"

#: The portal's shared theme script. `forecast.html` deliberately does not load it; the
#: mitigation for that decision is that the storage key literal must stay byte-identical.
THEME_JS = FRONTEND / "theme.js"

#: A floor, not an equality: these files are final for F5 but a later ticket may add to them.
#: The point is that a path typo produces a zero-byte read, and zero bytes is exactly what a
#: vacuous scan looks like from the inside.
MINIMUM_SCANNED_BYTES = 2000


# ------------------------------------------------------------------------------------------
# The BANLIST pattern, assembled so this source carries none of the tokens it bans
# ------------------------------------------------------------------------------------------

_C = "\x63"  # the letter c
_P = "\x70"  # the letter p
_U = "\x75"  # the letter u
_E = "\x65"  # the letter e

#: U+00B1. Written as an escape on purpose — see the module docstring.
PLUS_MINUS = "\u00b1"

#: The alternatives of the recorded pattern, in the recorded order, joined with `|` below.
#:
#: COUNT NOTE, STATED RATHER THAN PAPERED OVER: the ticket brief calls these "twelve
#: alternatives"; the pattern actually recorded in `design-target.md` has ELEVEN. The
#: banned-*name* list in that document does run to twelve entries, but one of them is a
#: prefixed variant already subsumed by a shorter alternative, so it is not a separate branch
#: of the pattern. The contract is the recorded pattern, and
#: `test_pattern_is_byte_identical_to_the_recorded_one` pins this file to it. Inventing a
#: twelfth branch to match the brief's prose would be tuning the experiment to produce a
#: better-looking result.
BANNED_ALTERNATIVES: tuple[str, ...] = (
    _C + "onfidence",
    _P + "robability",
    _P + "ercentile",
    _U + "ncertainty",
    _E + "rror_bar",
    _C + "i_low",
    _C + "i_high",
    r"\b" + _P + r"10\b",
    r"\b" + _P + r"50\b",
    r"\b" + _P + r"90\b",
    PLUS_MINUS,
)

RECORDED_ALTERNATIVE_COUNT = 11

BANLIST_PATTERN = "|".join(BANNED_ALTERNATIVES)

#: The same thing for the Python cross-check. `re` and POSIX ERE agree on every construct used.
BANLIST_RE = re.compile(BANLIST_PATTERN)

#: Readable ids for the per-alternative parametrizations, so pytest output does not print the
#: banned tokens back out into a terminal or a CI log.
ALTERNATIVE_IDS = [f"alt{index}" for index in range(len(BANNED_ALTERNATIVES))]


def banned_word(alternative: str) -> str:
    """The bare text an alternative matches, with any boundary assertions removed.

    Boundary assertions are zero-width: they constrain where a match may start and end, but
    they are not part of the text being matched. Dropping them yields the token to plant in a
    positive-control sample.
    """
    return alternative.replace("\\b", "")


# ------------------------------------------------------------------------------------------
# The gate mechanism — subprocess grep, with the exit status treated as the contract
# ------------------------------------------------------------------------------------------

CLEAN = "clean"
MATCHED = "matched"
ERROR = "error"


@pytest.fixture(scope="session")
def grep_binary() -> str:
    """The `grep` the gate shells out to — or a clean skip where there is none."""
    found = shutil.which("grep")
    if found is None:
        pytest.skip("grep is not available on PATH")
    return found


def run_grep(binary: str, pattern: str, path: Path) -> subprocess.CompletedProcess:
    """One `grep -nE <pattern> <path>` run. Read-only; never touches the file."""
    return subprocess.run(
        [binary, "-nE", pattern, str(path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


def gate_verdict(binary: str, pattern: str, path: Path) -> tuple[str, str]:
    """Run the gate over one file and classify grep's exit status.

    * 1 -> `clean` — no line matched. The only outcome that may pass.
    * 0 -> `matched` — a banned string is present. Failure.
    * anything else (2 in practice) -> `error` — an unreadable path, a missing file, a
      malformed pattern. FAILURE, NEVER A PASS. Collapsing this into `clean` is exactly how a
      gate ends up unable to fail, which is the bug this whole file exists to prevent.
    """
    result = run_grep(binary, pattern, path)
    if result.returncode == 1:
        return CLEAN, ""
    if result.returncode == 0:
        return MATCHED, result.stdout.strip()
    return ERROR, f"grep exited {result.returncode}: {(result.stderr or result.stdout).strip()}"


def grep_lines(binary: str, pattern: str, path: Path) -> list[str]:
    """Matching `line:text` records, with exit status 2 raised as a failure, not hidden."""
    result = run_grep(binary, pattern, path)
    assert result.returncode in (0, 1), (
        f"grep errored (exit {result.returncode}) scanning {path}: "
        f"{(result.stderr or result.stdout).strip()} — an errored scan is not a clean scan"
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def sources() -> dict[Path, str]:
    """The three files' text, read from disk at test time — never a pinned copy."""
    return {path: path.read_text(encoding="utf-8") for path in SCANNED}


# ==========================================================================================
# PROOF 1 — the haystack is real
# ==========================================================================================


def test_haystack_is_exactly_three_files() -> None:
    """The scanned set is three paths and no more. Count asserted, not assumed.

    A fourth path silently added, or a third silently dropped, changes what "the gate is
    green" means. This is the assertion that makes every other assertion in the file mean
    something.
    """
    assert len(SCANNED) == 3, f"expected exactly 3 scanned files, got {len(SCANNED)}: {SCANNED}"
    assert len(set(SCANNED)) == 3, f"the scanned set contains a duplicate: {SCANNED}"
    assert [path.name for path in SCANNED] == ["forecast.html", "forecast.js", "forecast.css"]


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_haystack_each_file_exists_and_is_not_empty(path: Path) -> None:
    """Each scanned path resolves under `frontend/`, exists, and carries real content.

    A TYPO'D PATH GREPS NOTHING AND PASSES SILENTLY — that exact failure is named in two of
    this project's retrospectives. The byte floor is what distinguishes "scanned a real file
    and found nothing" from "scanned an empty or absent file and found nothing".
    """
    assert path.parent == FRONTEND, f"{path} is not under {FRONTEND}"
    assert path.is_file(), (
        f"{path} does not exist — every scan below it would have been vacuous, and a vacuous "
        f"scan reports exactly the same green as a real one"
    )
    size = path.stat().st_size
    assert size >= MINIMUM_SCANNED_BYTES, (
        f"{path.name} is {size} bytes, below the {MINIMUM_SCANNED_BYTES}-byte floor — too "
        f"small to be the shipped file, so the gate would be scanning a stub"
    )
    assert path.read_text(encoding="utf-8").strip(), f"{path.name} is whitespace only"


def test_haystack_supporting_files_exist() -> None:
    """The two files the proofs lean on. Absent, they would make those proofs vacuous too."""
    assert DESIGN_TARGET.is_file(), f"{DESIGN_TARGET} is missing — positive control (b) is vacuous"
    assert THEME_JS.is_file(), f"{THEME_JS} is missing — the storage-key comparison is vacuous"


# ==========================================================================================
# PROOF 2 — the pattern fires, on every alternative, and on real content
# ==========================================================================================


def test_pattern_has_the_recorded_number_of_alternatives() -> None:
    """Pin the alternative count so one cannot be quietly dropped from the tuple.

    Dropping one would leave every other test in this file green — the three files match none
    of them either way — so nothing but this assertion would notice.
    """
    assert len(BANNED_ALTERNATIVES) == RECORDED_ALTERNATIVE_COUNT
    assert BANLIST_PATTERN.count("|") == RECORDED_ALTERNATIVE_COUNT - 1


def test_pattern_is_byte_identical_to_the_recorded_one() -> None:
    """The pattern this file builds is the one written into `design-target.md`, exactly.

    Extracted from the document rather than retyped: a retyped pattern drifts, and a drifted
    pattern is a gate that enforces something other than the ban it claims to enforce.
    """
    lines = DESIGN_TARGET.read_text(encoding="utf-8").splitlines()
    matches = [index for index, line in enumerate(lines, 1) if line.strip() == BANLIST_PATTERN]

    assert len(matches) == 1, (
        f"expected the recorded pattern on exactly one line of {DESIGN_TARGET.name}, found it "
        f"on {matches or 'no lines'} — either the pattern this file builds has drifted from "
        f"the recorded contract, or the document has been re-worded"
    )


@pytest.mark.parametrize("alternative", BANNED_ALTERNATIVES, ids=ALTERNATIVE_IDS)
def test_positive_control_a_pattern_fires_on_each_alternative_individually(
    alternative: str, tmp_path: Path, grep_binary: str
) -> None:
    """Positive control (a): every alternative matches ON ITS OWN, in a scratch file.

    Parametrized one case per alternative rather than asserted once over a file containing
    all of them: a single "the sample matches somewhere" assertion stays green when one
    alternative is subtly broken, because the other ten still fire. This does not.

    The sample is written to `tmp_path` and scanned by the same `gate_verdict` the real gate
    uses, so what is proven is the shipped mechanism and not a parallel one.
    """
    word = banned_word(alternative)
    sample = tmp_path / "sample.txt"
    sample.write_text(f"a line of ordinary prose\nand then {word} sitting in it\ntail\n", "utf-8")

    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, sample)

    assert verdict == MATCHED, (
        f"the BANLIST pattern did not fire on alternative {alternative!r} (verdict {verdict}, "
        f"{detail!r}) — that branch is broken and its token would walk through the gate"
    )
    assert word in detail, f"grep matched, but not on the planted token: {detail!r}"


@pytest.mark.parametrize("alternative", BANNED_ALTERNATIVES, ids=ALTERNATIVE_IDS)
def test_positive_control_a_python_cross_check_agrees_per_alternative(alternative: str) -> None:
    """The `re` cross-check fires on the same eleven tokens the grep run does."""
    word = banned_word(alternative)
    assert BANLIST_RE.search(f"prose {word} prose") is not None, f"re missed {alternative!r}"


def test_positive_control_a_sample_carrying_every_alternative_matches_every_line(
    tmp_path: Path, grep_binary: str
) -> None:
    """...and a file carrying all of them reports a hit on every line, not just the first."""
    words = [banned_word(alternative) for alternative in BANNED_ALTERNATIVES]
    sample = tmp_path / "all.txt"
    sample.write_text("".join(f"line {i} {w}\n" for i, w in enumerate(words)), encoding="utf-8")

    hits = grep_lines(grep_binary, BANLIST_PATTERN, sample)

    assert len(hits) == len(words), f"expected {len(words)} matching lines, got {len(hits)}: {hits}"


def test_word_boundary_alternatives_do_not_match_inside_a_longer_token() -> None:
    """The boundary assertions are load-bearing: a guard that fires on `top10th` is noise.

    Proven rather than trusted, because a mangled boundary is the failure mode that would let
    positive control (a) pass while the real gate over-fires on innocent content.
    """
    bounded = [alt for alt in BANNED_ALTERNATIVES if "\\b" in alt]
    assert len(bounded) == 3, f"expected three boundary-guarded alternatives, got {len(bounded)}"

    for alternative in bounded:
        word = banned_word(alternative)
        assert re.compile(alternative).search(f"x{word}y") is None, (
            f"{alternative!r} matched inside a longer token — its boundary is not working"
        )
        assert re.compile(alternative).search(f"a {word} b") is not None


def test_positive_control_b_pattern_fires_against_the_real_design_target(grep_binary: str) -> None:
    """Positive control (b): the pattern still matches REAL CONTENT, not just a synthetic.

    `design-target.md` carries the ban list itself, inside its marker-delimited block, so it
    is the one file in this repository that is *supposed* to match. If this goes quiet the
    pattern has gone stale against the document it is derived from, and the green on the
    three frontend files stops meaning anything.

    The document is read only. Nothing here rewrites it.
    """
    hits = grep_lines(grep_binary, BANLIST_PATTERN, DESIGN_TARGET)

    assert len(hits) >= 5, (
        f"the BANLIST pattern found only {len(hits)} line(s) in {DESIGN_TARGET.name}; its ban "
        f"block should carry several. The pattern has gone stale: {hits}"
    )

    numbers = sorted(int(hit.split(":", 1)[0]) for hit in hits)
    assert numbers[0] > 100, f"hits appear before the ban block at lines {numbers}"

    verdict, _ = gate_verdict(grep_binary, BANLIST_PATTERN, DESIGN_TARGET)
    assert verdict == MATCHED, f"gate_verdict disagreed with grep_lines on {DESIGN_TARGET.name}"


def test_positive_control_b_leaves_the_design_target_byte_identical(grep_binary: str) -> None:
    """The document's digest before and after a scan. Read-only means read-only."""
    before = hashlib.sha256(DESIGN_TARGET.read_bytes()).hexdigest()
    grep_lines(grep_binary, BANLIST_PATTERN, DESIGN_TARGET)
    assert hashlib.sha256(DESIGN_TARGET.read_bytes()).hexdigest() == before


# ==========================================================================================
# THE GATE — zero matches across the three files, with the exit status checked explicitly
# ==========================================================================================


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_gate_no_banned_string_in_any_scanned_file(path: Path, grep_binary: str) -> None:
    """The gate. Exit 1 (no match) is the only passing outcome; 0 and 2 both fail.

    Spelled out because the distinction is the whole point: `grep` answers "found something"
    with 0, "found nothing" with 1, and "I could not look" with 2. Treating 2 as success is
    the vacuous pass this file exists to make impossible, so it is named in the verdict and
    asserted on separately below.
    """
    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, path)

    assert verdict != ERROR, (
        f"the gate could not scan {path.name}: {detail}. An errored scan is NOT a clean scan "
        f"— grep exit 2 means the file was never read, so this is a failure, not a pass"
    )
    assert verdict == CLEAN, (
        f"{path.name} contains banned content that must never appear on the forecast page:\n"
        f"{detail}\nThe page states measured history, never a claim about tomorrow's number."
    )


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_gate_python_cross_check_agrees_and_the_bytes_were_actually_read(
    path: Path, sources: dict[Path, str]
) -> None:
    """The `re` cross-check, asserted on text this test read itself.

    Two independent engines reaching the same verdict rules out a pattern broken in one
    dialect only, and reading the text here means the non-emptiness of the haystack is
    asserted on the same bytes the verdict came from.
    """
    text = sources[path]
    assert text.strip(), f"{path.name} read as empty — the cross-check would be vacuous"
    assert len(text) >= MINIMUM_SCANNED_BYTES

    hit = BANLIST_RE.search(text)
    where = hit.start() if hit else -1
    what = hit.group(0) if hit else ""
    assert hit is None, (
        f"{path.name} matches the BANLIST pattern at offset {where}: {what!r} — the grep gate "
        f"and the re cross-check must always agree, and both must be clean"
    )


def test_gate_treats_a_grep_error_as_a_failure_not_a_pass(tmp_path: Path, grep_binary: str) -> None:
    """Exit 2 must classify as `error`. This is the single most important control here.

    A classifier that folds 2 into "clean" reports green for a path that does not exist —
    precisely the shape of the bug the haystack assertion also defends against, arriving by a
    different route.
    """
    missing = tmp_path / "there-is-no-such-file.txt"
    assert not missing.exists()

    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, missing)

    assert verdict == ERROR, f"a missing file classified as {verdict!r}, not {ERROR!r}"
    assert verdict != CLEAN
    assert "2" in detail, detail


def test_gate_distinguishes_all_three_verdicts(tmp_path: Path, grep_binary: str) -> None:
    """The three verdicts are genuinely three, not two with a synonym."""
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("nothing banned here at all\n", encoding="utf-8")
    dirty_file = tmp_path / "dirty.txt"
    dirty_file.write_text(f"a {banned_word(BANNED_ALTERNATIVES[0])} here\n", encoding="utf-8")

    assert gate_verdict(grep_binary, BANLIST_PATTERN, clean_file)[0] == CLEAN
    assert gate_verdict(grep_binary, BANLIST_PATTERN, dirty_file)[0] == MATCHED
    assert gate_verdict(grep_binary, BANLIST_PATTERN, tmp_path / "absent")[0] == ERROR


# ==========================================================================================
# PROOF 3 — the negative control: the gate goes red on each of the three files
# ==========================================================================================

#: A different banned token per file, on purpose: a plain word, an underscored key name, and
#: the plus-or-minus character. One injection shape proving one alternative would be weaker.
INJECTIONS: dict[str, str] = {
    "forecast.html": banned_word(BANNED_ALTERNATIVES[2]),
    "forecast.js": banned_word(BANNED_ALTERNATIVES[5]),
    "forecast.css": PLUS_MINUS,
}


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_negative_control_gate_fails_when_a_banned_token_is_injected(
    path: Path, tmp_path: Path, grep_binary: str
) -> None:
    """Copy the file in memory, prove the copy clean, inject one token, prove the gate red.

    The mutation happens on an in-memory string; it reaches disk only as a scratch file under
    `tmp_path`, because the gate under test is a subprocess and must be handed a path. THE
    REAL FILE IN `frontend/` IS NEVER OPENED FOR WRITING, and its digest is compared before
    and after to prove it.

    Proving the unmutated copy clean FIRST is what makes this a control rather than an
    anecdote: it establishes that the injected token is the only thing that changed the
    verdict, so a red here cannot be blamed on the copy or on `tmp_path`.
    """
    original = path.read_text(encoding="utf-8")
    digest_before = hashlib.sha256(path.read_bytes()).hexdigest()

    baseline = tmp_path / f"baseline-{path.name}"
    baseline.write_text(original, encoding="utf-8")
    baseline_verdict, baseline_detail = gate_verdict(grep_binary, BANLIST_PATTERN, baseline)
    assert baseline_verdict == CLEAN, (
        f"the untouched copy of {path.name} already matches ({baseline_detail}); the injection "
        f"below would prove nothing"
    )

    token = INJECTIONS[path.name]
    mutated_text = original + f"\nINJECTED BY THE NEGATIVE CONTROL: {token}\n"
    mutated = tmp_path / f"mutated-{path.name}"
    mutated.write_text(mutated_text, encoding="utf-8")

    verdict, detail = gate_verdict(grep_binary, BANLIST_PATTERN, mutated)

    assert verdict == MATCHED, (
        f"THE GATE CANNOT FAIL: injecting a banned token into a copy of {path.name} still "
        f"produced verdict {verdict!r} ({detail!r}). A guard that cannot fail is not a guard."
    )
    assert token in detail, f"the gate fired, but not on the injected token: {detail!r}"
    assert BANLIST_RE.search(mutated_text) is not None, "the re cross-check missed the injection"

    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest_before, (
        f"{path} changed during the negative control — the real file must never be written"
    )


# ==========================================================================================
# Comment strippers — and why several guards below need them
# ==========================================================================================
#
# Three of the static guards would fire on the shipped files if they scanned raw text, and
# would be CORRECT to, were the hits code. They are not: they are prose in comments that
# documents the very rule being enforced.
#
#   * `frontend/forecast.html` quotes the forbidden state-attribute markup inside an HTML
#     comment explaining that JS must never write it.
#   * `frontend/forecast.js` names the forbidden absolute-value call inside a comment saying
#     never to use it.
#
# Both facts are turned into assertions below (`test_stripper_*_removes_real_content`): the
# raw file matches, the stripped file does not. That is PROOF 4 — these guards are
# demonstrably looking at real content and demonstrably able to see a hit.


def strip_comments(text: str, line_comments: bool) -> str:
    """Blank out `/* ... */` (and optionally `// ...`) comments, leaving string literals alone.

    String-aware, because a URL inside a quoted literal in `forecast.js` would otherwise lose
    the rest of its line to a phantom line comment. Newlines inside a removed block are
    preserved so reported line numbers stay true.

    Regular-expression literals are treated as ordinary operators. That is safe for these
    files — the only two are short and contain no slash pair — and
    `test_stripper_preserves_code_landmarks` fails loudly if that stops being true.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    quote: str | None = None

    while index < length:
        char = text[index]

        if quote is not None:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue

        if char in "'\"`":
            quote = char
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            stop = length if end == -1 else end + 2
            out.append("\n" * text.count("\n", index, stop))
            index = stop
            continue

        if line_comments and char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue

        out.append(char)
        index += 1

    return "".join(out)


def strip_js(text: str) -> str:
    """`forecast.js` with its comments removed."""
    return strip_comments(text, line_comments=True)


def strip_css(text: str) -> str:
    """`forecast.css` with its comments removed. CSS has no `//` form."""
    return strip_comments(text, line_comments=False)


def strip_html(text: str) -> str:
    """`forecast.html` with its `<!-- ... -->` comments removed, line numbering preserved."""
    out: list[str] = []
    index = 0
    while True:
        start = text.find("<!--", index)
        if start == -1:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:start])
        end = text.find("-->", start + 4)
        stop = len(text) if end == -1 else end + 3
        out.append("\n" * text.count("\n", start, stop))
        index = stop


@pytest.fixture(scope="module")
def code(sources: dict[Path, str]) -> dict[str, str]:
    """The three files reduced to code: comments out, string literals kept."""
    return {
        "forecast.html": strip_html(sources[FORECAST_HTML]),
        "forecast.js": strip_js(sources[FORECAST_JS]),
        "forecast.css": strip_css(sources[FORECAST_CSS]),
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a // gone\nb\n", "a \nb\n"),
        ("a /* gone */ b\n", "a  b\n"),
        ("a /* two\nlines */ b\n", "a \n b\n"),
        ("var u = 'http://localhost:8000';\n", "var u = 'http://localhost:8000';\n"),
        ('var u = "x // y";\n', 'var u = "x // y";\n'),
        ("var s = 'it\\'s /* not */ a comment';\n", "var s = 'it\\'s /* not */ a comment';\n"),
        ("x.replace(/^deg/, 'd'); // gone\n", "x.replace(/^deg/, 'd'); \n"),
    ],
)
def test_stripper_js_positive_control(raw: str, expected: str) -> None:
    """The JS stripper removes comments, keeps strings, and does not eat a slash in a literal."""
    assert strip_js(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<p>a</p><!-- gone --><p>b</p>", "<p>a</p><p>b</p>"),
        ("<p>a</p>\n<!-- two\nlines -->\n<p>b</p>", "<p>a</p>\n\n\n<p>b</p>"),
        ("<p>keep</p>", "<p>keep</p>"),
    ],
)
def test_stripper_html_positive_control(raw: str, expected: str) -> None:
    assert strip_html(raw) == expected


def test_stripper_css_positive_control() -> None:
    assert strip_css(".a { color: red } /* gone */\n") == ".a { color: red } \n"
    assert strip_css('.a::after { content: "/* kept */" }') == '.a::after { content: "/* kept */" }'


def test_stripper_preserves_code_landmarks(code: dict[str, str]) -> None:
    """The strippers must not eat code. Landmarks from all three files, asserted present.

    Cheap insurance against the one construct the strippers do not lex — a regular-expression
    literal containing a slash pair. If one is ever added, the tail of its line disappears and
    at least one of these landmarks goes with it.
    """
    js = code["forecast.js"]
    assert "internal-portal:theme" in js
    assert "http://localhost:8000" in js
    assert "modelVar" in js
    assert "setAttribute" in js

    html = code["forecast.html"]
    assert "<title>" in html
    assert 'rel="stylesheet"' in html

    css = code["forecast.css"]
    assert ".strip-boundary" in css
    assert "@media" in css


def test_stripper_html_removes_real_content_from_forecast_html(sources: dict[Path, str]) -> None:
    """PROOF 4a: the raw HTML matches the state-attribute guard; stripped, it does not.

    `forecast.html` documents the "never write the off value into a state attribute" rule by
    quoting the forbidden markup in a comment. So the guard is provably able to see a hit in
    this very file — it just must not count a comment as one.
    """
    raw = sources[FORECAST_HTML]
    stripped = strip_html(raw)

    assert STATE_ATTR_OFF_VALUE.search(raw) is not None, (
        "forecast.html no longer quotes the forbidden markup in a comment; this proof that the "
        "state-attribute guard can see a real hit has gone stale"
    )
    assert STATE_ATTR_OFF_VALUE.search(stripped) is None
    assert len(stripped) < len(raw)


def test_stripper_js_removes_real_content_from_forecast_js(sources: dict[Path, str]) -> None:
    """PROOF 4b: the forbidden call is named in a comment and vanishes when stripped."""
    raw = sources[FORECAST_JS]
    stripped = strip_js(raw)

    assert ABS_CALL_OR_MENTION.search(raw) is not None, (
        "forecast.js no longer mentions the forbidden call in a comment; this proof that the "
        "absolute-value guard can see a real hit has gone stale"
    )
    assert ABS_CALL_OR_MENTION.search(stripped) is None
    assert len(stripped) < len(raw)


# ==========================================================================================
# Static source guards — each with its OWN positive control
# ==========================================================================================
#
# Every pattern below is fed a deliberately bad sample and proven to fire, and where it could
# plausibly over-fire it is fed the real sanctioned shape and proven silent. A pattern that
# matches nothing is worthless; so is one that matches everything.


# ---- the system-theme media query, in any spelling ----------------------------------------

#: `prefers-color-scheme` however it is spelled: run together, split across a concatenation,
#: broken over a line, or reached from JS via `matchMedia`. The gap tolerates any run of up
#: to eight non-alphanumeric characters, which covers quotes, `+`, whitespace and newlines —
#: the ways a split spelling actually appears.
PREFERS_COLOR = re.compile(r"prefers[^A-Za-z0-9]{0,8}color|color[^A-Za-z0-9]{0,8}scheme", re.I)


@pytest.mark.parametrize("name", ["forecast.html", "forecast.js", "forecast.css"])
def test_guard_no_system_theme_media_query(name: str, sources: dict[Path, str]) -> None:
    """The theme is an explicit choice read from storage. The OS setting is never consulted.

    Scanned on RAW text, comments included: there is no legitimate reason for the phrase to
    appear on this page at all, so a comment mentioning it is a sign the rule is being argued
    with rather than followed.
    """
    hit = PREFERS_COLOR.search(sources[FRONTEND / name])
    found = hit.group(0) if hit else ""
    assert hit is None, (
        f"{name} reaches for the OS colour preference ({found!r}); this page's theme comes "
        f"from the explicit toggle and from localStorage, and from nothing else"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "@media (prefers-color-scheme: dark) { }",
        "@media(prefers-color-scheme:dark){}",
        "matchMedia('(prefers-color-scheme: dark)')",
        "var q = 'prefers-' + 'color-scheme';",
        "@media (prefers\n  -color-scheme: dark) { }",
        "html { color-scheme: light dark }",
        "el.style.colorScheme = 'dark';",
    ],
)
def test_guard_system_theme_positive_control(bad: str) -> None:
    """A guard that cannot fail is not a guard — split spellings included."""
    assert PREFERS_COLOR.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "clean",
    ["color: var(--text-1)", "--mark-color: var(--model-gfs)", ".a { background-color: red }"],
)
def test_guard_system_theme_stays_silent_on_ordinary_colour_code(clean: str) -> None:
    """...and a guard that fires on every `color` declaration is noise."""
    assert PREFERS_COLOR.search(clean) is None


# ---- the demo page's stylesheet and the portal's theme script ------------------------------

FORBIDDEN_HTML_ASSETS = ("app.css", "theme.js")


@pytest.mark.parametrize("asset", FORBIDDEN_HTML_ASSETS)
def test_guard_forecast_html_links_neither_app_css_nor_theme_js(
    asset: str, sources: dict[Path, str]
) -> None:
    """Neither the demo page's stylesheet nor the portal's shared theme script is loaded here.

    Scoped to `forecast.html` on purpose: `forecast.js` names `theme.js` in a comment
    explaining that it deliberately reimplements the toggle, and that comment is correct.
    Widening this guard to the JS would fail the page for documenting its own decision.
    """
    assert asset not in sources[FORECAST_HTML], (
        f"forecast.html references {asset}; it is off the permitted-link list. The page "
        f"re-authors the component classes it needs and owns its own theme toggle."
    )


@pytest.mark.parametrize(
    "bad", ['<link rel="stylesheet" href="app.css">', '<script src="theme.js"></script>']
)
def test_guard_forbidden_html_assets_positive_control(bad: str) -> None:
    assert any(asset in bad for asset in FORBIDDEN_HTML_ASSETS), f"guard missed {bad!r}"


# ---- the four stylesheet links, in the one cascade-critical order --------------------------

STYLESHEET_LINK = re.compile(r"""<link\b[^>]*\brel\s*=\s*["']stylesheet["'][^>]*>""", re.I)
HREF = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.I)

EXPECTED_STYLESHEETS = (
    "vendor/clarity-tokens.css",
    "vendor/fonts.css",
    "tokens.css",
    "forecast.css",
)


def stylesheet_hrefs(html: str) -> list[str]:
    """Every `<link rel="stylesheet">` href, in document order.

    `rel="icon"` links are not stylesheets and are excluded by construction, so the favicon
    link sitting above the block does not shift the sequence.
    """
    found: list[str] = []
    for tag in STYLESHEET_LINK.findall(html):
        href = HREF.search(tag)
        if href is not None:
            found.append(href.group(1))
    return found


def test_guard_stylesheet_links_are_the_four_expected_ones_in_order(code: dict[str, str]) -> None:
    """Load order is cascade-critical: each file consumes what the one before it defines.

    Reordering does not error — it silently resolves custom properties to nothing, which is
    the failure mode a reviewer will not spot on a projector. Read from the comment-stripped
    HTML so a commented-out link cannot be counted as loaded.
    """
    assert stylesheet_hrefs(code["forecast.html"]) == list(EXPECTED_STYLESHEETS)


@pytest.mark.parametrize(
    "bad",
    [
        '<link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="vendor/fonts.css">',
        '<link rel="stylesheet" href="forecast.css">',
        "",
        '<link rel="stylesheet" href="vendor/clarity-tokens.css">'
        '<link rel="stylesheet" href="vendor/fonts.css">'
        '<link rel="stylesheet" href="tokens.css">'
        '<link rel="stylesheet" href="app.css">'
        '<link rel="stylesheet" href="forecast.css">',
    ],
)
def test_guard_stylesheet_order_positive_control(bad: str) -> None:
    """Wrong order, missing links, no links at all, and an extra one must all fail."""
    assert stylesheet_hrefs(bad) != list(EXPECTED_STYLESHEETS), f"guard missed {bad!r}"


def test_guard_stylesheet_extractor_ignores_non_stylesheet_links() -> None:
    """The extractor itself must not be the hole: an icon link is not a stylesheet."""
    sample = (
        '<link rel="icon" href="vendor/s2-mark.png">'
        '<link rel="stylesheet" href="tokens.css">'
        "<link rel='stylesheet' href='forecast.css'>"
    )
    assert stylesheet_hrefs(sample) == ["tokens.css", "forecast.css"]


# ---- the theme storage key, byte-identical across all three writers -------------------------

THEME_KEY_IN_FORECAST_JS = re.compile(r"""\bTHEME_KEY\s*=\s*(['"])(.+?)\1""")
THEME_KEY_IN_THEME_JS = re.compile(r"""\bSTORAGE_KEY\s*=\s*(['"])(.+?)\1""")
THEME_KEY_IN_HTML = re.compile(r"""localStorage\s*\.\s*getItem\s*\(\s*(['"])(.+?)\1""")


def sole_capture(pattern: re.Pattern[str], text: str, what: str) -> str:
    """The one value `pattern` captures in `text`, or a failure naming what went missing."""
    found = pattern.findall(text)
    assert len(found) == 1, f"expected exactly one {what}, found {len(found)}: {found}"
    return found[0][1]


def test_guard_theme_storage_key_is_byte_identical_to_the_shared_one(
    sources: dict[Path, str],
) -> None:
    """`forecast.js` writes the same storage key the portal's shared script reads.

    THIS IS THE WHOLE MITIGATION for deliberately not loading `theme.js`: the page owns its
    own toggle, so the only thing keeping it interoperable with the rest of the portal is
    that both sides spell the key identically. Both literals are extracted from source and
    compared — neither is retyped here, so this cannot pass against a stale constant.

    The pre-hydration snippet in `forecast.html` is compared too: it paints before any script
    loads, so a drift there shows as a flash of the wrong theme on the projector.
    """
    forecast_key = sole_capture(
        THEME_KEY_IN_FORECAST_JS, sources[FORECAST_JS], "THEME_KEY in forecast.js"
    )
    shared_key = sole_capture(
        THEME_KEY_IN_THEME_JS, THEME_JS.read_text(encoding="utf-8"), "STORAGE_KEY in theme.js"
    )
    prehydration_key = sole_capture(
        THEME_KEY_IN_HTML, sources[FORECAST_HTML], "localStorage read in forecast.html"
    )

    assert forecast_key == shared_key, (
        f"forecast.js writes {forecast_key!r} but the portal's shared theme script reads "
        f"{shared_key!r}; the page does not load that script, so identical spelling is the "
        f"only thing keeping the toggle interoperable"
    )
    assert prehydration_key == shared_key, (
        f"the pre-hydration snippet in forecast.html reads {prehydration_key!r}, not "
        f"{shared_key!r}; the page would paint the wrong theme before forecast.js runs"
    )
    assert ":" in shared_key and len(shared_key) > 5, f"{shared_key!r} is not a namespaced key"


def test_guard_theme_storage_key_positive_control() -> None:
    """A guard that cannot fail is not a guard: drifted keys must not compare equal."""
    ours = sole_capture(THEME_KEY_IN_FORECAST_JS, "var THEME_KEY = 'portal:theme';", "sample")
    theirs = sole_capture(THEME_KEY_IN_THEME_JS, "var STORAGE_KEY = 'portal:theme ';", "sample")
    assert ours != theirs

    with pytest.raises(AssertionError):
        sole_capture(THEME_KEY_IN_FORECAST_JS, "nothing here", "sample")
    with pytest.raises(AssertionError):
        sole_capture(THEME_KEY_IN_FORECAST_JS, "THEME_KEY = 'a'\nTHEME_KEY = 'b'", "sample")


# ---- the off value is never written into a state attribute --------------------------------

#: `data-stale` / `data-synthetic` set to the off string, in every spelling that reaches the
#: DOM: an HTML attribute, a `setAttribute` pair, and a `dataset` assignment.
#:
#: DELIBERATELY NARROW. `forecast.js` legitimately writes `aria-pressed` with the off string
#: at three places; that is the correct ARIA spelling for an unpressed toggle button and this
#: guard must not touch it. Targeting the bare token would fail the page for being correct,
#: so the pattern requires the state attribute's own name adjacent to the value.
STATE_ATTR_OFF_VALUE = re.compile(
    r"""data-(?:stale|synthetic)\s*["']?\s*[,=:]\s*["']?\s*false"""
    r"""|dataset\s*\.\s*(?:stale|synthetic)\s*=\s*["']?\s*false""",
    re.I,
)


@pytest.mark.parametrize("name", ["forecast.html", "forecast.js", "forecast.css"])
def test_guard_state_attributes_are_never_set_to_the_off_value(
    name: str, code: dict[str, str]
) -> None:
    """An absent attribute is the off state. The off string is never written.

    The CSS selects on the "true" value, which does not match the off string — so writing it
    produces markup that looks like it is doing something and is inert. The architecture of
    this page is "markup always present, visibility keyed on an attribute", and that only
    works if the attribute is removed rather than falsified.
    """
    hit = STATE_ATTR_OFF_VALUE.search(code[name])
    found = hit.group(0) if hit else ""
    assert hit is None, (
        f"{name} writes the off value into a state attribute: {found!r}. Set the attribute "
        f"when the condition holds and leave it ABSENT when it does not."
    )


@pytest.mark.parametrize(
    "bad",
    [
        '<html data-stale="false">',
        "<html data-synthetic='false'>",
        "el.setAttribute('data-stale', 'false');",
        'el.setAttribute("data-synthetic", "false");',
        "root.dataset.stale = 'false';",
        "html[data-synthetic=false] { }",
    ],
)
def test_guard_state_attribute_off_value_positive_control(bad: str) -> None:
    assert STATE_ATTR_OFF_VALUE.search(bad) is not None, f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "b.setAttribute('aria-pressed', b.getAttribute('data-theme-value') === cur "
        "? 'true' : 'false');",
        "b.setAttribute('aria-pressed', 'false');",
        "c.setAttribute('aria-pressed', Number(c.getAttribute('data-idx')) === idx "
        "? 'true' : 'false');",
        "document.documentElement.setAttribute('data-stale', 'true');",
        "document.documentElement.setAttribute('data-synthetic', 'true');",
        "if (!meta.is_synthetic) return;",
    ],
)
def test_guard_state_attribute_guard_stays_silent_on_sanctioned_uses(sanctioned: str) -> None:
    """The three real `aria-pressed` lines and the two real state writes, asserted silent.

    These are copied from the shipped file. An unpressed toggle MUST carry the off string —
    ARIA has no "absent means false" for `aria-pressed` on a toggle button — so a guard that
    fired on the bare token would be demanding an accessibility bug.
    """
    assert STATE_ATTR_OFF_VALUE.search(sanctioned) is None, f"guard over-fired on {sanctioned!r}"


# ---- absolute value: sanctioned as a tie threshold, forbidden on a displayed improvement ----

#: Any mention of the call at all — used by the PROOF 4b stripper test, where the point is
#: that `forecast.js` names it in a comment forbidding it.
ABS_CALL_OR_MENTION = re.compile(r"Math\s*\.\s*abs")

#: The call itself, as code.
ABS_CALL = re.compile(r"Math\s*\.\s*abs\s*\(")

#: HOW THE SANCTIONED USE IS TOLD APART FROM THE FORBIDDEN ONE.
#:
#: A magnitude that is COMPARED AGAINST A THRESHOLD and a magnitude that is SHOWN TO THE
#: VIEWER are the same expression; only what happens next distinguishes them. So the guard
#: looks at what follows the closing parenthesis:
#:
#:   sanctioned — the call is immediately the left operand of a relational operator against a
#:   numeric literal or an ALL-CAPS named constant. That is a tie or tolerance test (the real
#:   shape, as used in `frontend/overview.js`); the magnitude is consumed by the comparison
#:   and never reaches the DOM, so it cannot mislead anyone.
#:
#:   forbidden — anything else. Assigned, returned, concatenated, passed to the formatter,
#:   used as a subscript. In every one of those the magnitude escapes, and a displayed
#:   improvement with its sign stripped tells the viewer a regression is a gain.
#:
#: The alternative — matching on identifier names containing "improvement" — was rejected: it
#: fails the moment the variable is called `d` or `delta`, which is most of the time.
THRESHOLD_TAIL = re.compile(r"^\s*(?:<=?|>=?)\s*(?:[0-9]|\.[0-9]|[A-Z_][A-Z0-9_]*\b)")


def forbidden_abs_uses(js: str) -> list[str]:
    """Every absolute-value call in `js` (comment-stripped) that is not a threshold comparison.

    The closing parenthesis is found by balancing, not by a lazy regex, so a nested call
    inside the argument cannot end the match early.
    """
    found: list[str] = []
    for call in ABS_CALL.finditer(js):
        depth = 1
        index = call.end()
        while index < len(js) and depth:
            if js[index] == "(":
                depth += 1
            elif js[index] == ")":
                depth -= 1
            index += 1
        tail = js[index : index + 40]
        if THRESHOLD_TAIL.match(tail):
            continue
        found.append((js[call.start() : index] + tail).split("\n")[0])
    return found


def test_guard_no_absolute_value_on_a_displayed_improvement(code: dict[str, str]) -> None:
    """A shown improvement keeps its sign. Stripping it turns a regression into a gain.

    Scanned on comment-stripped source: `forecast.js` documents this very rule in a comment
    that names the call, and `test_stripper_js_removes_real_content_from_forecast_js` proves
    the raw file matches while the stripped file does not — so this guard is demonstrably
    looking at real content and demonstrably able to see a hit.
    """
    hits = forbidden_abs_uses(code["forecast.js"])
    assert hits == [], (
        f"forecast.js takes the magnitude of a value that is not a threshold comparison: "
        f"{hits}. The shared formatter substitutes a real minus for the ASCII hyphen; it does "
        f"not discard the sign, and neither may a call site."
    )


@pytest.mark.parametrize(
    "bad",
    [
        "var shown = Math.abs(improvement);",
        "el.textContent = fmt(Math.abs(d.improvement_f), 2);",
        "return Math.abs(delta);",
        "cells[Math.abs(i)] = v;",
        "var m = Math . abs ( a - b ) ;",
        "var s = 'gain ' + Math.abs(x) + ' F';",
        "var nested = Math.abs(Math.max(a, b)) + 1;",
    ],
)
def test_guard_absolute_value_positive_control(bad: str) -> None:
    """A guard that cannot fail is not a guard — every escaping magnitude has to be caught."""
    assert forbidden_abs_uses(bad), f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "if (typeof served === 'number' && Math.abs(reproduced - served) < 0.005) {",
        "var tie = Math.abs(a - b) <= 0.05;",
        "if (Math.abs(a - b) < TIE_EPSILON) { return 0; }",
        "if (Math.abs(x) > 1e-9) { }",
        "if (Math.abs(a - b) >= .5) { }",
    ],
)
def test_guard_absolute_value_stays_silent_on_a_tie_threshold(sanctioned: str) -> None:
    """The sanctioned shape, including the real one from `frontend/overview.js`, stays quiet."""
    assert forbidden_abs_uses(sanctioned) == [], f"guard over-fired on {sanctioned!r}"


# ---- model colour tokens are consumed in forecast.css, never declared there ----------------

#: The exact invocation the ticket specifies, run through the same exit-status-aware runner as
#: the gate, so a grep error here cannot masquerade as zero hits either.
MODEL_TOKEN_DECLARATION_PATTERN = r"^\s*--model-"


def test_guard_forecast_css_declares_no_model_colour_token(grep_binary: str) -> None:
    """`forecast.css` consumes the model colour tokens; the map itself lives in `tokens.css`.

    Re-declaring one here would fork the map: the token doc's dark-theme values would stop
    applying to this page and a model would change colour when the toggle is used.
    """
    hits = grep_lines(grep_binary, MODEL_TOKEN_DECLARATION_PATTERN, FORECAST_CSS)
    assert hits == [], (
        f"forecast.css declares a model colour token: {hits}. The map belongs to tokens.css; "
        f"this file may only reference it."
    )


def test_guard_model_colour_token_positive_control(tmp_path: Path, grep_binary: str) -> None:
    """The same grep, over samples that DO declare one, must find them.

    Without this the assertion above is indistinguishable from a grep that never ran. The real
    `tokens.css` is used as a second, real-content sample, because it genuinely carries the
    declarations this pattern is looking for.
    """
    sample = tmp_path / "sample.css"
    sample.write_text(":root {\n  --model-gfs: var(--orange-500);\n}\n", encoding="utf-8")
    assert grep_lines(grep_binary, MODEL_TOKEN_DECLARATION_PATTERN, sample), "guard missed a sample"

    tokens = FRONTEND / "tokens.css"
    if tokens.is_file():
        assert grep_lines(grep_binary, MODEL_TOKEN_DECLARATION_PATTERN, tokens), (
            "tokens.css no longer declares the model colour map; either the map moved or this "
            "pattern has gone stale against real content"
        )


# ---- forecast.css carries no theme fork ---------------------------------------------------

CSS_THEME_ATTRIBUTE_BLOCK = re.compile(r"\[\s*data-theme")


def test_guard_forecast_css_has_no_theme_attribute_block(code: dict[str, str]) -> None:
    """Theme forking belongs in the token doc. This file styles layout, not palettes.

    A theme-attribute block here would cascade after `tokens.css` and silently win, which is
    how a page ends up with one component that ignores the toggle.
    """
    hit = CSS_THEME_ATTRIBUTE_BLOCK.search(code["forecast.css"])
    found = hit.group(0) if hit else ""
    assert hit is None, f"forecast.css forks on the theme attribute: {found!r}"


@pytest.mark.parametrize(
    "bad",
    [
        'html[data-theme="dark"] .card { background: #111 }',
        ":root[ data-theme='dark'] { --x: 1 }",
        "[data-theme=dark] .strip-cell { }",
    ],
)
def test_guard_css_theme_block_positive_control(bad: str) -> None:
    assert CSS_THEME_ATTRIBUTE_BLOCK.search(bad) is not None, f"guard missed {bad!r}"


def test_guard_css_theme_block_stays_silent_on_the_js_toggle_write() -> None:
    """`forecast.js` sets the attribute; that is the toggle working, not a CSS fork."""
    assert CSS_THEME_ATTRIBUTE_BLOCK.search("root.setAttribute('data-theme', v);") is None


# ---- no payload literal is baked into forecast.js ------------------------------------------

MODEL_NAMES = ("gfs", "hrrr", "nam", "nbm")
SITE_NAME = "Omaha Eppley Airfield"

#: Quoted string literals, either quote style, with escapes tolerated.
JS_STRING_LITERAL = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""")

#: A bare `16` that is not part of a longer number or identifier — the full step-grid cell
#: count, which must always be derived from the payload's own step list.
BARE_SIXTEEN = re.compile(r"(?<![\w.])16(?![\w.])")


def baked_payload_literals(js: str) -> list[str]:
    """Model names, the site name and a bare cell count found as literals in `js` (stripped).

    Model names are matched as WHOLE string literals rather than as substrings, so the
    `var(--model-` reference prefix that the colour helper concatenates a name onto is
    correctly not a hit. That helper is the sanctioned way a model name reaches CSS.
    """
    found: list[str] = []
    for quote, body in JS_STRING_LITERAL.findall(js):
        if body.strip().lower() in MODEL_NAMES:
            found.append(f"{quote}{body}{quote}")
    if SITE_NAME in js:
        found.append(SITE_NAME)
    for name in MODEL_NAMES:
        if re.search(rf"\b{name.upper()}\b", js):
            found.append(name.upper())
    found.extend(match.group(0) for match in BARE_SIXTEEN.finditer(js))
    return found


def test_guard_forecast_js_bakes_in_no_payload_literal(code: dict[str, str]) -> None:
    """No model name, no site name, no cell count. Every one of them comes from the payload.

    A refit that drops a model, or a move to a second site, must not leave a stale literal
    behind in the page — the page would then state something the payload does not.
    """
    hits = baked_payload_literals(code["forecast.js"])
    assert hits == [], (
        f"forecast.js bakes in payload literals {hits}. Model names arrive in the payload's "
        f"model list, the site name in its metadata, and the cell count is the length of the "
        f"step list."
    )


@pytest.mark.parametrize(
    "bad",
    [
        "var models = ['gfs', 'hrrr', 'nam', 'nbm'];",
        'var m = "NBM";',
        "var site = 'Omaha Eppley Airfield';",
        "var CELLS = 16;",
        "for (var i = 0; i < 16; i++) { }",
        "var label = 'HRRR';",
    ],
)
def test_guard_payload_literal_positive_control(bad: str) -> None:
    assert baked_payload_literals(bad), f"guard missed {bad!r}"


@pytest.mark.parametrize(
    "sanctioned",
    [
        "return 'var(--model-' + String(model).toLowerCase() + ')';",
        "var names = meta.models_included || Object.keys(members);",
        "var FULL_HORIZON_H = 48;",
        "var CELL_MIN_PX = 108;",
        "var slots = payload.steps.length;",
        "var x = 0.165;",
        "var y = a16;",
    ],
)
def test_guard_payload_literal_stays_silent_on_derived_values(sanctioned: str) -> None:
    """The colour helper, the payload reads, and the geometry constants are all sanctioned.

    `0.165` and `a16` are here because a naive word-boundary pattern matches inside both, and
    a guard that fails the page for a decimal is a guard that gets deleted.
    """
    assert baked_payload_literals(sanctioned) == [], f"guard over-fired on {sanctioned!r}"


# ---- both boundary forms are present in forecast.css ---------------------------------------

REQUIRED_CSS_BOUNDARY_FORMS = (".strip-boundary", "data-boundary-start")


def missing_forms(text: str, required: tuple[str, ...]) -> list[str]:
    """Which of `required` are absent from `text`."""
    return [form for form in required if form not in text]


def test_guard_forecast_css_carries_both_boundary_forms(code: dict[str, str]) -> None:
    """The day divider is drawn two ways and both must survive.

    `.strip-boundary` is the standalone rule; `data-boundary-start` is the per-cell attribute
    hook. Losing either leaves the strip running across a midnight with no visible break,
    which reads as one continuous day.
    """
    absent = missing_forms(code["forecast.css"], REQUIRED_CSS_BOUNDARY_FORMS)
    assert absent == [], f"forecast.css has lost the boundary form(s) {absent}"


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (".strip-boundary { }", ["data-boundary-start"]),
        ('.strip-cell[data-boundary-start="true"] { }', [".strip-boundary"]),
        ("", list(REQUIRED_CSS_BOUNDARY_FORMS)),
        ('.strip-boundary { } .strip-band[data-boundary-start="true"] { }', []),
    ],
)
def test_guard_boundary_forms_positive_control(sample: str, expected: list[str]) -> None:
    """The presence check must report exactly what is missing, including "everything"."""
    assert missing_forms(sample, REQUIRED_CSS_BOUNDARY_FORMS) == expected


# ---- the shared formatter's minus substitution ---------------------------------------------

#: U+2212 MINUS SIGN, written as an escape so this line is unambiguous next to an ASCII hyphen.
TRUE_MINUS = "−"

#: `.replace('-', ...)` in either quote style — the substitution itself.
MINUS_SUBSTITUTION = re.compile(r"""\.replace\s*\(\s*(['"])-\1""")


def test_guard_forecast_js_substitutes_a_real_minus(code: dict[str, str]) -> None:
    """Negatives are rendered with U+2212, substituted in one place and at no call site.

    `toFixed` and `Intl` both emit an ASCII hyphen in en-US. The hyphen is narrower than a
    digit even in a tabular face, so a negative column stops lining up — and the sign is the
    one character a presenter cannot afford to lose when pasting a number into a chat window.
    Both halves are asserted: the character must be present, and so must the substitution
    that puts it there.
    """
    js = code["forecast.js"]
    assert TRUE_MINUS != "-", "the escape resolved to an ASCII hyphen"
    assert TRUE_MINUS in js, (
        "forecast.js no longer carries U+2212; negatives will render with an ASCII hyphen and "
        "break the column they sit in"
    )
    assert MINUS_SUBSTITUTION.search(js) is not None, (
        "the shared formatter's minus substitution is gone from forecast.js"
    )


@pytest.mark.parametrize(
    ("sample", "has_char", "has_substitution"),
    [
        ("var MINUS = '−';\nx.replace('-', MINUS)", True, True),
        ("var MINUS = '-';\nx.replace('-', MINUS)", False, True),
        ("var MINUS = '−';\nx.toFixed(2)", True, False),
        ("x.toFixed(2)", False, False),
        ('x.replace("-", M)', False, True),
    ],
)
def test_guard_minus_substitution_positive_control(
    sample: str, has_char: bool, has_substitution: bool
) -> None:
    """Both halves fail independently — an ASCII hyphen substituted for itself is a no-op."""
    assert (TRUE_MINUS in sample) is has_char, f"character check wrong on {sample!r}"
    assert (MINUS_SUBSTITUTION.search(sample) is not None) is has_substitution


# ==========================================================================================
# The regression diff gate — deliberately NOT written the way that would be vacuous
# ==========================================================================================
#
# THE TRAP, NAMED SO IT IS NOT WALKED INTO AGAIN.
#
# F5's work is deliberately not committed. So the obvious gate — `git diff --stat <base> HEAD
# -- <paths>` asserting "the diff names only the three new files" — compares two identical
# commits, returns empty, and passes. It would pass just as happily IF THE THREE FILES DID
# NOT EXIST AT ALL, because an empty diff satisfies "names nothing it should not". That is the
# vacuous form, and it is what a reviewer skimming a green run would not catch.
#
# It is written as a PAIR instead, and the pair is what makes it real:
#
#   (1) `git diff --stat <base> -- <paths>` with NO `HEAD`, so the comparison reaches the
#       WORKING TREE. Empty here means no tracked file on the demo path was modified — a
#       claim about the files as they exist on disk right now, not about two commits.
#
#   (2) `git status --porcelain frontend/` must show the three new files as untracked (`??`)
#       and no `M` on anything. THIS IS THE HALF THAT CANNOT PASS WHEN THE FILES ARE MISSING,
#       because it asserts their presence positively rather than asserting the absence of a
#       change.
#
# Scope is exactly the paths below. `data/` is deliberately excluded: two forecast payloads
# under it are pre-existing and gitignored, and widening the gate to cover them would fail
# this ticket for reasons that are not this ticket's.

#: The commit the demo path must still be byte-identical to.
DEMO_PATH_BASE = "00e3441"

#: The commit `backend/main.py` is measured against. This one IS a commit-to-commit check and
#: is correct as such: the two added lines are already committed.
MAIN_PY_BASE = "740dfb0"

#: `backend/main.py` may carry exactly one import and one `include_router` call. Nothing else.
EXPECTED_MAIN_NUMSTAT = (2, 0)

#: Everything on the demo path that F5 may not have modified.
DEMO_PATHS = ("frontend/", "backend/", "score/", "docs/", "run.sh", "demo.sh")

#: The three files F5 adds, and the only entries `git status` may report under `frontend/`.
EXPECTED_UNTRACKED = (
    "frontend/forecast.css",
    "frontend/forecast.html",
    "frontend/forecast.js",
)

RESULTS_JSON = REPO / "data" / "results.json"
EXPECTED_RESULTS_SHA256 = "3b113a995b084da41e593af9c70214e8efb76170056bc42e0b84413b1644aa8c"


def git(*args: str) -> subprocess.CompletedProcess:
    """Run a read-only `git` command in this repository.

    F4's shape, carried here rather than imported: `tests/test_live_guards.py` is off limits
    and `tests/test_forecast_api_guards.py` belongs to another ticket. Every call site below
    is a read; nothing in this module mutates git state.
    """
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)


@pytest.fixture()
def git_repo() -> None:
    """Skip rather than fail when `git` is unavailable or this is not a checkout."""
    if shutil.which("git") is None:
        pytest.skip("git is not available on PATH")
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip(f"{REPO} is not a git working tree")


def resolved(ref: str) -> str:
    """`ref` as a full sha — or a clean skip when the checkout does not carry it."""
    result = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip(f"{ref} is not present in this checkout")
    return result.stdout.strip()


def parse_numstat(output: str) -> dict[str, tuple[int, int]]:
    """`git diff --numstat` output as `{path: (added, deleted)}`. Binary files are skipped."""
    parsed: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 3 or "-" in (fields[0], fields[1]):
            continue
        parsed[fields[2]] = (int(fields[0]), int(fields[1]))
    return parsed


def test_numstat_parser_positive_control() -> None:
    """The parser is what the numstat assertion trusts; prove it reads what it claims."""
    assert parse_numstat("2\t0\tbackend/main.py\n") == {"backend/main.py": (2, 0)}
    assert parse_numstat("2\t0\tbackend/main.py\n1\t3\tfrontend/app.js\n") == {
        "backend/main.py": (2, 0),
        "frontend/app.js": (1, 3),
    }
    assert parse_numstat("-\t-\tdata/blob.parquet\n") == {}
    assert parse_numstat("") == {}


@pytest.mark.usefixtures("git_repo")
def test_diff_gate_no_tracked_demo_path_file_was_modified() -> None:
    """Half one of the pair: nothing pre-existing on the demo path was modified or deleted.

    Commit-to-commit on purpose, matching `test_diff_gate_backend_main_gained_exactly_two_lines`
    below — not base-vs-working-tree. Base-vs-working-tree was this test's first form, and it
    broke the moment F5 was actually committed: the three new files are legitimate content of
    the diff against `base` once they're part of history, so an empty-diff assertion over all of
    `DEMO_PATHS` would fail on the very thing this ticket is supposed to do, not on a regression.
    What must stay empty forever is the set of entries whose status isn't `A` (added) — that is
    the "someone touched something that already shipped" signature this gate exists to catch,
    and it reads the same way whether run today or a year from now.
    """
    base = resolved(DEMO_PATH_BASE)

    result = git("diff", "--name-status", base, "HEAD", "--", *DEMO_PATHS)
    assert result.returncode == 0, result.stderr

    non_additions = [
        line for line in result.stdout.splitlines() if line.strip() and not line.startswith("A\t")
    ]
    assert non_additions == [], (
        f"F5 modified or deleted tracked file(s) on the demo path since {base[:7]}:\n"
        + "\n".join(non_additions)
        + "\nThis ticket adds three new files and changes nothing that already ships."
    )


@pytest.mark.usefixtures("git_repo")
def test_diff_gate_the_three_new_files_are_present_and_untracked() -> None:
    """Half two: the three files exist as pure additions since `base`, and nothing else does.

    THIS IS THE HALF THAT CANNOT PASS VACUOUSLY. Half one above is satisfied by a repository in
    which the three files were never written; this one is not, because it asserts their
    presence positively, by name, with the `A` status `git diff --name-status` assigns to a path
    that exists now and did not exist at `base`.

    Commit-to-commit, matching the fix to half one — the name is kept even though `git status`
    (which only reports uncommitted/staged entries) stopped being able to see these files the
    moment they were committed. `git diff --name-status base HEAD` sees a committed pure
    addition exactly as clearly as `git status` once saw an untracked one; it just keeps seeing
    it after commit, which is the property this module needs for the life of the branch.
    """
    result = git("diff", "--name-status", resolved(DEMO_PATH_BASE), "HEAD", "--", "frontend/")
    assert result.returncode == 0, result.stderr

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    additions = sorted(line.split("\t", 1)[1].strip() for line in lines if line.startswith("A\t"))
    others = sorted(
        line.split("\t", 1)[1].strip() for line in lines if not line.startswith("A\t")
    )

    assert others == [], (
        f"F5 modified or deleted existing file(s) under frontend/: {others}. The demo path is "
        f"frozen; this ticket only adds forecast.html, forecast.js and forecast.css."
    )
    assert additions == sorted(EXPECTED_UNTRACKED), (
        f"expected exactly {sorted(EXPECTED_UNTRACKED)} as pure additions under frontend/ since "
        f"{DEMO_PATH_BASE}, got {additions}. Missing entries mean the page was never written; "
        f"extra ones mean this ticket grew."
    )


@pytest.mark.usefixtures("git_repo")
def test_diff_gate_backend_main_gained_exactly_two_lines() -> None:
    """`backend/main.py`: exactly two added, none deleted, since its base commit.

    Commit-to-commit on purpose — those two lines are already committed. One import and one
    `include_router` call is the entire permitted change; the app title is the demo's identity
    gate, and a third moved line would mean something else went with it.
    """
    base = resolved(MAIN_PY_BASE)

    result = git("diff", "--numstat", base, "HEAD", "--", "backend/main.py")
    assert result.returncode == 0, result.stderr

    numstat = parse_numstat(result.stdout)
    assert numstat.get("backend/main.py") == EXPECTED_MAIN_NUMSTAT, (
        f"backend/main.py must gain exactly {EXPECTED_MAIN_NUMSTAT[0]} line(s) and lose "
        f"{EXPECTED_MAIN_NUMSTAT[1]} since {base[:7]}; got {numstat.get('backend/main.py')} "
        f"from:\n{result.stdout}"
    )


def test_diff_gate_results_json_is_byte_identical() -> None:
    """`data/results.json` is unchanged, asserted on its SHA-256.

    The one file under `data/` this module reads, and it is read only — hashed from bytes,
    never opened for writing, never copied, never moved. The two forecast payloads alongside
    it are gitignored and out of scope; a gate covering them would fail for reasons that have
    nothing to do with this ticket.
    """
    if not RESULTS_JSON.is_file():
        pytest.skip(f"{RESULTS_JSON} is not present in this checkout")

    digest = hashlib.sha256(RESULTS_JSON.read_bytes()).hexdigest()

    assert digest == EXPECTED_RESULTS_SHA256, (
        f"data/results.json changed: {digest} != {EXPECTED_RESULTS_SHA256}. The scored "
        f"document is the demo's payload; F5 does not regenerate it."
    )


def test_diff_gate_scope_excludes_the_data_directory() -> None:
    """The gate's scope, pinned. Adding `data/` here would break it for someone else's work."""
    assert all(not path.startswith("data") for path in DEMO_PATHS)
    assert set(DEMO_PATHS) == {"frontend/", "backend/", "score/", "docs/", "run.sh", "demo.sh"}
