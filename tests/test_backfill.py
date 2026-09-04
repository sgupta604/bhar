"""T4 Stream 3 tests — the ledger, classification, retry, deadline guard, coverage.

SPEC §13: **offline only.** An autouse fixture blocks `socket` for every test in this
module, so a backfill that ever grew a live call inside `run_backfill` turns these red
rather than quietly going to the network. Every `fetcher` here is injected.

The failure modes pinned here are the ones that are silent in production:

* a crash-truncated ledger line taking the other 1439 outcomes down with it;
* `RuntimeError from requests.ConnectionError` classified as anything but
  `failed_network` (`fetch/grib.py:_get` wraps the request exception, so
  `except requests.RequestException` never fires);
* an HTTP-500-flavoured `RuntimeError` classified as `missing`, which silently deflates
  the numerator and fakes a clean run (SPEC §10);
* a 404 being retried three times for nothing;
* a hung socket eating the 15-minute budget with no deadline guard (SPEC §8);
* coverage computed over the rows that happen to be present rather than the enumerated
  denominator — 100% of a short ledger;
* a below-floor model being dropped. **T4 flags and reports; T5 decides exclusion.**
"""

import json
import socket
import threading
from datetime import datetime, timezone

import pyarrow.parquet as pq
import pytest
import requests

from fetch import backfill
from fetch.grib import ArchiveMissing
from fetch.schema import FORECAST_SCHEMA
from fetch.window import init_times, work_items

UTC = timezone.utc
END_INIT = datetime(2026, 8, 5, 12, tzinfo=UTC)
MODELS = ("hrrr", "gfs", "nam", "nbm")
LEADS = (6, 12, 24)


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §13: no test in this module may open a socket."""

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "SPEC §13 violation: tests/test_backfill.py tried to open a network socket. "
            "Every fetcher in this module is injected."
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


# --- helpers -------------------------------------------------------------------------------


def sample_result(model="hrrr", init=END_INIT, lead=6, temp_f=68.24) -> dict:
    return {
        "model": model,
        "init_time": init,
        "lead_h": lead,
        "valid_time": init.replace(hour=(init.hour + lead) % 24),
        "temp_f": temp_f,
        "grid_lat": 41.2914,
        "grid_lon": -95.8923,
        "distance_deg": 0.012,
    }


def ok_fetcher(model, init, lead):
    return sample_result(model, init, lead, temp_f=60.0 + lead)


def record_for(item, status: str) -> dict:
    model, init, lead = item
    if status == "success":
        return backfill.make_record(
            item, status="success", result=sample_result(model, init, lead)
        )
    return backfill.make_record(item, status=status, error=f"synthetic {status}")


def full_window():
    inits = init_times(END_INIT, 120)
    return inits, work_items(inits, MODELS, LEADS)


def ledger_from(items, status_of) -> dict:
    return {
        backfill.ledger_key(*item): record_for(item, status_of(item)) for item in items
    }


# --- 3.1 ledger ------------------------------------------------------------------------------


def test_append_then_load_round_trips(tmp_path):
    path = tmp_path / "ledger.jsonl"
    item = ("hrrr", END_INIT, 6)
    record = record_for(item, "success")
    backfill.append_ledger(path, record)

    loaded = backfill.load_ledger(path)
    key = backfill.ledger_key(*item)
    assert list(loaded) == [key]
    assert loaded[key]["temp_f"] == pytest.approx(68.24)
    assert loaded[key]["init_time"] == "2026-08-05T12:00:00Z"
    assert loaded[key]["valid_time"].endswith("Z")
    assert list(loaded[key]) == list(backfill.LEDGER_FIELDS)


def test_missing_file_is_an_empty_ledger(tmp_path):
    assert backfill.load_ledger(tmp_path / "nope.jsonl") == {}


def test_truncated_final_line_is_skipped_not_raised(tmp_path):
    path = tmp_path / "ledger.jsonl"
    backfill.append_ledger(path, record_for(("hrrr", END_INIT, 6), "success"))
    backfill.append_ledger(path, record_for(("gfs", END_INIT, 6), "success"))
    with open(path, "a", encoding="utf-8") as handle:  # a kill mid-write
        handle.write('{"model": "nam", "init_time": "2026-08-05T12:00:00Z", "lea')

    loaded = backfill.load_ledger(path)
    assert set(loaded) == {
        backfill.ledger_key("hrrr", END_INIT, 6),
        backfill.ledger_key("gfs", END_INIT, 6),
    }


def test_blank_lines_are_skipped(tmp_path):
    path = tmp_path / "ledger.jsonl"
    backfill.append_ledger(path, record_for(("hrrr", END_INIT, 6), "success"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n   \n\n")
    backfill.append_ledger(path, record_for(("gfs", END_INIT, 6), "missing"))

    assert len(backfill.load_ledger(path)) == 2


def test_latest_record_wins_for_a_repeated_key(tmp_path):
    path = tmp_path / "ledger.jsonl"
    item = ("hrrr", END_INIT, 6)
    backfill.append_ledger(path, record_for(item, "failed_network"))
    backfill.append_ledger(path, record_for(item, "success"))

    loaded = backfill.load_ledger(path)
    assert len(loaded) == 1
    assert loaded[backfill.ledger_key(*item)]["status"] == "success"


def test_appending_never_truncates_prior_lines(tmp_path):
    path = tmp_path / "ledger.jsonl"
    for lead in LEADS:
        backfill.append_ledger(path, record_for(("hrrr", END_INIT, lead), "success"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["lead_h"] for line in lines] == list(LEADS)


def test_concurrent_appends_all_land_uncorrupted(tmp_path):
    path = tmp_path / "ledger.jsonl"
    inits = init_times(END_INIT, 10)
    items = work_items(inits, MODELS, LEADS)  # 120 items

    def worker(chunk):
        for item in chunk:
            backfill.append_ledger(path, record_for(item, "success"))

    threads = [
        threading.Thread(target=worker, args=(items[i::8],)) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(items)
    parsed = [json.loads(line) for line in lines]  # no interleaved/corrupt lines
    assert len(backfill.load_ledger(path)) == len(items)
    assert {p["status"] for p in parsed} == {"success"}


# --- resume ----------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["success", "missing"])
def test_settled_statuses_are_skipped(status):
    assert backfill.should_skip({"status": status}) is True


@pytest.mark.parametrize("status", ["failed_network", "failed_decode", "not_attempted"])
def test_unsettled_statuses_are_requeued(status):
    assert backfill.should_skip({"status": status}) is False


def test_should_skip_on_an_absent_record():
    assert backfill.should_skip(None) is False
    assert backfill.should_skip({}) is False


def test_pending_items_filters_only_settled_work():
    inits = init_times(END_INIT, 2)
    items = work_items(inits, ("hrrr", "gfs"), LEADS)  # 12
    statuses = {
        0: "success",
        1: "missing",
        2: "failed_network",
        3: "failed_decode",
        4: "not_attempted",
    }
    ledger = {
        backfill.ledger_key(*items[i]): {"status": status} for i, status in statuses.items()
    }
    todo = backfill.pending_items(items, ledger)
    assert items[0] not in todo and items[1] not in todo
    assert items[2] in todo and items[3] in todo and items[4] in todo
    assert len(todo) == len(items) - 2


# --- 3.2 classification ------------------------------------------------------------------------


def wrapped_request_error() -> RuntimeError:
    """Built exactly the way `fetch/grib.py:_get` builds it: `raise RuntimeError(...) from`."""
    try:
        try:
            raise requests.ConnectionError("connection reset by peer")
        except requests.RequestException as exc:
            raise RuntimeError("SPEC §9 hard stop: GET ... failed twice") from exc
    except RuntimeError as built:
        return built


def test_archive_missing_classifies_as_missing():
    assert backfill.classify(ArchiveMissing("HTTP 404")) == "missing"


def test_wrapped_request_exception_classifies_as_failed_network():
    exc = wrapped_request_error()
    assert isinstance(exc, RuntimeError)
    assert isinstance(exc.__cause__, requests.RequestException)
    assert backfill.classify(exc) == "failed_network"


@pytest.mark.parametrize(
    "exc",
    [
        AssertionError("SPEC §5: nearest cell is 3.2 deg away"),
        ValueError("no ':TMP:2 m above ground:' record in the .idx"),
        KeyError("t2m"),
    ],
)
def test_decode_failures_classify_as_failed_decode(exc):
    assert backfill.classify(exc) == "failed_decode"


def test_plain_runtime_error_is_failed_decode_never_missing():
    """A 500 misfiled as `missing` deflates the numerator and fakes a clean run."""
    exc = RuntimeError("SPEC §9 hard stop: GET ... returned HTTP 500")
    assert exc.__cause__ is None
    assert backfill.classify(exc) == "failed_decode"
    assert backfill.classify(exc) != "missing"


# --- 3.3 retry ----------------------------------------------------------------------------------


def test_transient_failure_is_retried_twice_with_2s_then_5s():
    calls = []
    slept = []

    def flaky(model, init, lead):
        calls.append((model, init, lead))
        raise wrapped_request_error()

    record = backfill.attempt_item(
        ("hrrr", END_INIT, 6), flaky, backfill.BACKOFF_S, slept.append
    )
    assert len(calls) == 3  # initial + 2 retries
    assert slept == [2, 5]
    assert record["status"] == "failed_network"
    assert record["error"] and len(record["error"]) <= backfill.MAX_ERROR_CHARS


def test_success_on_the_third_attempt_records_success():
    calls = []
    slept = []

    def eventually(model, init, lead):
        calls.append(1)
        if len(calls) < 3:
            raise wrapped_request_error()
        return sample_result(model, init, lead)

    record = backfill.attempt_item(
        ("hrrr", END_INIT, 6), eventually, backfill.BACKOFF_S, slept.append
    )
    assert len(calls) == 3
    assert slept == [2, 5]
    assert record["status"] == "success"
    assert record["temp_f"] == pytest.approx(68.24)


def test_archive_missing_is_attempted_exactly_once():
    """A key that does not exist will not exist five seconds later (SPEC §11 R2)."""
    calls = []
    slept = []

    def gone(model, init, lead):
        calls.append(1)
        raise ArchiveMissing("SPEC §11 R2: GET ... returned HTTP 404")

    record = backfill.attempt_item(
        ("hrrr", END_INIT, 6), gone, backfill.BACKOFF_S, slept.append
    )
    assert len(calls) == 1
    assert slept == []
    assert record["status"] == "missing"


def test_a_long_error_is_truncated_in_the_ledger():
    def noisy(model, init, lead):
        raise ValueError("x" * 5000)

    record = backfill.attempt_item(("hrrr", END_INIT, 6), noisy, (), lambda _s: None)
    assert len(record["error"]) == backfill.MAX_ERROR_CHARS


# --- 3.3 the pool and the deadline guard ---------------------------------------------------------


def test_run_backfill_records_every_outcome(tmp_path):
    inits = init_times(END_INIT, 3)
    items = work_items(inits, MODELS, LEADS)  # 36

    def mixed(model, init, lead):
        if model == "nbm":
            raise ArchiveMissing("HTTP 404")
        if model == "nam" and lead == 24:
            raise RuntimeError("HTTP 500, no cause")
        return sample_result(model, init, lead)

    path = tmp_path / "ledger.jsonl"
    summary = backfill.run_backfill(
        items, fetcher=mixed, workers=4, ledger_path=path, sleep=lambda _s: None
    )
    assert summary["deadline_hit"] is False
    assert summary["missing"] == 9  # nbm: 3 inits x 3 leads
    assert summary["failed_decode"] == 3  # nam f024
    assert summary["success"] == 36 - 9 - 3
    assert summary["executor"] == "thread"
    assert summary["workers"] == 4
    assert len(backfill.load_ledger(path)) == 36


def test_deadline_guard_fires_and_marks_the_rest_not_attempted(tmp_path):
    """SPEC §8 is ENFORCED, not hoped for: prove the guard fires, not that work ran out."""
    inits = init_times(END_INIT, 1)
    items = work_items(inits, MODELS, LEADS)  # 12
    lock = threading.Lock()
    clock = {"t": 0.0}
    calls = []

    def slow(model, init, lead):
        with lock:
            calls.append((model, init, lead))
            clock["t"] += 10.0  # each fetch burns 10 s of the budget
        return sample_result(model, init, lead)

    path = tmp_path / "ledger.jsonl"
    summary = backfill.run_backfill(
        items,
        fetcher=slow,
        workers=1,
        deadline_s=15.0,
        ledger_path=path,
        sleep=lambda _s: None,
        now=lambda: clock["t"],
    )

    assert summary["deadline_hit"] is True
    assert summary["not_attempted"] > 0
    assert summary["success"] > 0
    assert summary["success"] + summary["not_attempted"] == len(items)
    assert len(calls) < len(items)  # the guard stopped submission

    ledger = backfill.load_ledger(path)  # everything already fetched is still written
    assert len(ledger) == len(items)
    assert {r["status"] for r in ledger.values()} == {"success", "not_attempted"}


def test_full_1440_item_run_with_an_injected_fetcher(tmp_path):
    inits, items = full_window()
    assert len(items) == 1440

    path = tmp_path / "ledger.jsonl"
    summary = backfill.run_backfill(
        items, fetcher=ok_fetcher, workers=8, ledger_path=path, sleep=lambda _s: None
    )
    assert summary["success"] == 1440
    assert summary["not_attempted"] == 0
    assert summary["deadline_hit"] is False

    ledger = backfill.load_ledger(path)
    assert len(ledger) == 1440
    frame = backfill.forecasts_from_ledger(ledger)
    assert len(frame) == 1440
    assert frame["model"].value_counts().to_dict() == {m: 360 for m in MODELS}


def test_run_backfill_is_resumable(tmp_path):
    inits = init_times(END_INIT, 2)
    items = work_items(inits, MODELS, LEADS)  # 24
    path = tmp_path / "ledger.jsonl"

    def half(model, init, lead):
        if model in ("nam", "nbm"):
            raise wrapped_request_error()
        return sample_result(model, init, lead)

    backfill.run_backfill(
        items, fetcher=half, workers=4, ledger_path=path, sleep=lambda _s: None
    )
    todo = backfill.pending_items(items, backfill.load_ledger(path))
    assert len(todo) == 12  # only the failed halves come back

    calls = []

    def second_pass(model, init, lead):
        calls.append(model)
        return sample_result(model, init, lead)

    backfill.run_backfill(
        todo, fetcher=second_pass, workers=4, ledger_path=path, sleep=lambda _s: None
    )
    assert len(calls) == 12
    assert set(calls) == {"nam", "nbm"}
    ledger = backfill.load_ledger(path)
    assert len(ledger) == 24
    assert {r["status"] for r in ledger.values()} == {"success"}


def test_unknown_executor_is_rejected():
    with pytest.raises(ValueError, match="thread"):
        backfill.run_backfill([], executor="magic")


# --- 3.4 coverage arithmetic ---------------------------------------------------------------------


def test_denominators_are_360_and_120():
    inits, items = full_window()
    coverage = backfill.coverage_from_ledger(
        ledger_from(items, lambda item: "success"), models=MODELS, inits=inits, leads=LEADS
    )
    assert coverage["denominators"] == {"per_model": 360, "per_model_lead": 120}
    for model in MODELS:
        assert coverage["models"][model]["total"] == 360
        assert coverage["models"][model]["coverage_pct"] == 100.0
        assert coverage["models"][model]["below_floor"] is False
        for lead in ("6", "12", "24"):
            assert coverage["models"][model]["by_lead"][lead]["total"] == 120


def test_denominator_comes_from_the_window_not_the_ledger_length():
    """A short ledger must show LOW coverage, never 100% of a small number."""
    inits, items = full_window()
    short = {backfill.ledger_key(*item): record_for(item, "success") for item in items[:10]}
    coverage = backfill.coverage_from_ledger(
        short, models=MODELS, inits=inits, leads=LEADS
    )
    hrrr = coverage["models"]["hrrr"]
    assert hrrr["total"] == 360
    assert hrrr["success"] == 10
    assert hrrr["not_attempted"] == 350
    assert hrrr["coverage_pct"] == pytest.approx(10 / 360 * 100, abs=1e-4)
    assert hrrr["below_floor"] is True


def _coverage_with_hrrr_successes(n_success: int):
    inits, items = full_window()
    hrrr_items = [item for item in items if item[0] == "hrrr"]
    successful = {backfill.ledger_key(*item) for item in hrrr_items[:n_success]}

    def status_of(item):
        if item[0] != "hrrr":
            return "success"
        return "success" if backfill.ledger_key(*item) in successful else "missing"

    return backfill.coverage_from_ledger(
        ledger_from(items, status_of), models=MODELS, inits=inits, leads=LEADS
    )


def test_exactly_ninety_percent_passes_the_floor():
    coverage = _coverage_with_hrrr_successes(324)  # 324/360 == 90.0
    hrrr = coverage["models"]["hrrr"]
    assert hrrr["success"] == 324
    assert hrrr["coverage_pct"] == 90.0
    assert hrrr["below_floor"] is False


def test_one_success_below_the_floor_flags():
    coverage = _coverage_with_hrrr_successes(323)
    hrrr = coverage["models"]["hrrr"]
    assert hrrr["coverage_pct"] < backfill.COVERAGE_FLOOR_PCT
    assert hrrr["below_floor"] is True


def test_an_all_missing_ledger_is_zero_percent_and_does_not_raise():
    inits, items = full_window()
    coverage = backfill.coverage_from_ledger(
        ledger_from(items, lambda item: "missing"), models=MODELS, inits=inits, leads=LEADS
    )
    for model in MODELS:
        block = coverage["models"][model]
        assert block["missing"] == 360
        assert block["coverage_pct"] == 0.0
        assert block["below_floor"] is True


def test_a_below_floor_model_is_never_dropped(tmp_path):
    """T4 FLAGS AND REPORTS. T5 DECIDES EXCLUSION (SPEC §5)."""
    inits, items = full_window()

    def status_of(item):
        if item[0] == "hrrr" and item[1].hour == 0:  # a quarter of hrrr's runs missing
            return "missing"
        return "success"

    ledger = ledger_from(items, status_of)
    coverage = backfill.coverage_from_ledger(
        ledger, models=MODELS, inits=inits, leads=LEADS
    )
    assert coverage["models"]["hrrr"]["below_floor"] is True
    assert "hrrr" in coverage["models"]  # still present, in full

    frame = backfill.forecasts_from_ledger(ledger)
    assert (frame["model"] == "hrrr").sum() == 270  # its successes still reach the parquet
    out = backfill.write_forecasts(frame, tmp_path / "forecasts.parquet", MODELS)
    assert out.exists()


def test_print_coverage_flags_the_below_floor_model(capsys):
    inits, items = full_window()
    coverage = _coverage_with_hrrr_successes(300)
    backfill.print_coverage(coverage)
    out = capsys.readouterr().out
    assert "FLAG: hrrr coverage" in out
    assert "T5 decides exclusion (SPEC §5)" in out
    assert "RESULT, not a bug" in out
    assert "FLAG: gfs" not in out


# --- 3.4 coverage.json shape (LOCKED — T5 reads it) ----------------------------------------------


def test_coverage_json_shape_is_locked(tmp_path):
    inits, items = full_window()
    coverage = backfill.coverage_from_ledger(
        ledger_from(items, lambda item: "success"),
        models=MODELS,
        inits=inits,
        leads=LEADS,
        run={
            "workers": 8,
            "executor": "thread",
            "elapsed_s": 12.5,
            "deadline_s": 900,
            "deadline_hit": False,
        },
    )
    path = backfill.write_coverage(coverage, tmp_path / "coverage.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert set(loaded) == {
        "generated_at",
        "window",
        "denominators",
        "threshold_pct",
        "models",
        "obs",
        "run",
    }
    assert loaded["generated_at"].endswith("Z")
    assert set(loaded["window"]) == {
        "start_init",
        "end_init",
        "n_inits",
        "leads_h",
        "models",
        "obs_start",
        "obs_end",
    }
    assert loaded["window"]["n_inits"] == 120
    assert loaded["window"]["leads_h"] == [6, 12, 24]
    assert loaded["window"]["models"] == list(MODELS)
    assert loaded["window"]["end_init"] == "2026-08-05T12:00:00Z"
    for key in ("start_init", "end_init", "obs_start", "obs_end"):
        assert loaded["window"][key].endswith("Z")
    assert loaded["threshold_pct"] == 90.0
    assert loaded["denominators"] == {"per_model": 360, "per_model_lead": 120}
    assert set(loaded["models"]) == set(MODELS)
    block = loaded["models"]["hrrr"]
    assert set(block) == {
        "success",
        "missing",
        "failed_network",
        "failed_decode",
        "not_attempted",
        "total",
        "coverage_pct",
        "below_floor",
        "by_lead",
    }
    assert list(block["by_lead"]) == ["6", "12", "24"]  # STRING keys
    assert set(block["by_lead"]["6"]) == {"success", "total", "coverage_pct"}
    assert loaded["obs"] == {"rows": 0, "distinct_hours": 0, "start": None, "end": None}
    assert loaded["run"] == {
        "workers": 8,
        "executor": "thread",
        "elapsed_s": 12.5,
        "deadline_s": 900,
        "deadline_hit": False,
    }


def test_write_coverage_preserves_an_existing_obs_block(tmp_path):
    """`--forecasts-only` must not erase what the obs step already recorded."""
    inits, items = full_window()
    path = tmp_path / "coverage.json"
    obs = {
        "rows": 1447,
        "distinct_hours": 722,
        "start": "2026-07-07T17:00:00Z",
        "end": "2026-08-06T13:00:00Z",
    }
    first = backfill.coverage_from_ledger(
        ledger_from(items, lambda item: "success"),
        models=MODELS,
        inits=inits,
        leads=LEADS,
        obs=obs,
    )
    backfill.write_coverage(first, path)

    second = backfill.coverage_from_ledger(
        ledger_from(items, lambda item: "success"), models=MODELS, inits=inits, leads=LEADS
    )
    assert second["obs"] == backfill.empty_obs_block()
    backfill.write_coverage(second, path)
    assert json.loads(path.read_text(encoding="utf-8"))["obs"] == obs


# --- 3.4 the parquet writer -----------------------------------------------------------------------


def test_forecasts_parquet_round_trips_the_pinned_schema(tmp_path):
    inits = init_times(END_INIT, 4)
    items = work_items(inits, MODELS, LEADS)
    frame = backfill.forecasts_from_ledger(ledger_from(items, lambda item: "success"))
    assert list(frame.columns) == ["model", "init_time", "lead_h", "valid_time", "temp_f"]

    path = backfill.write_forecasts(frame, tmp_path / "forecasts.parquet", MODELS)
    table = pq.read_table(path)
    assert table.schema.equals(FORECAST_SCHEMA)
    assert table.schema.field("model").type == FORECAST_SCHEMA.field("model").type
    assert str(table.schema.field("lead_h").type) == "int32"
    assert str(table.schema.field("init_time").type) == "timestamp[us, tz=UTC]"
    assert str(table.schema.field("valid_time").type) == "timestamp[us, tz=UTC]"
    assert table.num_rows == len(items)


def test_only_success_rows_reach_the_parquet():
    inits = init_times(END_INIT, 2)
    items = work_items(inits, MODELS, LEADS)  # 24

    def status_of(item):
        return "success" if item[2] == 6 else "missing"

    frame = backfill.forecasts_from_ledger(ledger_from(items, status_of))
    assert len(frame) == 8
    assert set(frame["lead_h"].tolist()) == {6}


def test_forecast_rows_are_deterministically_sorted():
    inits = init_times(END_INIT, 3)
    items = work_items(inits, MODELS, LEADS)
    ledger = ledger_from(items, lambda item: "success")
    frame = backfill.forecasts_from_ledger(ledger)
    keys = list(zip(frame["model"], frame["init_time"], frame["lead_h"], strict=True))
    assert keys == sorted(keys)


def test_an_all_failed_ledger_raises_rather_than_writing_an_empty_parquet(tmp_path):
    inits = init_times(END_INIT, 2)
    items = work_items(inits, MODELS, LEADS)
    frame = backfill.forecasts_from_ledger(ledger_from(items, lambda item: "failed_network"))
    assert len(frame) == 0
    path = tmp_path / "forecasts.parquet"
    with pytest.raises(AssertionError):
        backfill.write_forecasts(frame, path, MODELS)
    assert not path.exists()


def test_a_model_with_zero_successes_is_the_spec_9_hard_stop(tmp_path):
    inits = init_times(END_INIT, 2)
    items = work_items(inits, MODELS, LEADS)

    def status_of(item):
        return "missing" if item[0] == "nbm" else "success"

    frame = backfill.forecasts_from_ledger(ledger_from(items, status_of))
    with pytest.raises(AssertionError, match="nbm"):
        backfill.write_forecasts(frame, tmp_path / "forecasts.parquet", MODELS)


def test_holes_in_a_model_are_not_a_hard_stop(tmp_path):
    """HRRR with holes still writes. Only ZERO successes is SPEC §9 hard stop #1."""
    inits = init_times(END_INIT, 4)
    items = work_items(inits, MODELS, LEADS)

    def status_of(item):
        return "missing" if (item[0] == "hrrr" and item[2] != 6) else "success"

    frame = backfill.forecasts_from_ledger(ledger_from(items, status_of))
    out = backfill.write_forecasts(frame, tmp_path / "forecasts.parquet", MODELS)
    assert out.exists()
    assert (frame["model"] == "hrrr").sum() == 4
