"""F9 Stream 1 — the ledger contract, the pure scorecard, and the purity boundary itself.

Hermetic. No network, no server process, no writes outside ``tmp_path``, and nothing here
reads ``data/forecast_ledger.jsonl``: every ledger under test is either built in a temp
directory by this file or read from ``tests/fixtures/scorecard/``.

What these tests are actually defending
---------------------------------------

1. **The ledger cannot shrink.** ``forecast/scorecard.py`` is scanned for every way a file
   gets shortened — a truncating ``open`` mode, ``write_text``/``write_bytes``, a
   ``truncate`` call, an atomic replace. A scan that never fires is worthless, so each
   pattern is re-run against a deliberately corrupted copy of the source and has to fire
   there. Atomic replace is right for ``data/forecast.json`` and wrong here: replacing a
   file *is* discarding what it held.

2. **:func:`forecast.scorecard.scorecard` is pure.** Same rows in, byte-identical JSON out.
   The source of every function it depends on — the module enumerates them in
   ``PURE_FUNCTION_NAMES`` — is scanned for a clock, a path, a file handle or an HTTP
   client, again with a positive control. Purity is what lets one number be computed once
   and shown identically by the CLI and by the page.

3. **A statistic never appears without its denominator, and never over an empty sample.**
   A mean over zero rows is ``None``, never ``0.0``: an empty join scores perfectly and is
   fake (SPEC §10). Gap rows are excluded from every mean and counted separately.

4. **The blend's losses survive.** Nothing here demands a win. The synthetic fixture is
   built to make the blend lose three cycles in a row on purpose, and the streak counters
   are pinned with those losses in them.

What these tests do NOT cover
-----------------------------

The record and grade passes (Stream 2), the endpoint (Stream 3) and the renderer
(Stream 5). This module tests the contract those three meet at, and nothing else.
"""

from __future__ import annotations

import io
import json
import re
import threading
import tokenize
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecast import scorecard as sc

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / "forecast" / "scorecard.py"
FIXTURE = REPO / "tests" / "fixtures" / "scorecard" / "winning.synthetic.jsonl"

NOW = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
WEIGHTS_WINDOW = {"start": "2026-08-04T12:00:00Z", "end": "2026-09-04T00:00:00Z", "days": 30}


# --- source-scanning helpers (shared by every guard below) -------------------------------


def _drop(source: str, kinds: set[int]) -> str:
    """``source`` with the given token kinds removed, joined for scanning.

    Reconstruction is *not* valid Python — it is a token soup for regex scanning — so
    every pattern in this file tolerates whitespace between tokens.
    """
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in kinds:
            continue
        if token.string:
            kept.append(token.string)
    return " ".join(kept)


def _no_comments(source: str) -> str:
    """Comments removed, string literals **kept** — a file mode lives inside a literal."""
    return _drop(source, {tokenize.COMMENT})


def _code_only(source: str) -> str:
    """Comments *and* literals removed — prose about smoothing is not smoothing."""
    kinds = {tokenize.COMMENT, tokenize.STRING}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, name):
            kinds.add(getattr(tokenize, name))
    return _drop(source, kinds)


def _module_source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


#: Every way a file gets shorter. Each one has a firing sample below it.
TRUNCATING_PATTERNS = {
    "truncating open mode": (
        r"open\s*\(\s*[^)]*?['\"](?:w|wb|wt|w\+|x|xb)['\"]",
        'open(target, "w")',
    ),
    "write_text": (r"\bwrite_text\b", 'target.write_text("x")'),
    "write_bytes": (r"\bwrite_bytes\b", 'target.write_bytes(b"x")'),
    "truncate": (r"\.\s*truncate\s*\(", "handle.truncate(0)"),
    "os.replace": (r"\bos\s*\.\s*replace\b", "os.replace(tmp, target)"),
    "atomic replace helper": (r"\bwrite_atomic\b", "write_atomic(target, doc)"),
}

#: Every clock, path, handle or client that would make the pure layer non-reproducible.
IMPURE_PATTERNS = {
    "datetime.now": (r"datetime\s*\.\s*now\b", "stamp = datetime.now(timezone.utc)"),
    "utcnow": (r"\butcnow\b", "stamp = datetime.utcnow()"),
    "time.time": (r"\btime\s*\.\s*time\b", "started = time.time()"),
    "time.monotonic": (r"\btime\s*\.\s*monotonic\b", "started = time.monotonic()"),
    "open": (r"\bopen\s*\(", 'handle = open(source)'),
    "Path": (r"\bPath\s*\(", 'here = Path("data")'),
    "requests": (r"\brequests\b", "requests.get(url)"),
}

#: Smoothing a six-cycle record manufactures a trend that is not in it.
SMOOTHING_PATTERNS = {
    "rolling": (r"\.\s*rolling\s*\(", "frame.rolling(3)"),
    "ewm": (r"\.\s*ewm\s*\(", "frame.ewm(span=3)"),
    "resample": (r"\.\s*resample\s*\(", 'frame.resample("h")'),
    "interpolate": (r"\.\s*interpolate\s*\(", "frame.interpolate()"),
    "ffill": (r"\.\s*ffill\s*\(", "frame.ffill()"),
    "bfill": (r"\.\s*bfill\s*\(", "frame.bfill()"),
    "fillna": (r"\.\s*fillna\s*\(", "frame.fillna(0)"),
    "moving average helper": (r"moving_average|movingAverage", "moving_average(values, 3)"),
    "smoothing helper": (r"\bsmooth\w*\s*\(", "smoothed(values)"),
}


def _fires(patterns: dict, key: str, text: str) -> bool:
    return re.search(patterns[key][0], text) is not None


# --- the contract shapes ------------------------------------------------------------------


def test_the_ledger_row_field_tuples_are_the_locked_contract() -> None:
    """The two row shapes are frozen here so a silent reorder is a red test, not a surprise."""
    assert sc.PREDICTION_FIELDS == (
        "kind", "init_time", "run_label", "valid_time", "lead_h", "series", "series_kind",
        "forecast_f", "weights_fitted_at_lead_h", "is_extrapolated_lead",
        "source_generated_at", "recorded_at",
    )
    assert sc.GRADE_FIELDS == (
        "kind", "init_time", "valid_time", "lead_h", "series", "status", "observed_f",
        "obs_offset_min", "error_f", "abs_error_f", "reason", "obs_source", "tolerance_min",
        "graded_at",
    )
    assert sc.IDENTITY_FIELDS == ("kind", "init_time", "valid_time", "lead_h", "series")


def test_the_join_tolerance_is_derived_not_retyped() -> None:
    """`tolerance_min` is the join's own window, so the printed number cannot drift from it."""
    from score.join import TOLERANCE

    assert sc.TOLERANCE_MIN == int(TOLERANCE.total_seconds() // 60) == 30


def test_the_tunables_are_the_ones_the_plan_locked() -> None:
    assert sc.HTTP_TIMEOUT == (3.05, 5.0)
    assert sc.GRADE_DEADLINE_S == 6.0
    assert sc.GAP_GRACE_H == 3
    assert sc.MAX_OBS_WINDOW_DAYS == 7
    assert sc.OBS_SOURCE == "iem_asos_OMA"
    assert isinstance(sc.MIN_CYCLES_FOR_ENOUGH, int) and sc.MIN_CYCLES_FOR_ENOUGH > 0
    assert sc.LEDGER_PATH == REPO / "data" / "forecast_ledger.jsonl"
    assert sc.FORECAST_PATH == REPO / "data" / "forecast.json"


def test_the_module_carries_no_bare_assert() -> None:
    """`python -O` deletes assertions, and this module decides what the page claims."""
    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(_module_source().splitlines(), start=1)
        if re.search(r"(^|[^\w.])assert\s", line)
    ]
    assert offenders == [], f"bare assertions in forecast/scorecard.py: {offenders}"


def test_the_docstring_states_the_three_layers_and_the_purity_boundary() -> None:
    """The docstring is the contract with the next reader (F6/F7 precedent)."""
    doc = sc.__doc__ or ""
    for phrase in ("ledger", "impure", "pure", "purity boundary", "append-only"):
        assert phrase in doc.lower(), f"the module docstring never mentions {phrase!r}"
    for key in ("models_included", "lead_hours"):
        assert key in doc, f"the locked meta key {key!r} is not stated in the docstring"


# --- the row builders ----------------------------------------------------------------------


def _prediction(**overrides) -> dict:
    kwargs = {
        "init_time": "2026-09-01T00:00:00Z",
        "run_label": "00z",
        "valid_time": "2026-09-01T03:00:00Z",
        "lead_h": 3,
        "series": "HRRR",
        "series_kind": "model",
        "forecast_f": 71.5,
        "weights_fitted_at_lead_h": 6,
        "is_extrapolated_lead": False,
        "source_generated_at": "2026-09-01T08:00:00Z",
        "recorded_at": "2026-09-01T08:01:00Z",
    }
    kwargs.update(overrides)
    return sc.make_prediction_row(**kwargs)


def _grade(**overrides) -> dict:
    kwargs = {
        "init_time": "2026-09-01T00:00:00Z",
        "valid_time": "2026-09-01T03:00:00Z",
        "lead_h": 3,
        "series": "HRRR",
        "status": "graded",
        "observed_f": 70.0,
        "obs_offset_min": -8,
        "error_f": 1.5,
        "graded_at": "2026-09-01T04:00:00Z",
    }
    kwargs.update(overrides)
    return sc.make_grade_row(**kwargs)


def test_a_prediction_row_carries_every_key_in_order_including_the_absent_ones() -> None:
    full = _prediction()
    assert list(full) == list(sc.PREDICTION_FIELDS)
    sparse = _prediction(run_label=None, weights_fitted_at_lead_h=None, is_extrapolated_lead=None)
    assert list(sparse) == list(sc.PREDICTION_FIELDS)
    assert sparse["run_label"] is None
    assert sparse["weights_fitted_at_lead_h"] is None
    assert sparse["is_extrapolated_lead"] is None


def test_a_grade_row_carries_every_key_in_order_on_both_statuses() -> None:
    graded = _grade()
    assert list(graded) == list(sc.GRADE_FIELDS)
    assert graded["abs_error_f"] == 1.5
    gap = _grade(status="gap", observed_f=None, obs_offset_min=None, error_f=None,
                 reason="no reading within the match window")
    assert list(gap) == list(sc.GRADE_FIELDS)
    assert [gap["observed_f"], gap["obs_offset_min"], gap["error_f"], gap["abs_error_f"]] == [
        None, None, None, None
    ]
    assert gap["reason"]


def test_a_gap_must_state_a_reason_and_carry_no_numbers() -> None:
    with pytest.raises(sc.ScorecardError, match="non-empty reason"):
        _grade(status="gap", observed_f=None, obs_offset_min=None, error_f=None, reason=None)
    with pytest.raises(sc.ScorecardError, match="carries no observed_f"):
        _grade(status="gap", obs_offset_min=None, error_f=None, reason="hole")


def test_a_graded_row_without_its_observation_is_refused() -> None:
    with pytest.raises(sc.ScorecardError, match="must carry observed_f"):
        _grade(observed_f=None)
    with pytest.raises(sc.ScorecardError, match="must carry observed_f"):
        _grade(error_f=None)


def test_an_abs_error_that_disagrees_with_the_signed_error_is_refused() -> None:
    with pytest.raises(sc.ScorecardError, match="disagrees with"):
        _grade(error_f=-1.5, abs_error_f=2.5)
    assert _grade(error_f=-1.5, abs_error_f=1.5)["abs_error_f"] == 1.5


def test_an_observation_outside_the_join_window_is_refused() -> None:
    with pytest.raises(sc.ScorecardError, match="outside the"):
        _grade(obs_offset_min=-31)
    assert _grade(obs_offset_min=-30)["obs_offset_min"] == -30


def test_an_unknown_status_or_series_kind_is_refused() -> None:
    with pytest.raises(sc.ScorecardError, match="status must be"):
        _grade(status="pending")
    with pytest.raises(sc.ScorecardError, match="series_kind must be"):
        _prediction(series_kind="ensemble")
    with pytest.raises(sc.ScorecardError, match="the blend series is named"):
        _prediction(series="HRRR", series_kind="blend")
    with pytest.raises(sc.ScorecardError, match="may not be recorded as a model"):
        _prediction(series="BLEND", series_kind="model")


def test_stamps_are_iso_8601_with_a_trailing_z_never_an_offset() -> None:
    row = _prediction(
        init_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        valid_time=datetime(2026, 9, 1, 3, tzinfo=timezone.utc),
        source_generated_at=datetime(2026, 9, 1, 8),  # naive -> UTC, never local
        recorded_at=datetime(2026, 9, 1, 8, 1, tzinfo=timezone.utc),
    )
    for field in ("init_time", "valid_time", "source_generated_at", "recorded_at"):
        assert row[field].endswith("Z"), field
        assert "+00:00" not in row[field], field
    assert row["source_generated_at"] == "2026-09-01T08:00:00Z"


def test_row_identity_and_its_two_narrower_views() -> None:
    prediction = _prediction()
    grade = _grade()
    assert sc.row_identity(prediction) == (
        "prediction", "2026-09-01T00:00:00Z", "2026-09-01T03:00:00Z", 3, "HRRR"
    )
    assert sc.row_identity(grade)[0] == "grade"
    assert sc.series_identity(prediction) == sc.series_identity(grade)
    assert sc.step_identity(prediction) == ("2026-09-01T00:00:00Z", "2026-09-01T03:00:00Z", 3)
    with pytest.raises(sc.ScorecardError, match="missing identity field"):
        sc.row_identity({"kind": "prediction"})


# --- (a) append-only ledger I/O -------------------------------------------------------------


def test_a_missing_ledger_is_an_empty_ledger_not_an_error(tmp_path: Path) -> None:
    assert sc.load_ledger(tmp_path / "nothing" / "forecast_ledger.jsonl") == []


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    target = tmp_path / "ledger.jsonl"
    target.write_text(
        "\n" + json.dumps(_prediction()) + "\n\n   \n" + json.dumps(_grade()) + "\n",
        encoding="utf-8",
    )
    assert [row["kind"] for row in sc.load_ledger(target)] == ["prediction", "grade"]


def test_a_crash_truncated_final_line_loses_only_itself(tmp_path: Path) -> None:
    """A half-written line is a normal consequence of killing the process."""
    target = tmp_path / "ledger.jsonl"
    good = [_prediction(lead_h=lead, valid_time=f"2026-09-01T{lead:02d}:00:00Z") for lead in (3, 6)]
    with open(target, "a", encoding="utf-8") as handle:
        for row in good:
            handle.write(json.dumps(row) + "\n")
        handle.write('{"kind":"gra')
    loaded = sc.load_ledger(target)
    assert len(loaded) == 2
    assert [row["lead_h"] for row in loaded] == [3, 6]


def test_a_row_that_cannot_be_identified_is_skipped_not_raised_on(tmp_path: Path) -> None:
    target = tmp_path / "ledger.jsonl"
    target.write_text(
        json.dumps({"kind": "prediction"}) + "\n"
        + json.dumps([1, 2, 3]) + "\n"
        + json.dumps(_grade()) + "\n",
        encoding="utf-8",
    )
    assert [row["kind"] for row in sc.load_ledger(target)] == ["grade"]


def test_append_ledger_creates_its_directory_and_appends_whole_lines(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "deeper" / "ledger.jsonl"
    sc.append_ledger(target, _prediction())
    sc.append_ledger(target, _grade())
    assert target.read_text(encoding="utf-8").count("\n") == 2
    assert len(sc.load_ledger(target)) == 2


@pytest.mark.parametrize("name", sorted(TRUNCATING_PATTERNS))
def test_the_module_contains_no_way_to_shorten_the_ledger(name: str) -> None:
    """The append-only claim, scanned — **with the positive control beside it**.

    A scan that cannot fire proves nothing, so each pattern is re-run against a copy of the
    real source with the offending call spliced in and has to fire there.
    """
    source = _no_comments(_module_source())
    assert not _fires(TRUNCATING_PATTERNS, name, source), (
        f"forecast/scorecard.py contains a {name}; the ledger is append-only and an atomic "
        f"replace is truncation by another name"
    )
    injected = _no_comments(_module_source() + "\n\ndef _oops(target, doc, tmp, os):\n    "
                            + TRUNCATING_PATTERNS[name][1] + "\n")
    assert _fires(TRUNCATING_PATTERNS, name, injected), (
        f"the {name} scanner never fires, so it was proving nothing"
    )


def test_the_injected_controls_leave_the_real_module_byte_identical() -> None:
    before = MODULE_PATH.read_bytes()
    for pattern, sample in TRUNCATING_PATTERNS.values():
        re.search(pattern, sample)
    assert MODULE_PATH.read_bytes() == before


def _first_wins(rows: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for row in rows:
        seen.setdefault(sc.row_identity(row), row)
    return list(seen.values())


def _latest_wins(rows: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for row in rows:
        seen[sc.row_identity(row)] = row
    return list(seen.values())


def test_latest_wins_and_first_wins_agree_on_a_writer_produced_ledger(tmp_path: Path) -> None:
    """The writer refuses a second line per identity, so the two read rules cannot diverge."""
    target = tmp_path / "ledger.jsonl"
    written: list[dict] = []
    for lead in (3, 6, 9):
        for series in ("HRRR", "BLEND"):
            for row in (
                _prediction(lead_h=lead, series=series,
                            series_kind="blend" if series == "BLEND" else "model",
                            valid_time=f"2026-09-01T{lead:02d}:00:00Z"),
                _grade(lead_h=lead, series=series, valid_time=f"2026-09-01T{lead:02d}:00:00Z"),
            ):
                # the write-side guard both passes use
                if sc.has_identity(written, sc.row_identity(row)):
                    continue
                sc.append_ledger(target, row)
                written.append(row)
    rows = sc.load_ledger(target)
    assert len(rows) == 12
    assert sc.dedupe(rows) == rows == _first_wins(rows) == _latest_wins(rows)


def test_the_two_read_rules_diverge_only_on_a_ledger_no_writer_produces(tmp_path: Path) -> None:
    """The positive control: the rules really are different rules, and dedupe picks correctly."""
    target = tmp_path / "ledger.jsonl"
    sc.append_ledger(target, _prediction(forecast_f=71.5))
    sc.append_ledger(target, _grade(error_f=1.5))
    sc.append_ledger(target, _prediction(forecast_f=99.0))     # a re-stated prediction
    sc.append_ledger(target, _grade(error_f=-9.0))             # an attempt to re-grade
    rows = sc.load_ledger(target)
    assert _first_wins(rows) != _latest_wins(rows)
    deduped = sc.dedupe(rows)
    assert len(deduped) == 2
    prediction = next(row for row in deduped if row["kind"] == "prediction")
    grade = next(row for row in deduped if row["kind"] == "grade")
    assert prediction["forecast_f"] == 99.0, "latest-wins for a prediction"
    assert grade["error_f"] == 1.5, "first-wins for a grade — an outcome is never re-graded"


def test_has_identity_is_the_write_side_guard() -> None:
    rows = [_prediction(), _grade()]
    assert sc.has_identity(rows, sc.row_identity(_prediction()))
    assert sc.has_identity(rows, sc.row_identity(_grade()))
    assert not sc.has_identity(rows, ("prediction", "2026-09-09T00:00:00Z", "x", 3, "HRRR"))


def test_concurrent_appends_never_interleave_a_line(tmp_path: Path) -> None:
    """Eight writers, four hundred lines, every one of them a whole parseable object."""
    target = tmp_path / "ledger.jsonl"
    errors: list[BaseException] = []

    def worker(worker_id: int) -> None:
        try:
            for index in range(50):
                sc.append_ledger(
                    target,
                    _prediction(
                        lead_h=index,
                        series=f"M{worker_id}",
                        valid_time=f"2026-09-01T{index:02d}:00:00Z",
                        # a long payload makes a partial write far likelier to show up
                        run_label="z" * 400,
                    ),
                )
        except BaseException as exc:  # pragma: no cover - reported, never swallowed
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 400
    parsed = [json.loads(line) for line in lines]  # raises if any line was interleaved
    assert len({sc.row_identity(row) for row in parsed}) == 400


# --- streaks -------------------------------------------------------------------------------


def _cycles(*pairs) -> list[dict]:
    return [{"blend_mae_f": blend, "best_single_mae_f": best} for blend, best in pairs]


@pytest.mark.parametrize(
    "cycles,expected",
    [
        pytest.param([], {"n_cycles_scored": 0, "current_beaten_cycles": 0,
                          "longest_beaten_cycles": 0, "current_won_cycles": 0,
                          "longest_won_cycles": 0}, id="empty"),
        pytest.param(_cycles((1.0, 2.0), (1.0, 2.0), (1.0, 2.0)),
                     {"n_cycles_scored": 3, "current_beaten_cycles": 0,
                      "longest_beaten_cycles": 0, "current_won_cycles": 3,
                      "longest_won_cycles": 3}, id="three-wins"),
        pytest.param(_cycles((2.0, 1.0), (2.0, 1.0)),
                     {"n_cycles_scored": 2, "current_beaten_cycles": 2,
                      "longest_beaten_cycles": 2, "current_won_cycles": 0,
                      "longest_won_cycles": 0}, id="two-losses"),
        pytest.param(_cycles((1.0, 1.0), (1.0, 1.0)),
                     {"n_cycles_scored": 2, "current_beaten_cycles": 0,
                      "longest_beaten_cycles": 0, "current_won_cycles": 0,
                      "longest_won_cycles": 0}, id="a-tie-is-neither"),
        pytest.param(_cycles((1.0, 2.0), (1.0, 2.0), (1.0, 1.0), (1.0, 2.0)),
                     {"n_cycles_scored": 4, "current_beaten_cycles": 0,
                      "longest_beaten_cycles": 0, "current_won_cycles": 1,
                      "longest_won_cycles": 2}, id="a-tie-breaks-a-winning-run"),
        pytest.param(_cycles((2.0, 1.0), (2.0, 1.0), (2.0, 1.0), (1.0, 2.0)),
                     {"n_cycles_scored": 4, "current_beaten_cycles": 0,
                      "longest_beaten_cycles": 3, "current_won_cycles": 1,
                      "longest_won_cycles": 1}, id="current-and-longest-diverge"),
        pytest.param(_cycles((1.0, 2.0), (None, 2.0), (1.0, 2.0)),
                     {"n_cycles_scored": 2, "current_beaten_cycles": 0,
                      "longest_beaten_cycles": 0, "current_won_cycles": 1,
                      "longest_won_cycles": 1}, id="an-unscored-cycle-breaks-the-run"),
    ],
)
def test_streaks_over_a_win_loss_tie_table(cycles, expected) -> None:
    assert sc.streaks(cycles) == expected


# --- (c) the pure scorecard -----------------------------------------------------------------


@pytest.fixture()
def fixture_rows() -> list[dict]:
    return sc.load_ledger(FIXTURE)


@pytest.fixture()
def fixture_meta(fixture_rows) -> dict:
    return sc.ledger_meta(fixture_rows, weights_fitted_window=WEIGHTS_WINDOW)


@pytest.fixture()
def fixture_payload(fixture_rows, fixture_meta) -> dict:
    return sc.scorecard(fixture_rows, NOW, meta=fixture_meta)


def test_ledger_meta_derives_the_member_list_from_the_ledger_itself(fixture_rows) -> None:
    """A fresh clone has no §9 payload, so the member list has to come from the record."""
    meta = sc.ledger_meta(fixture_rows)
    assert meta["models_included"] == ["HRRR", "GFS", "NAM", "NBM"]
    assert meta["never_interpolated"] is True
    assert meta["obs_source"] == sc.OBS_SOURCE
    assert meta["tolerance_min"] == 30
    assert meta["weights_fitted_window"] is None, "no payload, no fitting window invented"
    assert sc.ledger_meta([])["models_included"] == []


def test_the_scorecard_is_reproducible_to_the_byte(fixture_rows, fixture_meta) -> None:
    first = sc.scorecard(fixture_rows, NOW, meta=fixture_meta)
    second = sc.scorecard(fixture_rows, NOW, meta=fixture_meta)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_scorecard_is_unaffected_by_a_broken_network(
    monkeypatch, fixture_rows, fixture_meta
) -> None:
    import requests

    def explode(*args, **kwargs):
        raise AssertionError("the pure layer must never reach the network")

    monkeypatch.setattr(requests, "get", explode)
    monkeypatch.setattr(requests, "post", explode, raising=False)
    payload = sc.scorecard(fixture_rows, NOW, meta=fixture_meta)
    assert payload["meta"]["counts"]["graded"] == 84


@pytest.mark.parametrize("name", sorted(IMPURE_PATTERNS))
def test_no_pure_function_touches_a_clock_a_path_or_the_network(name: str) -> None:
    """The purity boundary, scanned function by function, control included."""
    import inspect

    for function_name in sc.PURE_FUNCTION_NAMES:
        body = _no_comments(inspect.getsource(getattr(sc, function_name)))
        assert not _fires(IMPURE_PATTERNS, name, body), (
            f"forecast.scorecard.{function_name} references {name}; it sits below the purity "
            f"boundary and must read nothing but its arguments"
        )
    control = _no_comments(
        inspect.getsource(sc.scorecard).rstrip()
        + "\n    " + IMPURE_PATTERNS[name][1] + "\n"
    )
    assert _fires(IMPURE_PATTERNS, name, control), (
        f"the {name} scanner never fires, so it was proving nothing"
    )


def test_pure_function_names_actually_covers_what_scorecard_calls() -> None:
    """A helper added without registering it here would slip under an unscanned name."""
    import inspect

    registered = set(sc.PURE_FUNCTION_NAMES)
    for function_name in sc.PURE_FUNCTION_NAMES:
        assert hasattr(sc, function_name), function_name
    called = set(re.findall(r"\b(_?[a-z][a-z0-9_]*)\s*\(", inspect.getsource(sc.scorecard)))
    module_level = {
        name for name in called
        if callable(getattr(sc, name, None)) and getattr(sc, name).__module__ == sc.__name__
    }
    assert module_level <= registered, (
        f"scorecard() calls unregistered module functions: {sorted(module_level - registered)}"
    )


@pytest.mark.parametrize("name", sorted(SMOOTHING_PATTERNS))
def test_the_module_smooths_nothing(name: str) -> None:
    """Six cycles is not a series. A rolling mean over it invents a trend."""
    source = _code_only(_module_source())
    assert not _fires(SMOOTHING_PATTERNS, name, source), (
        f"forecast/scorecard.py smooths via {name}; the record is short and every published "
        f"mean is a plain mean over a stated denominator"
    )
    control = _code_only("def _oops(frame, values, moving_average, smoothed):\n    "
                         + SMOOTHING_PATTERNS[name][1] + "\n")
    assert _fires(SMOOTHING_PATTERNS, name, control), (
        f"the {name} scanner never fires, so it was proving nothing"
    )


def test_scorecard_refuses_a_static_meta_block_it_was_not_handed() -> None:
    with pytest.raises(sc.ScorecardError, match="invents nothing"):
        sc.scorecard([], NOW, meta={"site": {}, "variable": "x"})


def test_an_empty_ledger_is_the_honest_empty_state() -> None:
    payload = sc.scorecard([], NOW, meta=sc.ledger_meta([]))
    sc.validate_scorecard(payload)
    assert payload["enough"] is False
    assert payload["not_enough_reason"] == "not enough days yet, 0 recorded"
    assert payload["by_series"] == payload["by_lead"] == payload["by_cycle"] == []
    assert payload["skips"] == []
    assert payload["meta"]["counts"] == {
        "cycles_recorded": 0, "rows_recorded": 0, "graded": 0, "pending": 0, "gap": 0,
        "rows_outside_grading_window": 0,
    }
    assert payload["meta"]["window"] == {
        "first_init_time": None, "last_init_time": None, "days_recorded": 0
    }


def test_a_statistic_over_no_rows_is_null_never_zero() -> None:
    """An empty join scores perfectly and is fake (SPEC §10)."""
    rows = [_prediction(series=name, series_kind="blend" if name == "BLEND" else "model")
            for name in ("HRRR", "BLEND")]
    payload = sc.scorecard(rows, NOW, meta=sc.ledger_meta(rows))
    sc.validate_scorecard(payload)
    for entry in payload["by_series"]:
        assert entry["n"] == 0
        assert entry["mae_f"] is None and entry["bias_f"] is None
    assert payload["by_lead"][0]["blend_mae_f"] is None
    assert payload["by_lead"][0]["blend_beaten"] is None
    assert payload["by_cycle"][0]["blend_mae_f"] is None
    assert payload["skips"] == [], "nothing was graded, so nothing was excluded"


def test_gap_rows_are_excluded_from_every_mean_and_counted_separately() -> None:
    rows = [
        _prediction(series="HRRR", forecast_f=72.0),
        _grade(series="HRRR", error_f=2.0),
        _prediction(series="BLEND", series_kind="blend", forecast_f=99.0),
        _grade(series="BLEND", status="gap", observed_f=None, obs_offset_min=None,
               error_f=None, reason="no reading within the match window"),
    ]
    payload = sc.scorecard(rows, NOW, meta=sc.ledger_meta(rows))
    sc.validate_scorecard(payload)
    blend = next(e for e in payload["by_series"] if e["series"] == "BLEND")
    hrrr = next(e for e in payload["by_series"] if e["series"] == "HRRR")
    assert blend == {"series": "BLEND", "series_kind": "blend", "mae_f": None, "bias_f": None,
                     "n": 0}
    assert hrrr["n"] == 1 and hrrr["mae_f"] == 2.0
    assert payload["meta"]["counts"]["gap"] == 1
    assert payload["meta"]["counts"]["graded"] == 1
    assert payload["by_cycle"][0]["n_gap"] == 1
    assert payload["skips"][0]["n_rows"] == 1, "the graded HRRR row could not be compared"


def test_a_pending_row_past_the_window_cap_is_counted_not_lost() -> None:
    rows = [_prediction()]
    fresh = sc.scorecard(rows, NOW, meta=sc.ledger_meta(rows))
    assert fresh["meta"]["counts"]["pending"] == 1
    assert fresh["meta"]["counts"]["rows_outside_grading_window"] == 0
    stale = sc.scorecard(
        rows, NOW + timedelta(days=sc.MAX_OBS_WINDOW_DAYS + 1), meta=sc.ledger_meta(rows)
    )
    assert stale["meta"]["counts"]["pending"] == 1
    assert stale["meta"]["counts"]["rows_outside_grading_window"] == 1


def test_enough_flips_only_once_the_record_is_long_enough(fixture_rows, fixture_meta) -> None:
    thin = sc.scorecard(fixture_rows, NOW, meta=fixture_meta)
    assert thin["enough"] is False
    assert thin["not_enough_reason"] == "not enough days yet, 6 recorded"
    assert thin["meta"]["counts"]["cycles_recorded"] == 6


def test_the_locked_meta_key_set_is_exactly_what_stream_5_codes_against(
    fixture_payload,
) -> None:
    """Changing this list is a contract change for the endpoint, the CLI and the renderer."""
    assert list(fixture_payload) == [
        "meta", "enough", "not_enough_reason", "by_series", "by_lead", "by_cycle", "skips",
        "streaks",
    ]
    assert set(fixture_payload["meta"]) == {
        "generated_at", "site", "variable", "units", "obs_source", "tolerance_min",
        "never_interpolated", "models_included", "lead_hours", "counts", "window",
        "weights_fitted_window",
    }
    assert fixture_payload["meta"]["models_included"] == ["HRRR", "GFS", "NAM", "NBM"]
    assert fixture_payload["meta"]["lead_hours"] == [3, 6, 9]
    assert fixture_payload["meta"]["generated_at"] == "2026-09-02T18:00:00Z"
    assert fixture_payload["meta"]["weights_fitted_window"] == WEIGHTS_WINDOW


def test_the_comparison_is_taken_over_the_same_steps_or_not_at_all(fixture_payload) -> None:
    """The gap cycle: the blend and its members are compared on the twelve shared steps."""
    cycle = next(c for c in fixture_payload["by_cycle"]
                 if c["init_time"] == "2026-09-01T12:00:00Z")
    assert cycle["n_gap"] == 1
    assert cycle["n_graded"] == 14
    assert (cycle["blend_mae_f"], cycle["best_single_mae_f"]) == (1.75, 0.75)
    assert cycle["blend_beaten"] is True
    skip = next(s for s in fixture_payload["skips"] if s["init_time"] == cycle["init_time"])
    assert skip["n_rows"] == 4
    assert "same steps" in skip["reason"]


def test_a_cycle_whose_leads_are_simply_ungraded_states_no_false_skip(fixture_payload) -> None:
    cycle = next(c for c in fixture_payload["by_cycle"]
                 if c["init_time"] == "2026-09-02T00:00:00Z")
    assert (cycle["n_graded"], cycle["n_pending"], cycle["n_gap"]) == (10, 5, 0)
    assert [s["init_time"] for s in fixture_payload["skips"]] == ["2026-09-01T12:00:00Z"]


# --- the validator ---------------------------------------------------------------------------


def test_the_fixture_payload_validates_unchanged(fixture_payload) -> None:
    before = json.dumps(fixture_payload, sort_keys=True)
    assert sc.validate_scorecard(fixture_payload) is fixture_payload
    assert json.dumps(fixture_payload, sort_keys=True) == before


def test_scorecard_error_is_a_contract_error() -> None:
    """One `except ContractError` clause covers results.json, forecast.json and this."""
    from backend.contract import ContractError

    assert issubclass(sc.ScorecardError, ContractError)


@pytest.mark.parametrize("banned", sorted(__import__(
    "forecast.contract", fromlist=["BANNED_FIELD_NAMES"]).BANNED_FIELD_NAMES))
@pytest.mark.parametrize("where", ["top", "meta", "meta.counts", "by_series[0]", "streaks"])
def test_a_banned_field_name_is_rejected_at_any_depth(fixture_payload, banned, where) -> None:
    """FORECAST-SPEC §6.2, eleven names, five depths — the scorecard states the past tense."""
    target = fixture_payload
    for step in where.split("."):
        if step == "top":
            break
        if step.endswith("]"):
            key, index = step[:-1].split("[")
            target = target[key][int(index)]
        else:
            target = target[step]
    target[banned] = 0.9
    with pytest.raises(sc.ScorecardError, match="banned outright"):
        sc.validate_scorecard(fixture_payload)


def test_an_unexpected_or_missing_key_is_rejected(fixture_payload) -> None:
    fixture_payload["surprise"] = 1
    with pytest.raises(sc.ScorecardError, match="expected exactly"):
        sc.validate_scorecard(fixture_payload)
    del fixture_payload["surprise"]
    del fixture_payload["skips"]
    with pytest.raises(sc.ScorecardError, match="expected exactly"):
        sc.validate_scorecard(fixture_payload)


def test_a_statistic_of_zero_over_no_rows_is_rejected(fixture_payload) -> None:
    """`0.0` over `n=0` is the fake-perfect-score bug, spelled out."""
    fixture_payload["by_series"].append(
        {"series": "GHOST", "series_kind": "model", "mae_f": 0.0, "bias_f": None, "n": 0}
    )
    with pytest.raises(sc.ScorecardError, match="never a number"):
        sc.validate_scorecard(fixture_payload)


def test_a_negative_or_non_integer_denominator_is_rejected(fixture_payload) -> None:
    fixture_payload["by_series"][0]["n"] = -1
    with pytest.raises(sc.ScorecardError, match="non-negative"):
        sc.validate_scorecard(fixture_payload)
    fixture_payload["by_series"][0]["n"] = 1.5
    with pytest.raises(sc.ScorecardError, match="plain non-negative int"):
        sc.validate_scorecard(fixture_payload)


def test_a_non_finite_statistic_is_rejected(fixture_payload) -> None:
    fixture_payload["by_series"][0]["mae_f"] = float("inf")
    with pytest.raises(sc.ScorecardError, match="not a finite number"):
        sc.validate_scorecard(fixture_payload)


def test_a_verdict_that_disagrees_with_its_own_means_is_rejected(fixture_payload) -> None:
    entry = fixture_payload["by_cycle"][0]
    entry["blend_beaten"] = not entry["blend_beaten"]
    with pytest.raises(sc.ScorecardError, match="says otherwise"):
        sc.validate_scorecard(fixture_payload)


def test_a_verdict_without_two_means_behind_it_is_rejected(fixture_payload) -> None:
    entry = fixture_payload["by_cycle"][0]
    entry["blend_mae_f"] = None
    with pytest.raises(sc.ScorecardError, match="must be null where no comparison"):
        sc.validate_scorecard(fixture_payload)


def test_a_thin_record_that_does_not_say_so_is_rejected(fixture_payload) -> None:
    fixture_payload["not_enough_reason"] = None
    with pytest.raises(sc.ScorecardError, match="must state the count"):
        sc.validate_scorecard(fixture_payload)


def test_never_interpolated_cannot_be_switched_off(fixture_payload) -> None:
    fixture_payload["meta"]["never_interpolated"] = False
    with pytest.raises(sc.ScorecardError, match="never_interpolated must be true"):
        sc.validate_scorecard(fixture_payload)


def test_a_skip_without_a_stated_reason_is_rejected(fixture_payload) -> None:
    fixture_payload["skips"][0]["reason"] = "  "
    with pytest.raises(sc.ScorecardError, match="non-empty sentence"):
        sc.validate_scorecard(fixture_payload)


# --- the synthetic fixture --------------------------------------------------------------------


def test_the_fixture_is_flagged_synthetic_in_its_own_filename() -> None:
    assert FIXTURE.exists()
    assert ".synthetic." in FIXTURE.name
    assert json.loads(FIXTURE.read_text(encoding="utf-8").splitlines()[0])["kind"] == "prediction"


def test_no_shipped_module_names_the_synthetic_fixture() -> None:
    """Synthetic data must never reach a shipped code path — the page publishes real numbers."""
    offenders = []
    for folder in ("forecast", "backend", "frontend"):
        for path in (REPO / folder).rglob("*"):
            if not path.is_file() or path.suffix in {".pyc", ".png", ".ico", ".woff2"}:
                continue
            if "winning.synthetic" in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"a shipped module names the synthetic fixture: {offenders}"


def test_the_pinned_scorecard_over_the_synthetic_winning_ledger(fixture_payload) -> None:
    """Six cycles, built to make the counters diverge — and to make the blend lose three.

    The blend wins the first two cycles, loses the next three and wins the last, so
    `current_won_cycles` (1) is not `longest_won_cycles` (2) and `current_beaten_cycles` (0)
    is not `longest_beaten_cycles` (3). A counter that only ever reported one of the two
    would pass a same-value pin and be wrong here.
    """
    sc.validate_scorecard(fixture_payload)
    assert fixture_payload["streaks"] == {
        "n_cycles_scored": 6,
        "current_beaten_cycles": 0,
        "longest_beaten_cycles": 3,
        "current_won_cycles": 1,
        "longest_won_cycles": 2,
    }
    assert fixture_payload["streaks"]["current_won_cycles"] > 0
    assert fixture_payload["streaks"]["longest_beaten_cycles"] > 0
    assert [c["blend_beaten"] for c in fixture_payload["by_cycle"]] == [
        False, False, True, True, True, False
    ]
    assert fixture_payload["meta"]["counts"] == {
        "cycles_recorded": 6, "rows_recorded": 90, "graded": 84, "pending": 5, "gap": 1,
        "rows_outside_grading_window": 0,
    }
    assert fixture_payload["meta"]["window"] == {
        "first_init_time": "2026-09-01T00:00:00Z",
        "last_init_time": "2026-09-02T06:00:00Z",
        "days_recorded": 2,
    }
    assert fixture_payload["by_series"] == [
        {"series": "HRRR", "series_kind": "model", "mae_f": 1.5, "bias_f": 0.441, "n": 17},
        {"series": "GFS", "series_kind": "model", "mae_f": 2.971, "bias_f": 0.853, "n": 17},
        {"series": "NAM", "series_kind": "model", "mae_f": 3.938, "bias_f": 0.938, "n": 16},
        {"series": "NBM", "series_kind": "model", "mae_f": 4.971, "bias_f": 1.441, "n": 17},
        {"series": "BLEND", "series_kind": "blend", "mae_f": 1.441, "bias_f": 0.382, "n": 17},
    ]
    assert fixture_payload["by_lead"] == [
        {"lead_h": 3, "blend_mae_f": 1.0, "n": 6, "best_single_model": "HRRR",
         "best_single_mae_f": 1.0, "blend_beaten": False},
        {"lead_h": 6, "blend_mae_f": 1.5, "n": 6, "best_single_model": "HRRR",
         "best_single_mae_f": 1.5, "blend_beaten": False},
        {"lead_h": 9, "blend_mae_f": 1.75, "n": 4, "best_single_model": "HRRR",
         "best_single_mae_f": 2.25, "blend_beaten": False},
    ]


def test_the_fixture_ledger_has_no_duplicate_row_identities(fixture_rows) -> None:
    """So first-wins-on-write and latest-wins-on-read can never disagree about it."""
    identities = [sc.row_identity(row) for row in fixture_rows]
    assert len(identities) == len(set(identities)) == 175
    assert sc.dedupe(fixture_rows) == fixture_rows
    duplicated = fixture_rows + [fixture_rows[0]]
    assert len(sc.dedupe(duplicated)) == 175, "the control: a duplicate really does collapse"
