"""`.idx` parse, anchored selection and byte-range arithmetic — SPEC §3 / §8, spike F9 + F10.

Every test here is offline: the only inputs are the verbatim NOAA `.idx` text captured under
`tests/fixtures/idx/` (see that directory's README for provenance) and small synthetic strings
built in this file. **No test in this module opens a socket.**

These tests carry no marker on purpose. They read text, not GRIB bytes, so they belong in the
default always-run set rather than behind `-m integration`.
"""

import re
from pathlib import Path

import pytest

from fetch.idx import NEEDLE, byte_range, parse_idx, range_header, select_tmp_2m

# The unanchored form of the needle. Never used by `fetch/`; kept here only so a test can prove
# the leading colon in NEEDLE does real work (spike F9 — the unanchored form silently matches
# `APTMP:2 m above ground`, i.e. apparent temperature, which is a different variable).
UNANCHORED = "TMP:2 m above ground"

# Message numbers the anchored needle must select, read back from the captured fixtures.
# These are *expected values recorded in tests*, never constants in `fetch/`.
SELECTION_FLOOR = {
    "hrrr_20260805_12z_f006.idx": "71",
    "gfs_20260805_12z_f006.idx": "581",
    "nam_20260805_12z_f006.idx": "321",
    "nbm_20260805_12z_f006.idx": "187",
}

# SPEC §8 floor: NBM's TMP:2m index MOVES with lead time (spike F10).
NBM_MOVING_INDEX = {
    "nbm_20260805_12z_f006.idx": "187",
    "nbm_20260805_12z_f012.idx": "192",
    "nbm_20260805_12z_f024.idx": "195",
}


def read_idx(FIXTURES: Path, name: str) -> str:
    """Read one captured `.idx` file verbatim. Path comes from the session fixture, never cwd."""
    path = FIXTURES / "idx" / name
    assert path.exists(), (
        f"missing captured fixture {path}; SPEC §13 forbids live-network tests, so this test "
        f"cannot fall back to fetching it — re-run `uv run python -m fetch.capture_fixtures`"
    )
    return path.read_text()


def synthetic_idx(*lines: str) -> str:
    """Build a small well-formed `.idx` body from literal lines (trailing newline included)."""
    return "".join(line + "\n" for line in lines)


# --------------------------------------------------------------------------------------------
# parse_idx
# --------------------------------------------------------------------------------------------


def test_parse_idx_message_numbers_are_strings(FIXTURES: Path) -> None:
    """NAM emits sub-messages `284.1` / `284.2`; `int(msg)` raises on them (plan Stream 2)."""
    records = parse_idx(read_idx(FIXTURES, "nam_20260805_12z_f006.idx"))

    assert records, "parse_idx returned no records for the captured NAM .idx"
    non_str = [r["msg"] for r in records if not isinstance(r["msg"], str)]
    assert not non_str, (
        f"message numbers must stay `str` (NAM sub-messages like '284.1' make int() raise); "
        f"got {len(non_str)} non-str msg values, first few: {non_str[:5]}"
    )


def test_parse_idx_parses_nam_sub_messages(FIXTURES: Path) -> None:
    """`284.1` and `284.2` both parse, and they share a start byte (the `.1`/`.2` shape)."""
    records = parse_idx(read_idx(FIXTURES, "nam_20260805_12z_f006.idx"))
    by_msg = {r["msg"]: r for r in records}

    for msg in ("284.1", "284.2"):
        assert msg in by_msg, (
            f"expected NAM sub-message {msg!r} to parse; parse_idx produced "
            f"{len(records)} records and no msg == {msg!r}"
        )
        with pytest.raises(ValueError):
            int(by_msg[msg]["msg"])  # documents exactly why msg must never be int()-ed

    assert by_msg["284.1"]["start"] == by_msg["284.2"]["start"], (
        f"NAM 284.1/284.2 are expected to share one start byte; got "
        f"{by_msg['284.1']['start']} and {by_msg['284.2']['start']}"
    )


def test_parse_idx_numbering_is_not_positional(FIXTURES: Path) -> None:
    """Message numbers come from the line, never from `enumerate()` — NAM's line 361 is msg 321."""
    text = read_idx(FIXTURES, "nam_20260805_12z_f006.idx")
    records = parse_idx(text)
    lines = [line for line in text.splitlines() if line.strip()]

    assert len(records) == len(lines), (
        f"parse_idx dropped or invented lines: {len(lines)} non-empty lines in the NAM .idx "
        f"but {len(records)} records"
    )
    positional = [i for i, r in enumerate(records, start=1) if r["msg"] != str(i)]
    assert positional, (
        "the NAM .idx is expected to contain sub-messages, so record position and message "
        "number must diverge somewhere; they matched everywhere, which means the fixture "
        "changed or numbering was derived from enumerate()"
    )


def test_parse_idx_keeps_colons_in_the_trailing_extra_field(FIXTURES: Path) -> None:
    """NBM probability lines carry extra colon-separated fields; `extra` must keep them whole."""
    records = parse_idx(read_idx(FIXTURES, "nbm_20260805_12z_f006.idx"))

    assert all(r["raw"].startswith(r["msg"] + ":") for r in records), (
        "every record's `raw` must be the original line, so downstream `ens std dev` "
        "rejection can match against it"
    )
    multi = [r for r in records if ":" in r["extra"]]
    assert multi, (
        f"expected at least one NBM record whose trailing extra field contains a colon "
        f"(e.g. 'prob <304.8:prob fcst 3/7:probability forecast'); found none across "
        f"{len(records)} records — the parser is over-splitting"
    )


def test_parse_idx_start_offsets_are_ints(FIXTURES: Path) -> None:
    """`start` is a byte offset used in arithmetic, so it is an `int` (unlike `msg`)."""
    records = parse_idx(read_idx(FIXTURES, "hrrr_20260805_12z_f006.idx"))

    bad = [r["msg"] for r in records if not isinstance(r["start"], int)]
    assert not bad, f"start offsets must be int for byte-range arithmetic; non-int for msgs {bad}"


# --------------------------------------------------------------------------------------------
# select_tmp_2m — the anchored needle (SPEC §8 floor, spike F9)
# --------------------------------------------------------------------------------------------


def test_needle_is_anchored_with_a_leading_colon() -> None:
    """SPEC §3 / spike F9: the leading colon is load-bearing, not cosmetic."""
    assert NEEDLE == ":TMP:2 m above ground:", (
        f"NEEDLE must be exactly ':TMP:2 m above ground:' (spike F9 — the leading colon is what "
        f"rejects APTMP); got {NEEDLE!r}"
    )


def test_select_tmp_2m_nbm_rejects_aptmp_and_ens_std_dev(FIXTURES: Path) -> None:
    """SPEC §8 floor: NBM f006 selects msg 187, not msg 1 (APTMP) and not msg 188 (ens std dev)."""
    records = parse_idx(read_idx(FIXTURES, "nbm_20260805_12z_f006.idx"))
    chosen = select_tmp_2m(records)

    assert chosen["msg"] == "187", (
        f"SPEC §8 floor: NBM 2026-08-05 12z f006 must select msg '187'; got {chosen['msg']!r} "
        f"from raw line {chosen['raw']!r}"
    )

    by_msg = {r["msg"]: r for r in records}
    aptmp = by_msg["1"]
    assert "APTMP:2 m above ground" in aptmp["raw"], (
        f"fixture drift: NBM msg 1 was expected to be the APTMP:2 m above ground line, got "
        f"{aptmp['raw']!r}"
    )
    assert chosen["msg"] != "1", (
        "spike F9: the APTMP:2 m above ground line (msg 1) must be REJECTED — selecting it "
        "silently returns apparent temperature instead of temperature"
    )
    assert "APTMP" not in chosen["var"], (
        f"selected variable must be TMP, not an APTMP variant; got var={chosen['var']!r}"
    )

    ens = by_msg["188"]
    assert "ens std dev" in ens["raw"], (
        f"fixture drift: NBM msg 188 was expected to be the 'ens std dev' line, got {ens['raw']!r}"
    )
    assert chosen["msg"] != "188", (
        "SPEC §3: the 'ens std dev' record (msg 188) must be REJECTED — it is a spread field, "
        "not the forecast temperature"
    )
    assert "ens std dev" not in chosen["raw"], (
        f"selected record must not be an ensemble spread field; got raw {chosen['raw']!r}"
    )


def test_unanchored_needle_would_have_matched_more_than_one_line(FIXTURES: Path) -> None:
    """Proves the anchor does real work: unanchored matches strictly more lines than anchored."""
    text = read_idx(FIXTURES, "nbm_20260805_12z_f006.idx")
    lines = [line for line in text.splitlines() if line.strip()]

    unanchored_hits = [line for line in lines if UNANCHORED in line]
    anchored_hits = [line for line in lines if NEEDLE in line]

    assert len(unanchored_hits) > 1, (
        f"spike F9 expects the unanchored string {UNANCHORED!r} to match MORE THAN ONE line in "
        f"the NBM f006 .idx; it matched {len(unanchored_hits)}: {unanchored_hits}"
    )
    assert len(unanchored_hits) > len(anchored_hits), (
        f"the leading colon in NEEDLE must reject at least one line the unanchored form accepts; "
        f"unanchored={len(unanchored_hits)} anchored={len(anchored_hits)}"
    )
    assert any("APTMP" in line for line in unanchored_hits), (
        f"the extra unanchored hit is expected to be the APTMP line; unanchored hits were "
        f"{unanchored_hits}"
    )
    assert not any("APTMP" in line for line in anchored_hits), (
        f"the anchored needle must never match an APTMP line; anchored hits were {anchored_hits}"
    )


@pytest.mark.parametrize(("fixture_name", "expected_msg"), sorted(NBM_MOVING_INDEX.items()))
def test_nbm_index_moves_with_lead(FIXTURES: Path, fixture_name: str, expected_msg: str) -> None:
    """SPEC §8 floor / spike F10: NBM f006/f012/f024 select 187/192/195, read from the `.idx`."""
    chosen = select_tmp_2m(parse_idx(read_idx(FIXTURES, fixture_name)))

    assert chosen["msg"] == expected_msg, (
        f"SPEC §8 floor: {fixture_name} must select msg {expected_msg!r} (NBM's TMP:2m index "
        f"moves with lead time — spike F10); got {chosen['msg']!r} at start "
        f"{chosen['start']} from raw {chosen['raw']!r}"
    )


@pytest.mark.parametrize(("fixture_name", "expected_msg"), sorted(SELECTION_FLOOR.items()))
def test_selection_reproduces_the_captured_message_numbers(
    FIXTURES: Path, fixture_name: str, expected_msg: str
) -> None:
    """SPEC §8 floor: HRRR/GFS/NAM/NBM f006 select 71 / 581 / 321 / 187 from captured text."""
    chosen = select_tmp_2m(parse_idx(read_idx(FIXTURES, fixture_name)))

    assert chosen["msg"] == expected_msg, (
        f"SPEC §8 floor: {fixture_name} must select msg {expected_msg!r} (recorded provenance in "
        f"tests/fixtures/README.md); got {chosen['msg']!r} from raw {chosen['raw']!r}"
    )
    assert chosen["var"] == "TMP", f"selected var must be 'TMP'; got {chosen['var']!r}"
    assert chosen["level"] == "2 m above ground", (
        f"selected level must be '2 m above ground'; got {chosen['level']!r}"
    )


def test_select_tmp_2m_raises_when_nothing_matches() -> None:
    """SPEC §3: zero hits is a hard failure — the error names the clause and the actual count."""
    records = parse_idx(
        synthetic_idx(
            "1:0:d=2026080512:APTMP:2 m above ground:6 hour fcst:",
            "2:1000:d=2026080512:TMP:surface:6 hour fcst:",
            "3:2000:d=2026080512:DPT:2 m above ground:6 hour fcst:",
        )
    )

    with pytest.raises(ValueError) as excinfo:
        select_tmp_2m(records)

    message = str(excinfo.value)
    assert "0" in message, f"the error must print the actual hit count (0); got {message!r}"
    assert "SPEC" in message, (
        f"the error must name the SPEC clause it enforces (SPEC §3 / spike F9); got {message!r}"
    )


def test_select_tmp_2m_raises_when_two_records_match() -> None:
    """SPEC §3: more than one survivor is ambiguous — refuse rather than pick arbitrarily."""
    records = parse_idx(
        synthetic_idx(
            "10:0:d=2026080512:TMP:2 m above ground:6 hour fcst:",
            "11:5000:d=2026080512:TMP:2 m above ground:6 hour fcst:",
            "12:9000:d=2026080512:TMP:2 m above ground:6 hour fcst:ens std dev",
        )
    )

    with pytest.raises(ValueError) as excinfo:
        select_tmp_2m(records)

    message = str(excinfo.value)
    assert "2" in message, (
        f"the error must print the actual hit count (2 survive after 'ens std dev' rejection); "
        f"got {message!r}"
    )
    assert "SPEC" in message, f"the error must name the SPEC clause; got {message!r}"


# --------------------------------------------------------------------------------------------
# byte_range / range_header
# --------------------------------------------------------------------------------------------


def test_byte_range_on_nam_matches_the_captured_range(FIXTURES: Path) -> None:
    """NAM msg 321: 48465225 → next strictly greater offset 48706129, so end is 48706128."""
    records = parse_idx(read_idx(FIXTURES, "nam_20260805_12z_f006.idx"))
    chosen = select_tmp_2m(records)
    start, end = byte_range(records, chosen)

    assert (start, end) == (48465225, 48706128), (
        f"tests/fixtures/README.md records NAM f006 as bytes=48465225-48706128 (240904 B); "
        f"got start={start} end={end}"
    )
    assert range_header(start, end) == "bytes=48465225-48706128", (
        f"range header must render as 'bytes=S-E'; got {range_header(start, end)!r}"
    )
    assert end - start + 1 == 240904, (
        f"the NAM range length must match the captured .bin size of 240904 bytes; got "
        f"{end - start + 1}"
    )


def test_byte_range_skips_records_sharing_the_chosen_start_byte() -> None:
    """The NAM `.1`/`.2` shape: 'the next line' would yield a zero-length range."""
    records = parse_idx(
        synthetic_idx(
            "284.1:42835573:d=2026080512:UGRD:975 mb:6 hour fcst:",
            "284.2:42835573:d=2026080512:VGRD:975 mb:6 hour fcst:",
            "285:42900000:d=2026080512:TMP:975 mb:6 hour fcst:",
        )
    )
    chosen = records[0]
    start, end = byte_range(records, chosen)

    assert start == 42835573, f"start must be the chosen record's offset; got {start}"
    assert end == 42899999, (
        f"end must be the next STRICTLY GREATER start offset (42900000) minus 1; got {end}"
    )
    assert end is not None and end - start + 1 > 0, (
        f"range length must be > 0 — 284.1 and 284.2 share start byte {start}, so 'the next "
        f"line' would give a zero-or-negative length; got length {(end or 0) - start + 1}"
    )


def test_byte_range_on_a_two_record_shared_start_pair_is_still_open_ended() -> None:
    """Two records sharing a start byte with nothing after: no strictly greater offset exists."""
    records = parse_idx(
        synthetic_idx(
            "284.1:42835573:d=2026080512:UGRD:975 mb:6 hour fcst:",
            "284.2:42835573:d=2026080512:VGRD:975 mb:6 hour fcst:",
        )
    )
    start, end = byte_range(records, records[0])

    assert start == 42835573, f"start must be the chosen record's offset; got {start}"
    assert end is None, (
        f"no record has a strictly greater start offset, so end must be None (open-ended range) "
        f"rather than a zero-length range; got {end}"
    )
    assert range_header(start, end) == "bytes=42835573-", (
        f"an open-ended range renders as 'bytes=S-'; got {range_header(start, end)!r}"
    )


def test_byte_range_on_the_last_record_is_open_ended(FIXTURES: Path) -> None:
    """The final GRIB message runs to EOF: end is None and the header omits it."""
    records = parse_idx(read_idx(FIXTURES, "hrrr_20260805_12z_f006.idx"))
    last = max(records, key=lambda r: r["start"])
    start, end = byte_range(records, last)

    assert end is None, (
        f"the record with the highest start offset (msg {last['msg']!r} at {last['start']}) has "
        f"no successor, so end must be None; got {end}"
    )
    assert range_header(start, end) == f"bytes={start}-", (
        f"the last message's range must render as 'bytes={start}-'; got "
        f"{range_header(start, end)!r}"
    )


def test_byte_range_is_not_positional(FIXTURES: Path) -> None:
    """`byte_range` uses offsets, not list position — every produced range has positive length."""
    records = parse_idx(read_idx(FIXTURES, "nam_20260805_12z_f006.idx"))

    zero_length = []
    for record in records:
        start, end = byte_range(records, record)
        if end is not None and end - start + 1 <= 0:
            zero_length.append((record["msg"], start, end))

    assert not zero_length, (
        f"every byte range must have positive length; {len(zero_length)} did not, first few: "
        f"{zero_length[:5]}"
    )


def test_range_header_renders_both_forms() -> None:
    """`bytes=S-E` when the end is known, `bytes=S-` when it is not."""
    assert range_header(0, 99) == "bytes=0-99", f"got {range_header(0, 99)!r}"
    assert range_header(153756600, 155939230) == "bytes=153756600-155939230", (
        f"got {range_header(153756600, 155939230)!r}"
    )
    assert range_header(156724060, None) == "bytes=156724060-", (
        f"an open-ended range must omit the end entirely; got {range_header(156724060, None)!r}"
    )


# --------------------------------------------------------------------------------------------
# Integrity guard
# --------------------------------------------------------------------------------------------


def test_no_message_index_is_hardcoded_in_fetch_idx(REPO_ROOT: Path) -> None:
    """CLAUDE.md conventions: never hardcode a GRIB message index — NBM's moves with lead."""
    source = (REPO_ROOT / "fetch" / "idx.py").read_text()
    forbidden = ("71", "581", "321", "187", "192", "195")

    hits = {n: len(re.findall(rf"\b{n}\b", source)) for n in forbidden}
    offenders = {n: c for n, c in hits.items() if c}
    assert not offenders, (
        f"fetch/idx.py must never hardcode a GRIB message index (CLAUDE.md: 'parse the .idx every "
        f"time — NBM's index moves'); found {offenders} in the module source"
    )
