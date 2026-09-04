"""T4 Task 2.2 tests — IEM ASOS parsing, coverage measurement, obs.parquet write.

SPEC §13: **no live network in pytest.** Every byte read here comes from
`tests/fixtures/iem/oma_sample.csv`; `fetch_obs` is exercised through an injected getter.
An autouse fixture below makes that structural — any socket opened in this module fails
the test.

The load-bearing test in this file is `test_parsed_minutes_are_not_all_on_the_hour`.
Spike F5: ASOS reports near `:52`, so an obs file whose timestamps all land on `:00`
means something resampled, and T5's ±30 min nearest join then matches ZERO rows and
reports a perfect MAE on an empty frame (SPEC §4/§10). The fixture's numbers are asserted
raw as well as parsed, so the fixture cannot quietly change underneath these tests.
"""

import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from fetch import obs
from fetch.schema import OBS_SCHEMA

# Captured fixture: 2026-09-01 00:00 .. 2026-09-03 23:55 UTC (fetch/capture_iem_fixture.py).
RAW_DATA_ROWS = 912
RAW_MISSING_ROWS = 837
PARSED_ROWS = 75
PARSED_DISTINCT_HOURS = 72
# Every surviving observation is off-hour: 72 at :52 plus one each at :46, :19, :07.
PARSED_MINUTES = {52, 46, 19, 7}


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §13: no test in this module may open a socket.

    Structural, not a promise in a docstring — if the obs loader ever grows a live
    fetch, the tests turn red instead of silently going to the network.
    """

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "SPEC §13 violation: a test in tests/test_obs.py tried to open a network "
            "socket. Every byte must come from tests/fixtures/."
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# --- fixture access ----------------------------------------------------------------------


@pytest.fixture
def iem_text(FIXTURES: Path) -> str:
    path = FIXTURES / "iem" / "oma_sample.csv"
    assert path.exists(), (
        f"missing captured IEM fixture at {path}; SPEC §13 forbids falling back to a live "
        "fetch — re-run `uv run python -m fetch.capture_iem_fixture`"
    )
    return path.read_text(encoding="utf-8")


@pytest.fixture
def parsed(iem_text: str) -> pd.DataFrame:
    return obs.parse_iem_csv(iem_text)


def _raw_rows(text: str) -> list[list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    return [[f.strip() for f in ln.split(",")] for ln in lines[1:]]


def synthetic_obs(n_rows: int, span: timedelta, minute_offset: int = 52) -> pd.DataFrame:
    """`n_rows` evenly spaced observations across `span`, first one at `:minute_offset`."""
    start = datetime(2026, 8, 1, 0, minute_offset, tzinfo=timezone.utc)
    step = span / n_rows
    stamps = [start + step * i for i in range(n_rows)]
    return pd.DataFrame(
        {
            "valid_time": pd.Series(stamps, dtype="datetime64[us, UTC]"),
            "temp_f": pd.Series([70.0 + (i % 10) for i in range(n_rows)], dtype="float64"),
        }
    )


# --- 1. missing rows are dropped ---------------------------------------------------------


def test_fixture_raw_counts_are_what_the_tests_assume(iem_text: str) -> None:
    """Pin the fixture so it cannot silently change under the assertions below."""
    rows = _raw_rows(iem_text)
    assert len(rows) == RAW_DATA_ROWS, (
        f"tests/fixtures/iem/oma_sample.csv should hold {RAW_DATA_ROWS} data rows, "
        f"found {len(rows)} — the fixture changed; re-derive the expected numbers, do not "
        "edit them to match (SPEC §10)"
    )
    missing = [r for r in rows if r[2] == "M"]
    assert len(missing) == RAW_MISSING_ROWS, (
        f"the fixture should hold {RAW_MISSING_ROWS} rows with tmpf == 'M', found "
        f"{len(missing)}; it exists to pin M-dropping (SPEC §4)"
    )
    assert len(rows) - len(missing) == PARSED_ROWS


def test_missing_rows_are_dropped_never_filled(parsed: pd.DataFrame) -> None:
    """SPEC §4: `M` means missing. Drop it — never interpolate, ffill or substitute."""
    assert len(parsed) == PARSED_ROWS, (
        f"SPEC §4: {RAW_DATA_ROWS} raw rows minus {RAW_MISSING_ROWS} 'M' rows leaves "
        f"{PARSED_ROWS} observations; parse_iem_csv returned {len(parsed)}. More than "
        f"{PARSED_ROWS} means an 'M' survived or a gap was filled."
    )
    assert parsed["temp_f"].notna().all(), (
        "SPEC §4: a NaN survived into the parsed frame — 'M' rows must be dropped, not "
        "carried through as NaN for something downstream to fill"
    )
    assert parsed["valid_time"].notna().all(), "an unparseable timestamp survived as NaT"


def test_unparseable_values_and_timestamps_are_dropped() -> None:
    """`M`, `T`, blank, garbage text and a broken timestamp all leave the dataset."""
    text = (
        "station,valid,tmpf\n"
        "OMA,2026-09-01 00:52,83.00\n"
        "OMA,2026-09-01 01:52,M\n"
        "OMA,2026-09-01 02:52,T\n"
        "OMA,2026-09-01 03:52,\n"
        "OMA,2026-09-01 04:52,n/a\n"
        "OMA,not-a-timestamp,71.00\n"
        "OMA,2026-09-01 05:52,79.00\n"
    )
    got = obs.parse_iem_csv(text)
    assert got["temp_f"].tolist() == [83.0, 79.0], (
        f"SPEC §4: only the two numeric observations may survive; got {got.to_dict('records')}"
    )


# --- 2. the anti-resample test (the important one) ---------------------------------------


def test_parsed_minutes_are_not_all_on_the_hour(parsed: pd.DataFrame) -> None:
    """Spike F5 / SPEC §4: the true minute resolution MUST survive parsing.

    This is the single most important assertion in the file. ASOS reports near `:52`.
    If every observation here landed on `:00`, something floored, rounded or resampled
    the timestamps — and T5's ±30 min nearest join would then match ZERO rows and report
    a flawless MAE on an empty dataframe (SPEC §10).
    """
    minutes = set(parsed["valid_time"].dt.minute.tolist())
    assert any(m != 0 for m in minutes), (
        "spike F5: every parsed observation lands on minute :00. Real ASOS observations "
        "do not — this means parse_iem_csv floored, rounded or resampled the timestamps. "
        "T5 joins forecasts to obs with a ±30 min NEAREST match on these exact values; an "
        "on-the-hour obs file matches ZERO rows and scores a perfect MAE on an empty join "
        "(SPEC §4/§10). Remove the resampling; do not adjust this test."
    )
    assert minutes != {0}, f"all timestamps collapsed onto the hour; minutes = {minutes}"
    assert minutes == PARSED_MINUTES, (
        f"this fixture's surviving observations sit at minutes {sorted(PARSED_MINUTES)} — "
        f"72 at :52 plus one each at :46, :19, :07. Got {sorted(minutes)}. NOT ONE real "
        "observation lands on :00 (spike F5)."
    )
    assert 0 not in minutes, "spike F5: no real observation in this slice falls on minute :00"


# --- 3. row count is preserved exactly ---------------------------------------------------


def test_parsing_adds_no_rows(parsed: pd.DataFrame) -> None:
    """No reindexing, no resampling, no filling — parsing only ever removes rows."""
    assert len(parsed) == PARSED_ROWS
    assert len(parsed) != RAW_DATA_ROWS, (
        f"{RAW_DATA_ROWS} rows survived: the 'M' rows were kept (SPEC §4 says drop them)"
    )
    assert len(parsed) != PARSED_DISTINCT_HOURS, (
        f"{PARSED_DISTINCT_HOURS} rows survived — exactly the distinct-hour count. That is "
        "the signature of a resample-to-hourly, which spike F5 forbids."
    )


# --- 4. distinct_hours is not a row count ------------------------------------------------


def test_distinct_hours_on_the_fixture(parsed: pd.DataFrame) -> None:
    """SPEC §8 acceptance measure: distinct floored UTC hours covered."""
    assert obs.distinct_hours(parsed) == PARSED_DISTINCT_HOURS, (
        f"the fixture covers {PARSED_DISTINCT_HOURS} distinct hours; distinct_hours "
        f"returned {obs.distinct_hours(parsed)}"
    )


def test_distinct_hours_is_demonstrably_not_a_row_count() -> None:
    """900 rows crammed into 3 hours: a row count passes, the real check does not."""
    dense = synthetic_obs(900, timedelta(hours=3), minute_offset=0)
    assert len(dense) == 900
    assert obs.distinct_hours(dense) == 3, (
        "SPEC §8: distinct_hours must be nunique() on the floored hour. It returned "
        f"{obs.distinct_hours(dense)} for 900 rows spanning 3 hours — if it returns 900 it "
        "is a row count wearing a coverage name, and a 3-hour file would pass the §8 floor."
    )


# --- 5. duplicates ------------------------------------------------------------------------


def test_exact_duplicate_timestamps_keep_the_first_value() -> None:
    text = (
        "station,valid,tmpf\n"
        "OMA,2026-09-01 00:52,83.00\n"
        "OMA,2026-09-01 00:52,99.00\n"
        "OMA,2026-09-01 01:52,81.00\n"
    )
    got = obs.parse_iem_csv(text)
    assert len(got) == 2, f"the duplicate valid_time was not removed: {got.to_dict('records')}"
    assert got.loc[0, "temp_f"] == 83.0, (
        f"dedupe must keep the FIRST value for a repeated timestamp; kept {got.loc[0, 'temp_f']}"
    )


# --- 6. sorting ---------------------------------------------------------------------------


def test_output_is_sorted_ascending_from_shuffled_input() -> None:
    text = (
        "station,valid,tmpf\n"
        "OMA,2026-09-01 05:52,79.00\n"
        "OMA,2026-09-01 00:52,83.00\n"
        "OMA,2026-09-01 03:52,75.00\n"
        "OMA,2026-09-01 01:52,81.00\n"
    )
    got = obs.parse_iem_csv(text)
    assert got["valid_time"].is_monotonic_increasing, (
        f"parse_iem_csv must sort ascending; got {got['valid_time'].tolist()}"
    )
    assert got["temp_f"].tolist() == [83.0, 81.0, 75.0, 79.0]
    assert got.index.tolist() == [0, 1, 2, 3], "the index must be reset after sorting"


# --- 7. dtypes ----------------------------------------------------------------------------


def test_parsed_dtypes_and_column_order(parsed: pd.DataFrame) -> None:
    """SPEC §6 column order; SPEC §2 UTC everywhere; float64 for T5's merge_asof."""
    assert list(parsed.columns) == ["valid_time", "temp_f"], (
        f"SPEC §6: obs columns are exactly ['valid_time', 'temp_f']; got {list(parsed.columns)}"
    )
    assert str(parsed["valid_time"].dt.tz) == "UTC", (
        f"SPEC §2 (UTC everywhere): valid_time tz is {parsed['valid_time'].dt.tz}, expected UTC"
    )
    assert parsed["temp_f"].dtype == "float64", (
        f"temp_f must be float64 for OBS_SCHEMA; got {parsed['temp_f'].dtype}"
    )


# --- 8. an all-M input writes nothing -----------------------------------------------------


def test_all_missing_input_yields_empty_frame_and_write_obs_refuses(tmp_path: Path) -> None:
    """SPEC §10: an empty parquet passes a schema check perfectly and scores perfectly."""
    text = "station,valid,tmpf\n" + "".join(
        f"OMA,2026-09-01 {h:02d}:52,M\n" for h in range(24)
    )
    empty = obs.parse_iem_csv(text)
    assert len(empty) == 0, f"every row was 'M'; expected an empty frame, got {len(empty)} rows"
    assert list(empty.columns) == ["valid_time", "temp_f"]
    assert obs.distinct_hours(empty) == 0

    out = tmp_path / "obs.parquet"
    with pytest.raises(AssertionError) as excinfo:
        obs.write_obs(empty, out)
    message = str(excinfo.value)
    assert "§10" in message and "§8" in message, (
        f"the refusal must cite SPEC §8/§10; got {message!r}"
    )
    assert not out.exists(), (
        f"write_obs created {out} for an empty frame — an empty parquet is the SPEC §10 fake"
    )


# --- 9. plenty of rows, not enough hours --------------------------------------------------


def test_many_rows_but_too_few_hours_is_refused(tmp_path: Path) -> None:
    """The whole point of the §8 measure: 900 rows in 3 hours must NOT pass."""
    dense = synthetic_obs(900, timedelta(hours=3), minute_offset=0)
    out = tmp_path / "obs.parquet"
    with pytest.raises(AssertionError) as excinfo:
        obs.write_obs(dense, out, min_rows=700, min_distinct_hours=700)
    message = str(excinfo.value)
    assert "distinct" in message.lower(), (
        f"the failure must say DISTINCT HOURS, not rows — a row count would have passed "
        f"here (900 >= 700). Message was {message!r}"
    )
    assert "3" in message and "900" in message, (
        f"the message must name both the distinct-hour count (3) and the row count (900); "
        f"got {message!r}"
    )
    assert "§8" in message
    assert not out.exists(), f"write_obs wrote {out} despite failing the coverage floor"


# --- 10. build_url ------------------------------------------------------------------------


def test_build_url_matches_the_spike_f4_verified_request() -> None:
    url = obs.build_url(
        datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 9, 4, tzinfo=timezone.utc)
    )
    for token in (
        "station=OMA",
        "data=tmpf",
        "tz=Etc/UTC",
        "format=onlycomma",
        "year1=2026",
        "month1=9",
        "day1=1",
        "year2=2026",
        "month2=9",
        "day2=4",
    ):
        assert token in url, f"spike F4 verified URL must contain {token!r}; got {url}"
    assert url.startswith(obs.IEM_URL), f"URL must be built on {obs.IEM_URL}; got {url}"
    assert "open-meteo" not in url.lower(), (
        "SPEC §11 R1 (Open-Meteo) is RETIRED and FORBIDDEN as an observation source"
    )


def test_build_url_uses_the_bounds_it_is_given() -> None:
    url = obs.build_url(
        datetime(2026, 8, 5, 11, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc),
    )
    assert "year1=2026&month1=8&day1=5" in url and "year2=2026&month2=9&day2=4" in url, (
        f"build_url ignored its arguments: {url}"
    )


def test_build_url_treats_a_naive_datetime_as_utc() -> None:
    """SPEC §2 UTC everywhere: a naive datetime is UTC, never local time."""
    naive = obs.build_url(datetime(2026, 9, 1, 0, 30), datetime(2026, 9, 4, 0, 30))
    aware = obs.build_url(
        datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc),
        datetime(2026, 9, 4, 0, 30, tzinfo=timezone.utc),
    )
    assert naive == aware, (
        f"SPEC §2: a naive datetime must be read as UTC.\n  naive: {naive}\n  aware: {aware}"
    )


# --- 11. fetch_obs (injected getter, never a socket) --------------------------------------


class _StubResponse:
    """Minimal stand-in for `requests.Response` — status and body only, no socket."""

    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def _stub_get(response: _StubResponse, calls: list):
    def _fake_get(url: str, timeout: int | None = None):
        calls.append((url, timeout))
        return response

    return _fake_get


def test_fetch_obs_parses_a_200_response(iem_text: str) -> None:
    calls: list = []
    got = obs.fetch_obs(
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 4, tzinfo=timezone.utc),
        session_get=_stub_get(_StubResponse(200, iem_text), calls),
    )
    assert len(got) == PARSED_ROWS
    assert obs.distinct_hours(got) == PARSED_DISTINCT_HOURS
    assert set(got["valid_time"].dt.minute.tolist()) == PARSED_MINUTES
    assert len(calls) == 1, f"fetch_obs should issue exactly one GET; issued {len(calls)}"
    url, timeout = calls[0]
    assert "station=OMA" in url
    assert timeout == 120, f"SPEC §9: the IEM GET must carry timeout=120; got {timeout}"


@pytest.mark.parametrize("status", [500, 503, 404, 403, 302])
def test_fetch_obs_non_200_is_a_spec_9_hard_stop_with_no_fallback(status: int) -> None:
    """There is exactly one observation source. A non-200 is reported, never worked around."""
    calls: list = []
    with pytest.raises(RuntimeError) as excinfo:
        obs.fetch_obs(
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 4, tzinfo=timezone.utc),
            session_get=_stub_get(_StubResponse(status, "boom"), calls),
        )
    message = str(excinfo.value)
    assert "§9" in message, f"a non-200 from IEM is a SPEC §9 hard stop; got {message!r}"
    assert str(status) in message, f"the message must name the status {status}; got {message!r}"
    lowered = message.lower()
    assert "§11 r1" in lowered or "open-meteo" in lowered, (
        "the message must state that SPEC §11 R1 (Open-Meteo) is RETIRED and FORBIDDEN — "
        f"there is no fallback source; got {message!r}"
    )
    assert "retired" in lowered and "forbidden" in lowered, (
        f"the message must say the retired source is forbidden; got {message!r}"
    )
    assert len(calls) == 1, (
        f"fetch_obs made {len(calls)} requests on an HTTP {status} — it must NOT fall back "
        "to a second source (SPEC §11 R1 is retired and forbidden)"
    )


# --- 12. obs_summary ----------------------------------------------------------------------


def test_obs_summary_shape_and_iso_z_timestamps(parsed: pd.DataFrame) -> None:
    """`fetch/backfill.py` writes this straight into data/coverage.json's `obs` block."""
    summary = obs.obs_summary(parsed)
    assert set(summary) == {"rows", "distinct_hours", "start", "end"}, (
        f"obs_summary contract is {{rows, distinct_hours, start, end}}; got {sorted(summary)}"
    )
    assert summary["rows"] == PARSED_ROWS
    assert summary["distinct_hours"] == PARSED_DISTINCT_HOURS
    assert summary["start"] == "2026-09-01T00:52:00Z", (
        f"start must be an ISO-8601 Z string; got {summary['start']!r}"
    )
    assert summary["end"] == "2026-09-03T23:52:00Z", (
        f"end must be an ISO-8601 Z string; got {summary['end']!r}"
    )
    for key in ("start", "end"):
        assert isinstance(summary[key], str) and summary[key].endswith("Z"), (
            f"coverage.json needs ISO-8601 'Z' strings, not Timestamps; {key}={summary[key]!r}"
        )
        assert "+00:00" not in summary[key], (
            f"use a 'Z' suffix rather than '+00:00'; {key}={summary[key]!r}"
        )


def test_obs_summary_is_side_effect_free(parsed: pd.DataFrame) -> None:
    before = parsed.copy(deep=True)
    obs.obs_summary(parsed)
    pd.testing.assert_frame_equal(parsed, before)


def test_obs_summary_on_an_empty_frame() -> None:
    summary = obs.obs_summary(obs.parse_iem_csv("station,valid,tmpf\nOMA,2026-09-01 00:52,M\n"))
    assert summary == {"rows": 0, "distinct_hours": 0, "start": None, "end": None}


# --- 13. parquet round trip ---------------------------------------------------------------


def test_write_obs_round_trips_as_obs_schema_with_off_hour_minutes(tmp_path: Path) -> None:
    """The written file must be exactly OBS_SCHEMA, and `:52` must survive the round trip."""
    frame = synthetic_obs(800, timedelta(hours=800), minute_offset=52)
    assert obs.distinct_hours(frame) == 800

    out = obs.write_obs(frame, tmp_path / "obs.parquet", min_rows=700, min_distinct_hours=700)
    assert out.exists(), f"write_obs returned {out} but wrote nothing"

    table = pq.read_table(out)
    assert table.schema.equals(OBS_SCHEMA), (
        f"SPEC §6: obs.parquet must be exactly OBS_SCHEMA\n  expected: {OBS_SCHEMA}\n"
        f"  got:      {table.schema}"
    )
    assert table.num_rows == 800

    back = table.to_pandas()
    minutes = set(back["valid_time"].dt.minute.tolist())
    assert minutes == {52}, (
        f"spike F5: the off-hour minute must survive the parquet round trip; got {minutes}. "
        "A file that reads back on the hour matches nothing in T5's ±30 min join."
    )
    assert obs.distinct_hours(back) == 800
