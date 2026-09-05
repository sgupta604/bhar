"""The NON-NEGOTIABLE guards for the live forecast path (F2, Stream 5 — T24-T30).

Every test here is offline. The only inputs are small synthetic `.idx` strings built in this
file, the verbatim NOAA `.idx` text captured under `tests/fixtures/idx/`, monkeypatched
in-memory `xarray` datasets, and `git` run against this checkout. **No test in this module
opens a socket, and none names an archive URL.**

Each guard was bought with a real bug, and each one fails loudly rather than quietly:

* T24 the needle's leading colon (`:TMP:` not `TMP:`) — without it, `APTMP:2 m above ground`
  matches and apparent temperature is silently returned as the forecast. The trap is live in
  **GFS as well as NBM**.
* T25 ensemble spread lines repeat the same variable and level and are not the forecast value.
* T26 NBM's `TMP:2 m above ground` message number **moves with lead time** (135 at f003 →
  173 at f048 in the live observation), so no message index may ever be hardcoded.
* T27/T28 the decode-side half of the same trap: the decoded variable must be 2 m temperature.
* T29 a source scan over `forecast/*.py` for the mistakes that would reintroduce all of the
  above, plus bare `assert` (stripped by `python -O`) and naive UTC.
* T30 a diff gate proving F2 changed nothing under `fetch/`.

Note on T27/T28 (Stream 1 finding, corrected on `develop` at 37ca272): eccodes reports
`GRIB_shortName == "2t"` for valid 2 m temperature data. The guard in `fetch/grib.py` is
therefore on the **data-variable name** being `t2m` and on `GRIB_cfVarName == "t2m"`, with
`aptmp` rejected explicitly. Asserting `GRIB_shortName == "t2m"` fails on good data; T29 exists
to make sure nobody puts that form back.
"""

from __future__ import annotations

import ast
import io
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from fetch import grib
from fetch.idx import ENS_SPREAD, NEEDLE, parse_idx, select_tmp_2m

REPO = Path(__file__).resolve().parent.parent
FORECAST_PKG = REPO / "forecast"

#: The unanchored form of the needle. Never used by `fetch/`; kept here only so a test can
#: prove the leading colon in `NEEDLE` does real work rather than being incidental.
UNANCHORED = "TMP:2 m above ground"

#: The three captured NBM `.idx` files, one per lead time. Their `TMP:2 m above ground`
#: message numbers must all differ — see T26.
NBM_FIXTURES = (
    "nbm_20260805_12z_f006.idx",
    "nbm_20260805_12z_f012.idx",
    "nbm_20260805_12z_f024.idx",
)


def synthetic_idx(*lines: str) -> str:
    """Build a well-formed `.idx` body from literal lines (trailing newline included).

    Field layout, from `fetch/idx.py`:
    ``{msg}:{start}:d={YYYYMMDDHH}:{VAR}:{level}:{fcst}:{optional extra}``.
    """
    return "".join(line + "\n" for line in lines)


def read_idx(FIXTURES: Path, name: str) -> str:
    """Read one captured `.idx` file verbatim. Path comes from the session fixture, never cwd."""
    path = FIXTURES / "idx" / name
    assert path.exists(), (
        f"missing captured fixture {path}; SPEC §13 forbids live-network tests, so this test "
        f"cannot fall back to fetching it"
    )
    return path.read_text()


# ------------------------------------------------------------------------------------------
# T24 — the anchored needle rejects APTMP.  NON-NEGOTIABLE.
# ------------------------------------------------------------------------------------------


def test_t24_anchored_needle_selects_tmp_and_rejects_aptmp() -> None:
    """Spike F9: `TMP:2 m above ground` also matches `APTMP:2 m above ground`.

    APTMP is *apparent* temperature — a heat index, a different variable, and message number
    one in NBM. The trap is live in **GFS as well as NBM**: both archives carry an
    `APTMP:2 m above ground` record in the same file as the real `TMP` record. Selecting it
    would produce plausible-looking degrees Fahrenheit that are not the forecast temperature.
    """
    body = synthetic_idx(
        "1:0:d=2026080512:APTMP:2 m above ground:6 hour fcst:",
        "2:2289048:d=2026080512:CDCB:reserved:6 hour fcst:",
        "187:153756600:d=2026080512:TMP:2 m above ground:6 hour fcst:",
        "188:155939231:d=2026080512:DPT:2 m above ground:6 hour fcst:",
    )

    chosen = select_tmp_2m(parse_idx(body))

    assert chosen["msg"] == "187", f"selected the wrong record: {chosen['raw']!r}"
    assert chosen["var"] == "TMP", f"selected {chosen['var']!r}, not TMP: {chosen['raw']!r}"
    assert "APTMP" not in chosen["raw"], (
        f"spike F9: apparent temperature was selected as the forecast: {chosen['raw']!r}"
    )


def test_t24_the_leading_colon_is_load_bearing() -> None:
    """The unanchored needle matches BOTH lines; the anchored one matches exactly one.

    This is what proves the leading colon in `fetch.idx.NEEDLE` is doing real work rather
    than being incidental punctuation that a future edit could tidy away.
    """
    body = synthetic_idx(
        "1:0:d=2026080512:APTMP:2 m above ground:6 hour fcst:",
        "187:153756600:d=2026080512:TMP:2 m above ground:6 hour fcst:",
    )
    records = parse_idx(body)

    unanchored = [r["raw"] for r in records if UNANCHORED in r["raw"]]
    anchored = [r["raw"] for r in records if NEEDLE in r["raw"]]

    assert len(unanchored) == 2, (
        f"the unanchored substring {UNANCHORED!r} must match both the APTMP and the TMP line, "
        f"otherwise this test is not exercising the trap; matched {unanchored}"
    )
    assert len(anchored) == 1, (
        f"the anchored needle {NEEDLE!r} must match only the TMP line; matched {anchored}"
    )
    assert NEEDLE.startswith(":"), (
        "spike F9: the leading colon in NEEDLE is the entire difference between a temperature "
        "and a heat index — never strip it"
    )
    assert "APTMP" not in anchored[0]


def test_t24_the_trap_is_present_in_the_captured_gfs_and_nbm_idx(FIXTURES: Path) -> None:
    """Not a hypothetical: both captured archives really do carry an APTMP 2 m record."""
    for name in ("gfs_20260805_12z_f006.idx", "nbm_20260805_12z_f006.idx"):
        body = read_idx(FIXTURES, name)
        aptmp = [line for line in body.splitlines() if ":APTMP:2 m above ground:" in line]
        assert aptmp, f"{name} no longer carries an APTMP 2 m record — this test is now blind"

        chosen = select_tmp_2m(parse_idx(body))
        assert chosen["var"] == "TMP", f"{name}: selected {chosen['var']!r}"
        assert "APTMP" not in chosen["raw"], f"{name}: selected apparent temperature"


# ------------------------------------------------------------------------------------------
# T25 — ensemble spread lines are rejected
# ------------------------------------------------------------------------------------------


def test_t25_ens_std_dev_line_is_rejected() -> None:
    """NBM repeats `TMP:2 m above ground` as an `ens std dev` record. It is not the forecast."""
    body = synthetic_idx(
        "187:153756600:d=2026080512:TMP:2 m above ground:6 hour fcst:",
        f"188:155939231:d=2026080512:TMP:2 m above ground:6 hour fcst:{ENS_SPREAD}",
    )

    chosen = select_tmp_2m(parse_idx(body))

    assert chosen["msg"] == "187"
    assert ENS_SPREAD not in chosen["raw"], (
        f"the ensemble-spread record was selected as the forecast value: {chosen['raw']!r}"
    )


def test_t25_an_idx_whose_only_2m_temperature_is_ens_spread_raises() -> None:
    """Zero surviving hits is a hard failure, never a 'pick the first' situation."""
    body = synthetic_idx(
        "1:0:d=2026080512:APTMP:2 m above ground:6 hour fcst:",
        f"188:155939231:d=2026080512:TMP:2 m above ground:6 hour fcst:{ENS_SPREAD}",
    )

    with pytest.raises(ValueError, match="exactly one"):
        select_tmp_2m(parse_idx(body))


# ------------------------------------------------------------------------------------------
# T26 — the message index MOVES.  NON-NEGOTIABLE.
# ------------------------------------------------------------------------------------------


def test_t26_nbm_message_index_moves_with_lead_time(FIXTURES: Path) -> None:
    """The three NBM lead times yield three DIFFERENT message numbers.

    Mirrors the live observation that NBM's `TMP:2 m above ground` index moved 135 (f003) →
    173 (f048). Any code that pins a message number is decoding a different variable at some
    lead times — which is why `fetch/idx.py` parses the `.idx` on every call.
    """
    selected = {}
    for name in NBM_FIXTURES:
        chosen = select_tmp_2m(parse_idx(read_idx(FIXTURES, name)))
        selected[name] = chosen["msg"]

    values = list(selected.values())
    assert len(set(values)) == len(values), (
        f"NBM's 2 m temperature message number must differ across lead times, but two or more "
        f"lead times share one: {selected} — if these ever coincide, this test has gone blind "
        f"and no longer proves that hardcoding an index is unsafe"
    )
    for name, msg in selected.items():
        assert isinstance(msg, str), (
            f"{name}: message numbers stay `str` — NAM emits sub-messages like '284.1' and "
            f"int() on those raises (fetch/idx.py line 75); got {type(msg).__name__}"
        )


# ------------------------------------------------------------------------------------------
# T27 / T28 — decode_point's variable guards
#
# `decode_point` opens a real GRIB file through cfgrib, so the offending condition is built by
# monkeypatching `xarray.open_dataset` (the name `fetch.grib` calls) to hand back a small
# in-memory Dataset. No GRIB bytes are read, so neither test needs the `integration` marker.
# ------------------------------------------------------------------------------------------


def _patch_open_dataset(monkeypatch: pytest.MonkeyPatch, dataset: xr.Dataset) -> None:
    """Make `fetch.grib`'s `xr.open_dataset(...)` return `dataset` without touching disk."""

    def fake_open_dataset(*args, **kwargs) -> xr.Dataset:
        return dataset

    monkeypatch.setattr(grib.xr, "open_dataset", fake_open_dataset)


def test_t27_decode_point_raises_when_the_variable_is_aptmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spike F9, decode side: apparent temperature must never be returned as the forecast."""
    dataset = xr.Dataset(
        {"aptmp": (("y", "x"), np.full((2, 2), 300.0))},
        coords={
            "latitude": (("y", "x"), np.array([[41.0, 41.0], [41.5, 41.5]])),
            "longitude": (("y", "x"), np.array([[-96.0, -95.5], [-96.0, -95.5]])),
        },
    )
    _patch_open_dataset(monkeypatch, dataset)

    with pytest.raises(AssertionError) as excinfo:
        grib.decode_point(tmp_path / "nbm_f006.grib2")

    assert "aptmp" in str(excinfo.value), (
        f"the raise must name the offending variable so a future reader can debug it; "
        f"got {excinfo.value!s}"
    )


def test_t28_decode_point_raises_when_cf_var_name_is_not_t2m(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`GRIB_cfVarName` is the attribute that must equal `t2m`.

    Deliberately NOT `GRIB_shortName`: eccodes reports `"2t"` there for valid 2 m temperature
    data (Stream 1 finding, corrected on `develop` at 37ca272). T29 keeps the wrong form out.
    """
    dataset = xr.Dataset(
        {"t2m": (("y", "x"), np.full((2, 2), 300.0), {"GRIB_cfVarName": "unknown"})},
        coords={
            "latitude": (("y", "x"), np.array([[41.0, 41.0], [41.5, 41.5]])),
            "longitude": (("y", "x"), np.array([[-96.0, -95.5], [-96.0, -95.5]])),
        },
    )
    _patch_open_dataset(monkeypatch, dataset)

    with pytest.raises(AssertionError) as excinfo:
        grib.decode_point(tmp_path / "nbm_f006.grib2")

    message = str(excinfo.value)
    assert "unknown" in message, (
        f"the raise must name the offending GRIB_cfVarName value; got {message}"
    )
    assert "GRIB_cfVarName" in message, f"the raise must name the attribute checked; got {message}"


def test_t28_a_valid_cf_var_name_passes_the_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Control: the same fake dataset with `GRIB_cfVarName == "t2m"` decodes.

    Without this, T27/T28 would still pass if the guard rejected *everything* — including
    good data. `GRIB_shortName` is left at its real-world value `"2t"` on purpose.
    """
    dataset = xr.Dataset(
        {
            "t2m": (
                ("y", "x"),
                np.full((2, 2), 300.0),
                {"GRIB_cfVarName": "t2m", "GRIB_shortName": "2t"},
            )
        },
        coords={
            "latitude": (("y", "x"), np.array([[41.0, 41.0], [41.5, 41.5]])),
            "longitude": (("y", "x"), np.array([[-96.0, -95.5], [-96.0, -95.5]])),
        },
    )
    _patch_open_dataset(monkeypatch, dataset)

    decoded = grib.decode_point(tmp_path / "nbm_f006.grib2", lat=41.3, lon=-95.9)

    assert decoded["temp_f"] == pytest.approx(80.33, abs=0.01)


# ------------------------------------------------------------------------------------------
# T29 — source scan over forecast/*.py
# ------------------------------------------------------------------------------------------


def forecast_sources() -> list[Path]:
    """Every `*.py` in the `forecast` package, discovered on disk rather than listed here."""
    return sorted(FORECAST_PKG.glob("*.py"))


def normalized_code(text: str) -> str:
    """Return `text` as executable code only: comments and docstrings dropped, spacing collapsed.

    Tokenizing (rather than splitting on `#`) means a `#` inside a string literal cannot
    truncate a line, and dropping only *statement-initial* string tokens removes docstrings
    while preserving every string literal that real code compares against — which is exactly
    what the `GRIB_shortName == "t2m"` check needs to see.
    """
    pieces: list[str] = []
    at_statement_start = True

    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.ENDMARKER):
            continue
        if token.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            at_statement_start = True
            continue
        if token.type == tokenize.STRING and at_statement_start:
            at_statement_start = False  # a docstring / bare string statement
            continue
        pieces.append(token.string)
        at_statement_start = False

    return " ".join(pieces)


_GAP = r".{0,80}?"

#: `GRIB_shortName` compared to `"t2m"`, in either direction and either quoting style.
#: Normalized source puts a single space between tokens, so spacing style cannot evade this.
SHORTNAME_COMPARED_TO_T2M = (
    re.compile(r"GRIB_shortName" + _GAP + r"(?:==|!=)" + _GAP + r"""['"]t2m['"]"""),
    re.compile(r"""['"]t2m['"]""" + _GAP + r"(?:==|!=)" + _GAP + r"GRIB_shortName"),
)

#: A bare integer bound to a name that means "GRIB message number". Deliberately narrow: it
#: matches assignment and keyword-argument forms of these names only, never arbitrary ints.
MESSAGE_NUMBER_LITERAL = re.compile(
    r"\b(?:msg|msgs|message|msg_no|msg_num|msg_number|msg_index|message_no|message_num|"
    r"message_number|message_index|grib_msg|grib_message|grib_index)\b"
    r"(?:\s*:\s*[A-Za-z_.\[\]| ]+)?"
    r"\s*(?<![=!<>])=(?!=)\s*[0-9]+\b"
)

#: Kelvin belongs only inside the decoder in `fetch/`. `459.67` / `273.15` are the giveaway
#: constants of a hand-rolled reimplementation.
KELVIN_REIMPLEMENTATION = re.compile(r"kelvin|\b273\.15\b|\b459\.67\b", re.IGNORECASE)


@pytest.mark.parametrize("source", forecast_sources(), ids=lambda p: p.name)
def test_t29_no_grib_shortname_compared_to_t2m(source: Path) -> None:
    """The single most important line in this file.

    eccodes reports `GRIB_shortName == "2t"` for valid 2 m temperature data. An assertion
    that it equals `"t2m"` FAILS ON GOOD DATA — that wrong form was corrected on `develop`
    at 37ca272, and this test fails loudly if anyone reintroduces it.
    """
    code = normalized_code(source.read_text(encoding="utf-8"))
    for pattern in SHORTNAME_COMPARED_TO_T2M:
        assert not pattern.search(code), (
            f"{source.name} compares GRIB_shortName to 't2m'; eccodes reports '2t' there for "
            f"valid 2 m temperature data, so this guard fails on good data. The correct guard "
            f"is the data variable being 't2m' AND GRIB_cfVarName == 't2m' (fetch/grib.py)."
        )


@pytest.mark.parametrize("source", forecast_sources(), ids=lambda p: p.name)
def test_t29_no_hardcoded_grib_message_number(source: Path) -> None:
    """NBM's index moves with lead time (135 → 173), so a pinned message number is a bug."""
    code = normalized_code(source.read_text(encoding="utf-8"))
    hit = MESSAGE_NUMBER_LITERAL.search(code)
    assert hit is None, (
        f"{source.name} binds a literal GRIB message number: {hit.group(0)!r}; "
        f"the selection must be read out of the `.idx` on every call — NBM's index moves with "
        f"lead time"
    )


@pytest.mark.parametrize("source", forecast_sources(), ids=lambda p: p.name)
def test_t29_no_bare_assert_statements(source: Path) -> None:
    """TR7: `python -O` strips `assert`, so a data guard written as one vanishes in production.

    Guards in live code raise instead. (Test files are free to use `assert`; this scan covers
    `forecast/` only.)
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    lines = sorted(node.lineno for node in asserts)
    assert not asserts, (
        f"{source.name} uses bare `assert` at line(s) {lines}; `python -O` deletes those, so "
        f"the guard silently disappears in production — raise instead"
    )


@pytest.mark.parametrize("source", forecast_sources(), ids=lambda p: p.name)
def test_t29_no_renorm_symbol(source: Path) -> None:
    """The weights are never renormalized over a subset of models. A gap is honest."""
    code = normalized_code(source.read_text(encoding="utf-8")).lower()
    assert "renorm" not in code, (
        f"{source.name} names a weight-rescaling helper; renormalizing over the models that "
        f"happened to arrive silently changes the blend that was fitted"
    )


@pytest.mark.parametrize("source", forecast_sources(), ids=lambda p: p.name)
def test_t29_no_naive_utcnow(source: Path) -> None:
    """`datetime.utcnow()` is deprecated and returns a NAIVE datetime. UTC everywhere, aware."""
    code = normalized_code(source.read_text(encoding="utf-8"))
    assert "utcnow" not in code, (
        f"{source.name} calls datetime.utcnow(): deprecated, and naive — use "
        f"datetime.now(timezone.utc)"
    )


@pytest.mark.parametrize("source", forecast_sources(), ids=lambda p: p.name)
def test_t29_no_kelvin_conversion_reimplemented_in_forecast(source: Path) -> None:
    """Kelvin lives only inside the decoder in `fetch/`; `forecast/` sees degrees F only."""
    code = normalized_code(source.read_text(encoding="utf-8"))
    hit = KELVIN_REIMPLEMENTATION.search(code)
    assert hit is None, (
        f"{source.name} reimplements a Kelvin conversion: {hit.group(0)!r}; "
        f"Kelvin belongs only inside the decoder in fetch/, and temperatures cross into "
        f"forecast/ already in degrees F"
    )


def test_t29_the_scan_actually_sees_source() -> None:
    """A scan over zero files passes vacuously. Prove there is something to scan."""
    sources = forecast_sources()
    assert sources, "no *.py found under forecast/ — every T29 scan above was vacuous"
    names = {path.name for path in sources}
    assert {"cycle.py", "live.py"} <= names, f"F2's own modules are missing from {sorted(names)}"


def test_t29_normalizer_keeps_code_strings_and_drops_docstrings() -> None:
    """The normalizer itself must not be the hole. Comments and docstrings out, literals in."""
    sample = '''"""A docstring mentioning GRIB_shortName == "t2m" and renorm."""
# A comment mentioning GRIB_shortName == "t2m" and utcnow.
LABEL = "keep # this"
if attrs["GRIB_shortName"] == "t2m":
    pass
'''
    code = normalized_code(sample)

    assert "A docstring mentioning" not in code, "docstrings must be dropped"
    assert "A comment mentioning" not in code, "comments must be dropped"
    assert '"keep # this"' in code, "a `#` inside a string literal must not truncate the line"
    assert any(pattern.search(code) for pattern in SHORTNAME_COMPARED_TO_T2M), (
        "the shortName pattern must fire on the real comparison it exists to catch"
    )


# ------------------------------------------------------------------------------------------
# T30 — diff gate
# ------------------------------------------------------------------------------------------

#: F2's branch point: the last commit at which `.gitignore` does NOT yet carry F2's two lines.
#: **Deliberately a pinned sha, never `git merge-base HEAD develop`.** The claim this section
#: makes — "F2 added exactly two lines" — is a fact about F2's own commit (96d0d55), not about
#: this branch's relationship to `develop`. Once the branch is merged into `develop` the
#: merge-base becomes HEAD itself, every diff against it is empty, and the gate reports zero
#: additions for a `.gitignore` that never changed while `fetch/` goes unscanned entirely. A
#: guard anchored to a moving ref stops meaning what it says.
#:
#: `tests/test_forecast_api_guards.py` pins `740dfb0` for the same reason, but that sha is
#: **F4's** branch point and sits *after* F2 — at `740dfb0` both lines are already present, so
#: it cannot serve as F2's base. `37ca272` is the newest commit at which they are absent, and
#: `fetch/` is byte-identical from there to HEAD, so both gates below are rooted correctly.
F2_BRANCH_POINT = "37ca272"

#: The two lines F2 is allowed to add to `.gitignore`, and the only two.
EXPECTED_GITIGNORE_ADDITIONS = ["data/live/", "data/forecast.json"]


def git(*args: str) -> subprocess.CompletedProcess:
    """Run a read-only `git` command in this repository."""
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )


@pytest.fixture()
def git_repo() -> None:
    """Skip rather than fail when `git` is unavailable or this is not a checkout."""
    if shutil.which("git") is None:
        pytest.skip("git is not available on PATH")
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip(f"{REPO} is not a git working tree")


def branch_point() -> str:
    """F2's recorded branch point, resolved to a full sha — or a clean skip if absent."""
    resolved = git("rev-parse", "--verify", f"{F2_BRANCH_POINT}^{{commit}}")
    if resolved.returncode != 0 or not resolved.stdout.strip():
        pytest.skip(f"branch point {F2_BRANCH_POINT} is not present in this checkout")
    return resolved.stdout.strip()


def gitignore_delta(
    base_lines: list[str], current_lines: list[str]
) -> tuple[list[str], list[str]]:
    """`(added, removed)` between two `.gitignore` line lists, each in file order.

    Pulled out of the test below so a companion can prove the comparison actually bites
    without writing to the real `.gitignore`.
    """
    added = [line for line in current_lines if line not in base_lines]
    removed = [line for line in base_lines if line not in current_lines]
    return added, removed


@pytest.mark.usefixtures("git_repo")
def test_t30_fetch_is_untouched_by_this_branch() -> None:
    """`fetch/` is correct and off-limits to F2 — committed, staged and working tree alike.

    `fetch/grib.py`'s variable guard in particular was corrected on `develop` at 37ca272; a
    diff here is the signature of someone "fixing" it back to the wrong form.
    """
    base = branch_point()

    committed = git("diff", "--stat", f"{base}..HEAD", "--", "fetch/")
    assert committed.returncode == 0, committed.stderr
    assert committed.stdout.strip() == "", (
        f"this branch changed fetch/ since {base[:7]}:\n{committed.stdout}"
    )

    working_tree = git("diff", "--", "fetch/")
    assert working_tree.returncode == 0, working_tree.stderr
    assert working_tree.stdout.strip() == "", (
        f"uncommitted changes under fetch/:\n{working_tree.stdout}"
    )

    status = git("status", "--porcelain", "--", "fetch/")
    assert status.returncode == 0, status.stderr
    assert status.stdout.strip() == "", (
        f"untracked or staged entries under fetch/:\n{status.stdout}"
    )


@pytest.mark.usefixtures("git_repo")
def test_t30_gitignore_gained_exactly_the_two_expected_lines() -> None:
    """F2 adds `data/live/` and `data/forecast.json` to `.gitignore` — and nothing else.

    Note on what is deliberately NOT asserted: `git status` shows `.venv` and `data/raw` as
    untracked `??` even though both are ignored by name, because a `dir/`-suffixed pattern
    does not match a **symlink**. That is pre-existing and not F2's doing, so this test
    asserts about `fetch/` and `.gitignore` specifically rather than about a clean tree.
    """
    base = branch_point()

    before = git("show", f"{base}:.gitignore")
    assert before.returncode == 0, before.stderr
    base_lines = before.stdout.splitlines()
    current_lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()

    for expected in EXPECTED_GITIGNORE_ADDITIONS:
        assert expected not in base_lines, (
            f"the pinned base {F2_BRANCH_POINT} already carries {expected!r}, so it post-dates "
            f"F2 and this gate can no longer see F2's addition — repin it to a commit before "
            f"F2 (96d0d55) rather than relaxing the assertion below"
        )

    added, removed = gitignore_delta(base_lines, current_lines)

    assert added == EXPECTED_GITIGNORE_ADDITIONS, (
        f".gitignore must gain exactly {EXPECTED_GITIGNORE_ADDITIONS}, but gained {added}"
    )
    assert removed == [], f".gitignore lost line(s) {removed}; F2 removes none"


def test_t30_the_gitignore_gate_fires_on_a_bad_sample() -> None:
    """A guard that cannot fail is worse than none — prove this one bites in both directions.

    Runs entirely on synthetic line lists, so it exercises the same comparison the live test
    uses without writing a byte to the real `.gitignore`.
    """
    base = ["data/raw/", "data/*.parquet", "*.grib2"]
    good = base + EXPECTED_GITIGNORE_ADDITIONS

    # The clean case, or every red case below would be meaningless.
    assert gitignore_delta(base, good) == (EXPECTED_GITIGNORE_ADDITIONS, [])

    # A THIRD line added — the gate must not shrug it off.
    added, removed = gitignore_delta(base, good + ["data/scratch/"])
    assert added != EXPECTED_GITIGNORE_ADDITIONS
    assert added == [*EXPECTED_GITIGNORE_ADDITIONS, "data/scratch/"]
    assert removed == []

    # One of the two expected lines MISSING, each in turn.
    for dropped in EXPECTED_GITIGNORE_ADDITIONS:
        partial = [line for line in good if line != dropped]
        added, removed = gitignore_delta(base, partial)
        assert added != EXPECTED_GITIGNORE_ADDITIONS, (
            f"dropping {dropped!r} must be caught, but `added` still matched"
        )

    # Both expected lines missing: the F2 change reverted wholesale.
    assert gitignore_delta(base, base) == ([], [])

    # A pre-existing line deleted — caught by the `removed` half, which is the reason it
    # exists at all: `added` alone stays correct here.
    added, removed = gitignore_delta(base, ["data/raw/", "*.grib2", *EXPECTED_GITIGNORE_ADDITIONS])
    assert added == EXPECTED_GITIGNORE_ADDITIONS
    assert removed == ["data/*.parquet"]

    # And the empty-diff shape that a merge-base pinned to HEAD used to produce: zero
    # additions is a FAILURE, not a pass.
    assert gitignore_delta(good, good) == ([], [])
    assert [] != EXPECTED_GITIGNORE_ADDITIONS
