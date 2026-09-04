"""Step-grid derivation and disk-cache tests for `forecast/live.py` (F2, Stream 3).

Zero network and zero wall-clock reads: every test drives injected data and `tmp_path`.
Numbering follows the plan's test index (T11-T23,
`.claude/features/forecast-live-fetch/2026-09-04T12-01-07_plan.md` §6 Stream 3).

The grid tests deliberately assert the *properties* of the derivation rather than
comparing against a copied tuple — a test that copies the answer proves nothing about
whether the answer was computed.
"""

from __future__ import annotations

import ast
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fetch.grib import ArchiveMissing
from forecast import cycle, live

UTC = timezone.utc

INIT = datetime(2026, 9, 4, 12, tzinfo=UTC)
FETCHED_AT = datetime(2026, 9, 4, 16, 53, 0, tzinfo=UTC)

MODELS = ("hrrr", "gfs", "nam", "nbm")


# --- helpers ---------------------------------------------------------------------------


def success_record(model: str = "hrrr", lead: int = 3) -> dict:
    """A `status="success"` cache record, every field populated."""
    return {
        "model": model,
        "init_time": INIT,
        "lead_h": lead,
        "valid_time": INIT + timedelta(hours=lead),
        "status": "success",
        "temp_f": 71.42,
        "grid_lat": 41.3,
        "grid_lon": -95.9,
        "distance_deg": 0.0123,
        "error": None,
        "fetched_at": FETCHED_AT,
    }


def missing_record(model: str = "nam", lead: int = 48) -> dict:
    """A `status="missing"` cache record — `temp_f` null, `error` carries the text."""
    return {
        "model": model,
        "init_time": INIT,
        "lead_h": lead,
        "valid_time": INIT + timedelta(hours=lead),
        "status": "missing",
        "temp_f": None,
        "grid_lat": None,
        "grid_lon": None,
        "distance_deg": None,
        "error": "SPEC §11 R2: GET ... returned HTTP 404 — the run is absent from the archive.",
        "fetched_at": FETCHED_AT,
    }


def assert_is_the_intersection(published: dict, step: int, max_lead: int) -> tuple[int, ...]:
    """The two derivation properties, checked together: membership and maximality."""
    grid = live.step_grid(published=published, step=step, max_lead=max_lead)
    candidates = tuple(range(step, max_lead + 1, step))  # the half-open range (0, max_lead]

    # (a) membership: every grid lead is published by EVERY model.
    for lead in grid:
        for model, leads in published.items():
            assert lead in leads, f"grid keeps f{lead:03d} but {model} does not publish it"

    # (b) maximality: no excluded multiple of the step is published by every model.
    for lead in candidates:
        if lead in grid:
            continue
        assert not all(lead in leads for leads in published.values()), (
            f"f{lead:03d} is published by all {len(published)} models but the grid excludes it"
        )

    # and nothing outside the candidate multiples leaked in
    assert set(grid) <= set(candidates)
    return grid


# --- T11: the derived grid -------------------------------------------------------------


def test_t11_step_grid_is_f003_to_f048_in_16_steps_of_3():
    grid = live.step_grid()
    assert grid == tuple(range(3, 49, 3))
    assert len(grid) == 16
    assert grid[0] == 3
    assert grid[-1] == 48


def test_t11_step_grid_excludes_f000_because_nbm_publishes_none():
    grid = live.step_grid()
    assert 0 not in grid, "f000 must be excluded — NBM publishes no f000"
    assert 0 not in live.PROBE_PUBLISHED_LEADS["nbm"]


# --- T11a: derivation properties, not a copied tuple -----------------------------------


def test_t11a_probe_table_covers_exactly_the_four_models():
    assert set(live.PROBE_PUBLISHED_LEADS) == set(MODELS)


def test_t11a_grid_is_the_intersection_of_the_probe_table():
    grid = assert_is_the_intersection(
        live.PROBE_PUBLISHED_LEADS, live.CANDIDATE_STEP_H, live.CANDIDATE_MAX_LEAD_H
    )
    assert grid, "an empty grid is not a passing result"


def test_t11a_maximality_has_teeth_on_a_table_with_real_exclusions():
    """The real probe excludes nothing, so exercise maximality where exclusions exist."""
    published = {
        "hrrr": tuple(range(0, 49)),
        "gfs": tuple(range(0, 49)),
        "nam": tuple(range(0, 31)),  # stops at f030
        "nbm": tuple(range(1, 49)),
    }
    grid = assert_is_the_intersection(published, live.CANDIDATE_STEP_H, live.CANDIDATE_MAX_LEAD_H)
    excluded = set(range(3, 49, 3)) - set(grid)
    assert excluded, "this table must exclude some steps or the maximality check is vacuous"


def test_t11a_every_step_is_a_multiple_of_the_step_and_inside_the_ceiling():
    for lead in live.step_grid():
        assert lead % live.CANDIDATE_STEP_H == 0
        assert 0 < lead <= live.CANDIDATE_MAX_LEAD_H


# --- T11b: the value is computed, not a literal ----------------------------------------


def test_t11b_synthetic_table_with_nam_stopping_at_f030_ends_the_grid_at_30():
    published = {
        "hrrr": tuple(range(0, 49)),
        "gfs": tuple(range(0, 49)),
        "nam": tuple(range(0, 31)),  # NAM stops at f030
        "nbm": tuple(range(1, 49)),
    }
    grid = live.step_grid(published=published)
    assert grid[-1] == 30, "the ceiling must come from the data, not from a literal 48"
    assert grid == tuple(range(3, 31, 3))
    assert 33 not in grid


def test_t11b_step_is_injectable():
    grid = live.step_grid(step=6)
    assert grid == tuple(range(6, 49, 6))


def test_t11b_max_lead_is_injectable():
    grid = live.step_grid(max_lead=24)
    assert grid == tuple(range(3, 25, 3))


def test_t11b_a_model_absent_at_every_multiple_yields_an_empty_grid():
    published = dict(live.PROBE_PUBLISHED_LEADS)
    published["nam"] = (0, 1, 2)
    assert live.step_grid(published=published) == ()


# --- T12: cache round-trip -------------------------------------------------------------


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    root = tmp_path / "live"
    root.mkdir()
    return root


def test_t12_cache_path_is_init_dir_slash_model_f_lead(cache_root: Path):
    path = live.cache_path(INIT, "nbm", 3, root=cache_root)
    assert path.relative_to(cache_root) == Path("2026090412") / "nbm_f003.json"
    assert live.cache_dir(INIT, root=cache_root) == cache_root / "2026090412"


def test_t12_cache_path_zero_pads_the_lead_to_three_digits(cache_root: Path):
    assert live.cache_path(INIT, "gfs", 48, root=cache_root).name == "gfs_f048.json"
    assert live.cache_path(INIT, "gfs", 6, root=cache_root).name == "gfs_f006.json"


def test_t12_cache_dir_uses_the_init_in_utc(cache_root: Path):
    naive = datetime(2026, 9, 4, 12)  # naive is UTC, never local (fetch.grib._as_utc)
    assert live.cache_dir(naive, root=cache_root).name == "2026090412"
    east = datetime(2026, 9, 4, 14, tzinfo=timezone(timedelta(hours=2)))
    assert live.cache_dir(east, root=cache_root).name == "2026090412"


@pytest.mark.parametrize("record", [success_record(), missing_record()])
def test_t12_write_then_read_round_trips_the_record(cache_root: Path, record: dict):
    path = live.cache_path(INIT, record["model"], record["lead_h"], root=cache_root)
    live.write_cached(path, record)
    assert path.exists()
    assert live.read_cached(path) == record


def test_t12_datetimes_come_back_tz_aware_utc(cache_root: Path):
    record = success_record()
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    live.write_cached(path, record)
    back = live.read_cached(path)
    for field in ("init_time", "valid_time", "fetched_at"):
        value = back[field]
        assert isinstance(value, datetime), f"{field} must deserialize to a datetime"
        assert value.tzinfo is not None, f"{field} must be tz-aware"
        assert value.utcoffset() == timedelta(0), f"{field} must be UTC"


def test_t12_file_is_valid_json_with_a_trailing_newline(cache_root: Path):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    live.write_cached(path, success_record())
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    payload = json.loads(text)
    assert payload["init_time"] == "2026-09-04T12:00:00Z"
    assert payload["valid_time"] == "2026-09-04T15:00:00Z"
    assert payload["fetched_at"] == "2026-09-04T16:53:00Z"
    assert payload["status"] == "success"
    assert payload["model"] == "hrrr"
    assert payload["temp_f"] == 71.42


def test_t12_missing_status_serializes_temp_f_as_null_and_keeps_the_error(cache_root: Path):
    path = live.cache_path(INIT, "nam", 48, root=cache_root)
    live.write_cached(path, missing_record())
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["temp_f"] is None
    assert payload["status"] == "missing"
    assert isinstance(payload["error"], str) and payload["error"]


def test_t12_write_creates_the_cycle_directory_and_leaves_no_temp_file(cache_root: Path):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    assert not path.parent.exists()
    live.write_cached(path, success_record())
    assert path.parent.is_dir()
    assert [p.name for p in path.parent.iterdir()] == ["hrrr_f003.json"]


def test_t12_write_is_a_replace_not_an_append(cache_root: Path):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    live.write_cached(path, success_record())
    second = success_record()
    second["temp_f"] = 55.0
    live.write_cached(path, second)
    assert live.read_cached(path)["temp_f"] == 55.0
    assert len(list(path.parent.iterdir())) == 1


def test_t12_model_keys_stay_lowercase(cache_root: Path):
    path = live.cache_path(INIT, "nbm", 3, root=cache_root)
    live.write_cached(path, success_record(model="nbm"))
    assert json.loads(path.read_text(encoding="utf-8"))["model"] == "nbm"
    assert path.name.startswith("nbm_")


# --- T17: a corrupt cache file is a MISS, never a crash --------------------------------


def test_t17_absent_file_is_a_miss(cache_root: Path):
    assert live.read_cached(live.cache_path(INIT, "hrrr", 3, root=cache_root)) is None


def test_t17_garbage_bytes_are_a_miss(cache_root: Path):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x01\x02not json at all{{{")
    assert live.read_cached(path) is None


def test_t17_truncated_json_is_a_miss(cache_root: Path):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    full = json.dumps(
        {
            "model": "hrrr",
            "init_time": "2026-09-04T12:00:00Z",
            "lead_h": 3,
            "valid_time": "2026-09-04T15:00:00Z",
            "status": "success",
            "temp_f": 71.42,
        }
    )
    path.write_text(full[: len(full) // 2], encoding="utf-8")
    assert live.read_cached(path) is None


@pytest.mark.parametrize(
    "dropped",
    ["model", "init_time", "lead_h", "valid_time", "status", "temp_f", "error", "fetched_at"],
)
def test_t17_valid_json_missing_a_required_key_is_a_miss(cache_root: Path, dropped: str):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    live.write_cached(path, success_record())
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload[dropped]
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    assert live.read_cached(path) is None, f"a record without {dropped!r} must be a miss"


def test_t17_a_json_list_instead_of_an_object_is_a_miss(cache_root: Path):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    assert live.read_cached(path) is None


def test_t17_an_unparseable_datetime_is_a_miss(cache_root: Path):
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    live.write_cached(path, success_record())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["valid_time"] = "not-a-timestamp"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    assert live.read_cached(path) is None


# --- T23: the cache-root guard (the data/raw hazard) -----------------------------------


def test_t23_default_root_resolves_inside_this_repository(REPO_ROOT: Path):
    resolved = live._guard_cache_root(live.LIVE_ROOT)
    assert resolved.is_absolute()
    assert REPO_ROOT.resolve() in resolved.parents


def test_t23_a_real_directory_root_is_accepted(cache_root: Path):
    assert live._guard_cache_root(cache_root) == cache_root.resolve()


def test_t23_a_root_that_is_a_symlink_raises_and_names_it(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "linked_live"
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError) as excinfo:
        live._guard_cache_root(link)
    assert "linked_live" in str(excinfo.value)


def test_t23_a_root_whose_parent_is_a_symlink_raises_and_names_the_parent(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    linked_parent = tmp_path / "linked_data"
    linked_parent.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError) as excinfo:
        live._guard_cache_root(linked_parent / "live")
    assert "linked_data" in str(excinfo.value)


def test_t23_write_through_a_symlinked_root_raises_and_writes_nothing(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "linked_live"
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError):
        live.write_cached(link / "2026090412" / "hrrr_f003.json", success_record())
    assert list(elsewhere.iterdir()) == []


def test_t23_write_through_a_symlinked_parent_raises_and_writes_nothing(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    linked_parent = tmp_path / "linked_data"
    linked_parent.symlink_to(elsewhere, target_is_directory=True)
    path = linked_parent / "live" / "2026090412" / "hrrr_f003.json"
    with pytest.raises(RuntimeError):
        live.write_cached(path, success_record())
    assert list(elsewhere.iterdir()) == []


def test_t23_cache_dir_refuses_a_symlinked_root(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "linked_live"
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError):
        live.cache_dir(INIT, root=link)


def test_t23_module_never_writes_through_the_shared_symlinks():
    source = (Path(live.__file__)).read_text(encoding="utf-8")
    for forbidden in ("parquet", "results.json", "obs.parquet"):
        assert forbidden not in source, f"forecast/live.py must never name {forbidden}"


# =========================================================================================
# Stream 4 — Phase A/B fetch, the cycle ladder, horizon and gaps (T13-T22a)
#
# Plan §6 Stream 4 / §0.4 (the two-phase rule). Every test injects a fetcher and a frozen
# clock and writes only under `tmp_path`: **zero network, zero wall-clock reads.** The
# fetchers below are the only things that stand in for `fetch.grib.fetch_point`, and one of
# them raises on *any* call — that is how the FR8 zero-network property is proved rather
# than asserted.
# =========================================================================================

NOW = datetime(2026, 9, 4, 16, 53, 0, tzinfo=UTC)  # target_cycle(NOW) == INIT (12z)
PREV = INIT - timedelta(hours=6)

GRID = live.step_grid()


class NetworkUsed(Exception):
    """Raised by `raising_fetcher`. Deliberately NOT a `RuntimeError` subclass.

    `fetch_one` catches `ArchiveMissing` and nothing else, so this would propagate either
    way — but keeping it off the `RuntimeError` branch means a test that fails here can only
    mean "the network was touched", never "the missing-record path swallowed it".
    """


def raising_fetcher(model: str, init_time: datetime, lead_h: int) -> dict:
    """A fetcher that refuses every call. A run that completes with this made no requests."""
    raise NetworkUsed(
        f"FR8 violated: the network was used for {model} f{lead_h:03d} at {init_time!r}"
    )


class RecordingFetcher:
    """An injected stand-in for `fetch.grib.fetch_point` over a table of published leads.

    `available` maps `init -> {model: set(leads)}`. Anything absent from the table raises
    `ArchiveMissing`, exactly as a 404 from the archive does. Every call is recorded under a
    lock, because `fetch_leads` drives this from a thread pool.
    """

    def __init__(self, available: dict[datetime, dict[str, set[int]]] | None = None) -> None:
        self.available = available or {}
        self.calls: list[tuple[str, datetime, int]] = []
        self._lock = threading.Lock()

    def __call__(self, model: str, init_time: datetime, lead_h: int) -> dict:
        init = init_time if init_time.tzinfo else init_time.replace(tzinfo=UTC)
        init = init.astimezone(UTC)
        with self._lock:
            self.calls.append((model, init, lead_h))
        published = self.available.get(init, {}).get(model, set())
        if lead_h not in published:
            raise ArchiveMissing(
                f"SPEC §11 R2: GET .../{model}/f{lead_h:03d} returned HTTP 404 — the run is "
                "absent from the archive."
            )
        return {
            "model": model,
            "init_time": init,
            "lead_h": lead_h,
            "valid_time": init + timedelta(hours=lead_h),
            "temp_f": 70.0 + lead_h * 0.1,
            "grid_lat": 41.3,
            "grid_lon": -95.9,
            "distance_deg": 0.0123,
        }

    @property
    def inits_requested(self) -> set[datetime]:
        return {init for (_model, init, _lead) in self.calls}


def full_table(*inits: datetime, grid: tuple[int, ...] = GRID) -> dict:
    """Every model publishes every grid lead at every one of `inits` — a healthy archive."""
    return {init: {model: set(grid) for model in MODELS} for init in inits}


def records_for(
    grid: tuple[int, ...],
    absent: set[tuple[str, int]] | None = None,
    init: datetime = INIT,
) -> dict[tuple[str, int], dict]:
    """`{(model, lead): record}` for a whole cycle; `absent` pairs come back `missing`."""
    holes = set(absent or ())
    out: dict[tuple[str, int], dict] = {}
    for lead in grid:
        for model in MODELS:
            record = missing_record(model=model, lead=lead) if (model, lead) in holes else (
                success_record(model=model, lead=lead)
            )
            record = dict(record)
            record["init_time"] = init
            record["valid_time"] = init + timedelta(hours=lead)
            out[(model, lead)] = record
    return out


# --- T13: FR8 — the zero-network re-run (NON-NEGOTIABLE) --------------------------------


def test_t13_a_whole_cycle_is_fetched_once_and_then_served_from_cache(cache_root: Path):
    fetcher = RecordingFetcher(full_table(INIT))
    first = live.fetch_cycle(INIT, fetcher=fetcher, cache_root=cache_root, now=NOW)

    assert first is not None, "a healthy archive must yield a cycle"
    assert len(first.records) == len(MODELS) * len(GRID) == 64
    assert len(fetcher.calls) == 64, "the first run must actually fetch every item"

    second = live.fetch_cycle(INIT, fetcher=raising_fetcher, cache_root=cache_root, now=NOW)

    assert second is not None
    assert len(second.records) == len(first.records)
    assert second.horizon_h == first.horizon_h
    assert second.gaps == first.gaps


def test_t13_the_cached_re_run_carries_the_same_temperatures(cache_root: Path):
    fetcher = RecordingFetcher(full_table(INIT))
    first = live.fetch_cycle(INIT, fetcher=fetcher, cache_root=cache_root, now=NOW)
    second = live.fetch_cycle(INIT, fetcher=raising_fetcher, cache_root=cache_root, now=NOW)
    assert {k: v["temp_f"] for k, v in second.records.items()} == {
        k: v["temp_f"] for k, v in first.records.items()
    }


def test_t13_the_cycle_directory_holds_one_file_per_item(cache_root: Path):
    live.fetch_cycle(INIT, fetcher=RecordingFetcher(full_table(INIT)),
                     cache_root=cache_root, now=NOW)
    files = sorted(p.name for p in (cache_root / "2026090412").iterdir())
    assert len(files) == 64
    assert files[0].endswith(".json")


# --- T14: a cached `missing` short-circuits the network too -----------------------------


def test_t14_a_cached_missing_record_is_not_re_requested(cache_root: Path):
    table = full_table(INIT)
    table[INIT]["nam"] = set(GRID) - {12}
    fetcher = RecordingFetcher(table)

    first = live.fetch_cycle(INIT, fetcher=fetcher, cache_root=cache_root, now=NOW)
    assert first is not None
    assert first.records[("nam", 12)]["status"] == "missing"

    second = live.fetch_cycle(INIT, fetcher=raising_fetcher, cache_root=cache_root, now=NOW)
    assert second is not None
    assert second.records[("nam", 12)]["status"] == "missing"
    assert [g["lead_h"] for g in second.gaps] == [12]


def test_t14_fetch_one_serves_a_cached_missing_without_calling_the_fetcher(cache_root: Path):
    table = {INIT: {model: set() for model in MODELS}}
    fetcher = RecordingFetcher(table)
    first = live.fetch_one("nam", INIT, 12, fetcher=fetcher, cache_root=cache_root)
    assert first["status"] == "missing"
    assert len(fetcher.calls) == 1

    again = live.fetch_one("nam", INIT, 12, fetcher=raising_fetcher, cache_root=cache_root)
    assert again["status"] == "missing"


def test_t14_refetch_missing_defaults_to_false(cache_root: Path):
    """Flipping this default would break FR8 outright — pin it."""
    table = {INIT: {model: set() for model in MODELS}}
    live.fetch_one("nam", INIT, 12, fetcher=RecordingFetcher(table), cache_root=cache_root)
    # explicit opt-in DOES re-request, which is what makes the default meaningful
    opt_in = RecordingFetcher(full_table(INIT))
    record = live.fetch_one(
        "nam", INIT, 12, fetcher=opt_in, cache_root=cache_root, refetch_missing=True
    )
    assert record["status"] == "success"
    assert len(opt_in.calls) == 1


# --- T14a: the whole ladder replays from cache ------------------------------------------


def test_t14a_the_fallback_ladder_makes_zero_requests_on_the_second_run(cache_root: Path):
    table = full_table(INIT, PREV)
    table[INIT]["nam"] = set(GRID) - {GRID[0]}  # target's Phase A fails for NAM
    fetcher = RecordingFetcher(table)

    first = live.select_cycle(NOW, fetcher=fetcher, cache_root=cache_root)
    assert first.cycles_fallen_back == 1
    assert first.init_time == PREV
    assert fetcher.calls, "the first run must have made requests"

    second = live.select_cycle(NOW, fetcher=raising_fetcher, cache_root=cache_root)
    assert second.init_time == PREV
    assert second.cycles_fallen_back == 1
    assert second.fallback_reasons == first.fallback_reasons
    assert len(second.records) == len(first.records) == 64


# --- T15: ArchiveMissing becomes a cached `missing`, fetched exactly once ----------------


def test_t15_archive_missing_is_recorded_not_raised(cache_root: Path):
    fetcher = RecordingFetcher({INIT: {model: set() for model in MODELS}})
    record = live.fetch_one("nbm", INIT, 48, fetcher=fetcher, cache_root=cache_root)

    assert record["status"] == "missing"
    assert record["temp_f"] is None
    assert record["grid_lat"] is None and record["grid_lon"] is None
    assert record["distance_deg"] is None
    assert isinstance(record["error"], str) and record["error"]
    assert record["init_time"] == INIT
    assert record["valid_time"] == INIT + timedelta(hours=48)


def test_t15_a_404_is_never_retried(cache_root: Path):
    """A key that does not exist will not exist five seconds later (plan §10)."""
    fetcher = RecordingFetcher({INIT: {model: set() for model in MODELS}})
    live.fetch_one("nbm", INIT, 48, fetcher=fetcher, cache_root=cache_root)
    assert len(fetcher.calls) == 1, "one 404 must cost exactly one request"


def test_t15_the_missing_record_lands_on_disk_and_reads_back(cache_root: Path):
    fetcher = RecordingFetcher({INIT: {model: set() for model in MODELS}})
    record = live.fetch_one("nbm", INIT, 48, fetcher=fetcher, cache_root=cache_root)
    path = live.cache_path(INIT, "nbm", 48, root=cache_root)
    assert path.exists()
    assert live.read_cached(path) == record


# --- T16: every other failure PROPAGATES and is never recorded as `missing` --------------


def _http_500(model: str, init_time: datetime, lead_h: int) -> dict:
    raise RuntimeError(
        f"SPEC §9 hard stop: GET .../{model}/f{lead_h:03d} returned HTTP 500."
    )


def test_t16_a_plain_runtime_error_propagates_out_of_fetch_one(cache_root: Path):
    with pytest.raises(RuntimeError) as excinfo:
        live.fetch_one("hrrr", INIT, 3, fetcher=_http_500, cache_root=cache_root)
    assert not isinstance(excinfo.value, ArchiveMissing)
    assert "500" in str(excinfo.value)


def test_t16_a_hard_stop_writes_no_cache_record(cache_root: Path):
    with pytest.raises(RuntimeError):
        live.fetch_one("hrrr", INIT, 3, fetcher=_http_500, cache_root=cache_root)
    path = live.cache_path(INIT, "hrrr", 3, root=cache_root)
    assert not path.exists(), "an HTTP 500 must never be filed as an archive hole"


def test_t16_a_hard_stop_propagates_out_of_fetch_cycle(cache_root: Path):
    with pytest.raises(RuntimeError) as excinfo:
        live.fetch_cycle(INIT, fetcher=_http_500, cache_root=cache_root, now=NOW)
    assert not isinstance(excinfo.value, ArchiveMissing)
    assert not isinstance(excinfo.value, live.NoCycleAvailable)


def test_t16_a_hard_stop_never_becomes_a_fallback(cache_root: Path):
    """Misclassifying a 500 as an archive hole would silently walk the ladder (plan §9.5)."""
    with pytest.raises(RuntimeError):
        live.select_cycle(NOW, fetcher=_http_500, cache_root=cache_root)
    written = list(cache_root.rglob("*.json"))
    assert written == [], f"nothing may be cached from a hard stop; found {written}"


# --- T18: the target cycle wins and later candidates are never touched -------------------


def test_t18_a_healthy_target_cycle_is_served_with_no_fallback(cache_root: Path):
    fetcher = RecordingFetcher(full_table(INIT))
    result = live.select_cycle(NOW, fetcher=fetcher, cache_root=cache_root)

    assert result.cycles_fallen_back == 0
    assert result.init_time == INIT == result.target_init_time
    assert result.run_label == "12z"
    assert result.fallback_reasons == ()
    assert result.is_stale is False and result.stale_reason is None
    assert result.horizon_h == GRID[-1] == 48
    assert result.grid_max_lead_h == 48
    assert result.truncated is False
    assert result.step_h == 3
    assert result.gaps == ()
    assert len(result.records) == 64


def test_t18_later_candidates_are_never_fetched(cache_root: Path):
    fetcher = RecordingFetcher(full_table(INIT))
    live.select_cycle(NOW, fetcher=fetcher, cache_root=cache_root)
    assert fetcher.inits_requested == {INIT}
    later = cycle.candidate_cycles(cycle.target_cycle(NOW))[1:]
    for init in later:
        assert init not in fetcher.inits_requested
        assert not (cache_root / init.strftime("%Y%m%d%H")).exists()


def test_t18_age_and_fetched_at_are_injected_not_read_from_the_clock(cache_root: Path):
    fetcher = RecordingFetcher(full_table(INIT))
    stamp = datetime(2026, 9, 4, 17, 0, 0, tzinfo=UTC)
    result = live.select_cycle(
        NOW, fetcher=fetcher, cache_root=cache_root, fetched_at=stamp
    )
    assert result.fetched_at == stamp
    assert result.age_minutes == cycle.age_minutes(INIT, NOW) == 293


# --- T19: a Phase A hole falls back EXACTLY one cycle ------------------------------------


def test_t19_a_model_missing_at_the_first_grid_step_falls_back_one_cycle(cache_root: Path):
    table = full_table(INIT, PREV)
    table[INIT]["nam"] = set(GRID) - {GRID[0]}
    fetcher = RecordingFetcher(table)

    result = live.select_cycle(NOW, fetcher=fetcher, cache_root=cache_root)

    assert result.cycles_fallen_back == 1
    assert result.init_time == PREV
    assert result.target_init_time == INIT
    assert result.run_label == "06z"
    assert len(result.fallback_reasons) == 1
    assert "nam" in result.fallback_reasons[0]
    assert live._iso(INIT) in result.fallback_reasons[0]
    assert result.is_stale is True
    assert result.stale_reason and "fallback" in result.stale_reason


def test_t19_every_returned_record_shares_one_init_time(cache_root: Path):
    table = full_table(INIT, PREV)
    table[INIT]["nam"] = set(GRID) - {GRID[0]}
    result = live.select_cycle(NOW, fetcher=RecordingFetcher(table), cache_root=cache_root)

    inits = {record["init_time"] for record in result.records.values()}
    assert inits == {PREV}, "FR4: members are never mixed across cycles"
    assert result.init_time == PREV
    assert len(result.records) == 64


def test_t19_a_mixed_cycle_record_is_a_hard_error(cache_root: Path):
    """The FR4 belt-and-braces guard: a fetcher that answers with the wrong init is caught."""

    def wrong_init(model: str, init_time: datetime, lead_h: int) -> dict:
        return {
            "model": model,
            "init_time": PREV,  # not the requested init
            "lead_h": lead_h,
            "valid_time": PREV + timedelta(hours=lead_h),
            "temp_f": 70.0,
            "grid_lat": 41.3,
            "grid_lon": -95.9,
            "distance_deg": 0.01,
        }

    with pytest.raises(RuntimeError) as excinfo:
        live.fetch_cycle(INIT, fetcher=wrong_init, cache_root=cache_root, now=NOW)
    assert "§5.2" in str(excinfo.value) or "FR4" in str(excinfo.value)


def test_t19_two_dead_candidates_fall_back_exactly_twice(cache_root: Path):
    older = INIT - timedelta(hours=12)
    table = full_table(INIT, PREV, older)
    table[INIT]["nam"] = set(GRID) - {GRID[0]}
    table[PREV]["nbm"] = set(GRID) - {GRID[0]}
    result = live.select_cycle(NOW, fetcher=RecordingFetcher(table), cache_root=cache_root)

    assert result.cycles_fallen_back == 2
    assert result.init_time == older
    assert len(result.fallback_reasons) == 2
    assert "nam" in result.fallback_reasons[0]
    assert "nbm" in result.fallback_reasons[1]


# --- T19a: the two-phase rule — an INTERIOR hole never falls back ------------------------


def test_t19a_a_model_missing_at_f012_does_not_fall_back(cache_root: Path):
    table = full_table(INIT, PREV)
    table[INIT]["nam"] = set(GRID) - {12}
    fetcher = RecordingFetcher(table)

    result = live.select_cycle(NOW, fetcher=fetcher, cache_root=cache_root)

    assert result.cycles_fallen_back == 0, "Phase B never fires the ladder (plan §0.4)"
    assert result.init_time == INIT
    assert result.fallback_reasons == ()
    assert fetcher.inits_requested == {INIT}, "no earlier candidate may be probed"


def test_t19a_the_interior_hole_becomes_a_gap_not_a_truncation(cache_root: Path):
    table = full_table(INIT, PREV)
    table[INIT]["nam"] = set(GRID) - {12}
    result = live.select_cycle(NOW, fetcher=RecordingFetcher(table), cache_root=cache_root)

    assert result.horizon_h == 48
    assert result.truncated is False
    assert [gap["lead_h"] for gap in result.gaps] == [12]
    assert result.gaps[0]["missing_models"] == ("nam",)


def test_t19a_phase_a_probes_the_first_grid_step_not_the_literal_three(cache_root: Path):
    """Phase A must move with the grid (plan §9.2)."""
    grid = (6, 12, 18)
    table = {INIT: {model: set(grid) for model in MODELS}}
    fetcher = RecordingFetcher(table)
    result = live.fetch_cycle(INIT, fetcher=fetcher, cache_root=cache_root, now=NOW, grid=grid)
    assert result is not None
    assert result.horizon_h == 18
    assert result.step_h == 6
    first_wave = [call for call in fetcher.calls if call[2] == grid[0]]
    assert len(first_wave) == len(MODELS)


# --- T20: all four candidates dead -------------------------------------------------------


def test_t20_an_empty_ladder_raises_no_cycle_available(cache_root: Path):
    fetcher = RecordingFetcher({})  # nothing is published anywhere
    with pytest.raises(live.NoCycleAvailable) as excinfo:
        live.select_cycle(NOW, fetcher=fetcher, cache_root=cache_root)
    assert isinstance(excinfo.value, RuntimeError)
    assert "§5.2" in str(excinfo.value)


def test_t20_the_error_names_every_candidate_and_its_reason(cache_root: Path):
    with pytest.raises(live.NoCycleAvailable) as excinfo:
        live.select_cycle(NOW, fetcher=RecordingFetcher({}), cache_root=cache_root)
    message = str(excinfo.value)
    candidates = cycle.candidate_cycles(cycle.target_cycle(NOW))
    assert len(candidates) == 4
    for init in candidates:
        assert live._iso(init) in message, f"{init} is not named in the failure"
        assert cycle.run_label(init) in message


def test_t20_only_phase_a_is_probed_on_a_dead_ladder(cache_root: Path):
    fetcher = RecordingFetcher({})
    with pytest.raises(live.NoCycleAvailable):
        live.select_cycle(NOW, fetcher=fetcher, cache_root=cache_root)
    assert len(fetcher.calls) == 4 * len(MODELS), "Phase B must never run on a dead cycle"
    assert {lead for (_m, _i, lead) in fetcher.calls} == {GRID[0]}


def test_t20_nothing_is_fabricated_and_no_payload_is_written(cache_root: Path):
    with pytest.raises(live.NoCycleAvailable):
        live.select_cycle(NOW, fetcher=RecordingFetcher({}), cache_root=cache_root)
    assert list(cache_root.rglob("forecast.json")) == []
    cached = list(cache_root.rglob("*_f*.json"))
    assert cached, "the missing outcomes are still cached — that is what makes FR8 real"
    for path in cached:
        assert live.read_cached(path)["status"] == "missing"


# --- T21: trailing holes TRUNCATE the horizon -------------------------------------------


def test_t21_trailing_nam_holes_at_f045_and_f048_truncate_the_horizon_to_42():
    records = records_for(GRID, absent={("nam", 45), ("nam", 48)})
    assert live.derive_horizon(records, GRID) == 42


def test_t21_the_horizon_is_derived_from_the_records_not_a_constant():
    """Move the hole and the answer must move with it."""
    assert live.derive_horizon(records_for(GRID, absent={("nam", 42), ("nam", 45),
                                                        ("nam", 48)}), GRID) == 39
    assert live.derive_horizon(records_for(GRID, absent={("nbm", 48)}), GRID) == 45
    assert live.derive_horizon(records_for(GRID), GRID) == 48


def test_t21_fetch_cycle_reports_truncation_and_the_grid_it_asked_for(cache_root: Path):
    table = full_table(INIT)
    table[INIT]["nam"] = set(GRID) - {45, 48}
    result = live.fetch_cycle(
        INIT, fetcher=RecordingFetcher(table), cache_root=cache_root, now=NOW
    )
    assert result is not None
    assert result.horizon_h == 42
    assert result.grid_max_lead_h == 48
    assert result.truncated is True
    assert result.gaps == (), "a trailing hole truncates; it is not an interior gap"


def test_t21_a_healthy_cycle_is_not_truncated(cache_root: Path):
    result = live.fetch_cycle(
        INIT, fetcher=RecordingFetcher(full_table(INIT)), cache_root=cache_root, now=NOW
    )
    assert result.horizon_h == result.grid_max_lead_h == 48
    assert result.truncated is False


def test_t21_covered_leads_needs_all_four_models():
    records = records_for(GRID, absent={("nam", 12)})
    covered = live.covered_leads(records)
    assert 12 not in covered
    assert set(covered) == set(GRID) - {12}


# --- T22: interior holes become named gaps; no weight rescaling helper exists ------------


def test_t22_a_gap_names_the_missing_models_and_its_reason():
    records = records_for(GRID, absent={("nam", 12), ("nbm", 12), ("gfs", 24)})
    gaps = live.find_gaps(records, GRID, horizon_h=48)
    by_lead = {gap["lead_h"]: gap for gap in gaps}

    assert sorted(by_lead) == [12, 24]
    assert by_lead[12]["missing_models"] == ("nam", "nbm")
    assert by_lead[24]["missing_models"] == ("gfs",)
    assert by_lead[12]["reason"] == "absent from archive"
    assert by_lead[12]["valid_time"] == INIT + timedelta(hours=12)
    for gap in gaps:
        for model in gap["missing_models"]:
            assert model == model.lower(), "model keys are lowercase throughout forecast/"


def test_t22_gaps_beyond_the_horizon_are_not_reported():
    records = records_for(GRID, absent={("nam", 12), ("nam", 45), ("nam", 48)})
    horizon = live.derive_horizon(records, GRID)
    assert horizon == 42
    gaps = live.find_gaps(records, GRID, horizon_h=horizon)
    assert [gap["lead_h"] for gap in gaps] == [12]


#: F2's own two modules. They produce values; they never apply weights. F3 (`forecast/build.py`,
#: `forecast/weights.py`) is where the fitted weights are read and applied.
F2_MODULES = frozenset({"cycle.py", "live.py"})


def test_t22_no_weight_rescaling_helper_exists_anywhere_in_forecast():
    """A gap is honest; a blend substituted over a subset of models is not (plan §0.4)."""
    package = Path(live.__file__).resolve().parent
    sources = sorted(package.glob("*.py"))
    assert sources, "the forecast package must have sources to scan"
    for source in sources:
        text = source.read_text(encoding="utf-8").lower()
        # The `renorm` ban is package-wide and permanent: the binding rule is that the weights
        # are NEVER renormalized over a subset of models. Never narrow this one.
        assert "renorm" not in text, f"{source.name} names a weight-rescaling helper"
        # The `weight` ban is deliberately scoped to F2's own two modules, and the scope is
        # load-bearing rather than an oversight. F3 legitimately reads the fitted weights and
        # applies them, in its own new modules (`forecast/build.py`, `forecast/weights.py`);
        # a package-wide ban here would fail the moment F3 lands and its only way forward
        # would be to delete this guard test. Do not widen it back, and do not delete it —
        # `cycle.py` and `live.py` must stay weight-free forever.
        if source.name in F2_MODULES:
            assert "weight" not in text, (
                f"{source.name} touches weights — F2 produces values, F3 applies weights"
            )
    assert not hasattr(live, "renormalize")


def test_t22_forecast_live_makes_no_http_calls_of_its_own():
    """F2 is a driver over `fetch.grib.fetch_point`; it opens no connection of its own."""
    text = Path(live.__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported & {"requests", "urllib", "http", "socket"} == set(), (
        f"forecast/live.py imports a network module: {sorted(imported)}"
    )
    for literal in ast.walk(tree):
        if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
            assert "s3.amazonaws" not in literal.value, "URLs belong to fetch/grib.py"


# --- T22a: §9 rule 8 disjointness --------------------------------------------------------


def test_t22a_a_gap_step_is_never_also_a_covered_step(cache_root: Path):
    table = full_table(INIT)
    table[INIT]["nam"] = set(GRID) - {12, 45, 48}
    result = live.fetch_cycle(
        INIT, fetcher=RecordingFetcher(table), cache_root=cache_root, now=NOW
    )
    covered = set(live.covered_leads(result.records))
    gap_leads = {gap["lead_h"] for gap in result.gaps}
    universe = {lead for lead in GRID if lead <= result.horizon_h}

    assert covered & gap_leads == set(), "a valid_time is in the forecast OR in gaps"
    assert (covered & universe) | gap_leads == universe, "never both, never neither"
    assert gap_leads == {12}
    assert result.horizon_h == 42


@pytest.mark.parametrize("holes", [set(), {("nam", 12)}, {("gfs", 6), ("nbm", 33)}])
def test_t22a_disjointness_holds_across_hole_patterns(holes: set):
    records = records_for(GRID, absent=holes)
    horizon = live.derive_horizon(records, GRID)
    gaps = live.find_gaps(records, GRID, horizon_h=horizon)
    covered = set(live.covered_leads(records))
    gap_leads = {gap["lead_h"] for gap in gaps}
    universe = {lead for lead in GRID if lead <= horizon}

    assert covered & gap_leads == set()
    assert (covered & universe) | gap_leads == universe


# --- an empty result is a failure, not a success ----------------------------------------


def test_a_cycle_result_with_zero_records_is_rejected():
    """An empty result scores perfectly and is fake (SPEC §10 / plan §10)."""
    with pytest.raises(RuntimeError) as excinfo:
        live.CycleResult(
            init_time=INIT,
            target_init_time=INIT,
            run_label="12z",
            fetched_at=FETCHED_AT,
            age_minutes=293,
            is_stale=False,
            stale_reason=None,
            cycles_fallen_back=0,
            step_h=3,
            horizon_h=48,
            grid_max_lead_h=48,
            truncated=False,
            records={},
            gaps=(),
            fallback_reasons=(),
        )
    assert "record" in str(excinfo.value).lower()


def test_cycle_result_is_frozen(cache_root: Path):
    result = live.fetch_cycle(
        INIT, fetcher=RecordingFetcher(full_table(INIT)), cache_root=cache_root, now=NOW
    )
    with pytest.raises(Exception):
        result.horizon_h = 12


def test_cycle_result_documents_the_lowercase_key_convention():
    doc = live.CycleResult.__doc__ or ""
    assert "lowercase" in doc.lower()
    assert "F3" in doc


def test_derive_horizon_on_an_empty_grid_is_an_error():
    with pytest.raises(RuntimeError):
        live.derive_horizon(records_for(GRID), ())


def test_fetch_leads_submits_nothing_when_everything_is_cached(cache_root: Path):
    fetcher = RecordingFetcher(full_table(INIT))
    live.fetch_leads(INIT, GRID, fetcher=fetcher, cache_root=cache_root)
    assert len(fetcher.calls) == 64
    again = live.fetch_leads(INIT, GRID, fetcher=raising_fetcher, cache_root=cache_root)
    assert len(again) == 64
    assert set(again) == {(model, lead) for lead in GRID for model in MODELS}


def test_fetch_leads_uses_eight_workers_and_no_more():
    """8 is the spike-F2-validated number; the decode is GIL-bound (plan §10)."""
    assert live.WORKERS == 8
