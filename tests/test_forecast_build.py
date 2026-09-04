"""F3 Stream 4 — `forecast/build.py`, the §9 document assembled from a fetched cycle.

Every test here is offline. The real-cache tests read `data/live/2026090412/` (64 JSON files
written by F2's live fetch) into a **copy under `tmp_path`**, so nothing in this module writes
to the repository's `data/` directory, and the fetcher injected into `fetch_cycle` raises on
any call at all — a cache miss fails the test rather than opening a socket.

The highest-value test in the file is `test_real_cache_blend_identity`: it recomputes
`sum(weights[m] * members[m])` from each row's **own** published numbers and requires it to
equal the published `blend_f` to 1e-6, over all 64 real records.
`test_blend_identity_has_teeth` proves that check can fail, by perturbing one `blend_f` by
1e-3 and requiring the validator to reject it.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fetch.grib import MODELS, valid_time
from forecast import cycle as cycle_mod
from forecast.build import build_forecast_document, model_case_map
from forecast.build import _members_at as members_at
from forecast.contract import ContractError, validate_forecast
from forecast.live import (
    PROBE_PUBLISHED_LEADS,
    CycleResult,
    derive_horizon,
    fetch_cycle,
    find_gaps,
    step_grid,
)
from forecast.weights import FittedWeights, load_fitted_weights

REPO = Path(__file__).resolve().parent.parent
REAL_CACHE = REPO / "data" / "live" / "2026090412"
RESULTS = REPO / "data" / "results.json"

INIT = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc)
GENERATED_AT = datetime(2026, 9, 4, 17, 4, 12, tzinfo=timezone.utc)

PAYLOAD_MODELS = ("HRRR", "GFS", "NAM", "NBM")

#: Per-model offsets with long decimal tails, so rounding members to 4 dp is a real operation
#: rather than a no-op that would make the identity test pass for the wrong reason.
OFFSET = {"hrrr": 0.0, "gfs": 1.0 / 3.0, "nam": -2.0 / 7.0, "nbm": 5.0 / 11.0}


# --------------------------------------------------------------------------- synthetic data


def no_network(model: str, init: datetime, lead: int) -> dict:
    """The injected fetcher. Any call at all is a bug in the test, never a network trip."""
    raise RuntimeError(
        f"SPEC §13 forbids live-network tests: the cache must answer every request, but "
        f"{model} f{lead:03d} for {init.isoformat()} was asked of the archive"
    )


def synthetic_temp(model: str, lead: int) -> float:
    return 70.0 + lead / 7.0 + OFFSET[model]


def synthetic_record(model: str, lead: int, *, status: str = "success") -> dict:
    """One cache record in F2's locked schema, with datetimes already tz-aware."""
    return {
        "model": model,
        "init_time": INIT,
        "lead_h": lead,
        "valid_time": valid_time(INIT, lead),
        "status": status,
        "temp_f": synthetic_temp(model, lead) if status == "success" else None,
        "grid_lat": 41.25,
        "grid_lon": -96.0,
        "distance_deg": 0.1185,
        "error": None if status == "success" else "absent from archive",
        "fetched_at": NOW,
    }


def synthetic_records(
    grid: tuple[int, ...],
    *,
    absent: tuple[tuple[str, int], ...] = (),
    dropped: tuple[tuple[str, int], ...] = (),
) -> dict[tuple[str, int], dict]:
    """`{(model, lead): record}` over `grid`; `absent` settle `missing`, `dropped` have no file."""
    records: dict[tuple[str, int], dict] = {}
    for lead in grid:
        for model in MODELS:
            if (model, lead) in dropped:
                continue
            status = "missing" if (model, lead) in absent else "success"
            records[(model, lead)] = synthetic_record(model, lead, status=status)
    return records


def synthetic_cycle(
    records: dict[tuple[str, int], dict],
    grid: tuple[int, ...],
    *,
    cycles_fallen_back: int = 0,
    now: datetime = NOW,
) -> CycleResult:
    """A `CycleResult` built exactly as `fetch_cycle` builds one — no network, no cache."""
    horizon_h = derive_horizon(records, grid)
    age = cycle_mod.age_minutes(INIT, now)
    is_stale, stale_reason = cycle_mod.staleness(cycles_fallen_back, age)
    target = INIT + timedelta(hours=cycle_mod.INIT_STEP_H * cycles_fallen_back)
    return CycleResult(
        init_time=INIT,
        target_init_time=target,
        run_label=cycle_mod.run_label(INIT),
        fetched_at=now,
        age_minutes=age,
        is_stale=is_stale,
        stale_reason=stale_reason,
        cycles_fallen_back=cycles_fallen_back,
        step_h=grid[1] - grid[0],
        horizon_h=horizon_h,
        grid_max_lead_h=grid[-1],
        truncated=horizon_h < grid[-1],
        records=records,
        gaps=find_gaps(records, grid, horizon_h),
        fallback_reasons=(),
    )


def synthetic_fitted() -> FittedWeights:
    """A `FittedWeights` with the real file's shape but fabricated, on-grid vectors."""
    window = {"start": "2026-08-04T12:00:00Z", "end": "2026-09-04T00:00:00Z", "days": 30}
    return FittedWeights(
        vectors={
            6: {"HRRR": 0.5, "GFS": 0.0, "NAM": 0.1, "NBM": 0.4},
            12: {"HRRR": 0.3, "GFS": 0.2, "NAM": 0.1, "NBM": 0.4},
            24: {"HRRR": 0.1, "GFS": 0.3, "NAM": 0.2, "NBM": 0.4},
        },
        fitted_leads=(6, 12, 24),
        models_included=PAYLOAD_MODELS,
        site={
            "id": "KOMA",
            "iem_station": "OMA",
            "name": "Omaha Eppley Airfield",
            "lat": 41.3032,
            "lon": -95.8941,
            "station_elev_m": 295.7,
        },
        weights_source={
            "path": "data/results.json",
            "generated_at": "2026-09-04T12:53:01Z",
            "weights_age_days": 0,
            "window": copy.deepcopy(window),
            "split": {"method": "chronological", "train_days": 20, "test_days": 10},
            "fitted_leads": [6, 12, 24],
        },
        skill={
            "basis": "historical_out_of_sample",
            "window": copy.deepcopy(window),
            "note": "Measured over the backtest window. History, not a prediction.",
            "by_lead": [
                {
                    "lead_h": lead,
                    "blend_mae": 1.9 + lead / 100.0,
                    "blend_mae_in_sample": 1.7 + lead / 100.0,
                    "best_single_model": "HRRR",
                    "best_single_mae": 2.1 + lead / 100.0,
                    "improvement_pct": 9.02,
                    "n_test": 40,
                    "independent_days_approx": 30,
                }
                for lead in (6, 12, 24)
            ],
        },
    )


def full_grid() -> tuple[int, ...]:
    return tuple(step_grid())


def build_synthetic(**kwargs) -> dict:
    """Build over the whole probe grid with the synthetic fitted weights."""
    grid = full_grid()
    records = synthetic_records(grid, **kwargs)
    return build_forecast_document(synthetic_cycle(records, grid), synthetic_fitted(), GENERATED_AT)


def leads_of(rows: list[dict]) -> list[int]:
    return [row["lead_h"] for row in rows]


def recompute_blend(row: dict) -> float:
    """Σ w·m from the row's **own** published numbers — never from the builder's."""
    return sum(row["weights"][model] * row["members"][model] for model in row["members"])


# --------------------------------------------------------------------------- the real cache


@pytest.fixture()
def real_cycle(tmp_path: Path) -> CycleResult:
    """The real 12z cycle, rebuilt from a **copy** of the cache with a raising fetcher."""
    if not REAL_CACHE.is_dir():
        pytest.skip(
            f"the real live cache {REAL_CACHE} is absent; this build cannot be exercised "
            "against real data here, and it is skipped rather than silently passed"
        )
    root = tmp_path / "live"
    shutil.copytree(REAL_CACHE, root / REAL_CACHE.name)
    return fetch_cycle(INIT, fetcher=no_network, cache_root=root, now=NOW)


@pytest.fixture()
def real_fitted() -> FittedWeights:
    if not RESULTS.exists():
        pytest.skip(f"{RESULTS} is absent; run `uv run --no-sync python -m score.run` first")
    return load_fitted_weights(RESULTS, now=NOW)


@pytest.fixture()
def real_document(real_cycle: CycleResult, real_fitted: FittedWeights) -> dict:
    return build_forecast_document(real_cycle, real_fitted, GENERATED_AT)


def test_real_cache_build_validates_and_reports_the_recorded_shape(
    real_cycle: CycleResult, real_document: dict
) -> None:
    """The acceptance criterion: the real cache builds a document of the recorded shape."""
    assert len(real_cycle.records) == 64, (
        f"the real cache is 4 models x 16 leads; got {len(real_cycle.records)} records"
    )

    validate_forecast(real_document)  # build already validates; this states the contract

    meta = real_document["meta"]
    assert meta["horizon_h"] == 48, meta["horizon_h"]
    assert meta["step_h"] == 3, meta["step_h"]
    assert len(real_document["forecast"]) == 16, leads_of(real_document["forecast"])
    assert real_document["gaps"] == [], real_document["gaps"]
    assert meta["cycle"]["is_stale"] is False
    assert meta["cycle"]["stale_reason"] is None
    assert meta["cycle"]["init_time"] == "2026-09-04T12:00:00Z"
    assert meta["cycle"]["run_label"] == "12z"
    assert meta["is_synthetic"] is False
    assert meta["source"] == "noaa_s3_grib"
    assert meta["variable"] == "2m_temperature"
    assert meta["units"] == "degF"
    assert meta["models_included"] == list(PAYLOAD_MODELS)


def test_real_cache_blend_identity(real_document: dict) -> None:
    """§9 rule 6 over every real row, recomputed from the row's own published numbers.

    This is the forward twin of T5's one-hot identity test. If the displayed number is not the
    weighted sum of its members, the page is showing a number with no provenance.
    """
    rows = real_document["forecast"]
    assert rows, "no rows to check — this test would otherwise pass vacuously"
    for row in rows:
        assert row["blend_f"] == pytest.approx(recompute_blend(row), abs=1e-6), (
            f"lead {row['lead_h']} h: blend_f {row['blend_f']} is not Σ w·m "
            f"{recompute_blend(row)}"
        )
        expected_spread = max(row["members"].values()) - min(row["members"].values())
        assert row["member_spread_f"] == pytest.approx(expected_spread, abs=1e-6)


def test_real_cache_site_is_copied_verbatim(
    real_document: dict, real_fitted: FittedWeights
) -> None:
    assert real_document["meta"]["site"] == real_fitted.site
    assert real_document["meta"]["site"] is not real_fitted.site, "site must be a copy"
    assert real_document["skill"] == real_fitted.skill
    assert real_document["meta"]["weights_source"] == real_fitted.weights_source


def test_real_cache_members_carry_the_lowercase_record_values(
    real_cycle: CycleResult, real_document: dict
) -> None:
    """The casing bridge over real data: no member is dropped, and none is invented."""
    for row in real_document["forecast"]:
        assert set(row["members"]) == set(PAYLOAD_MODELS), sorted(row["members"])
        for payload_name in PAYLOAD_MODELS:
            record = real_cycle.records[(payload_name.lower(), row["lead_h"])]
            assert row["members"][payload_name] == round(record["temp_f"], 4)


def test_real_cache_blend_is_not_display_rounded(real_document: dict) -> None:
    """`blend_f` is serialized unrounded (D-F3-C); rounding for display is the page's job."""
    unrounded = [
        row for row in real_document["forecast"] if round(row["blend_f"], 2) != row["blend_f"]
    ]
    assert unrounded, "every blend_f happened to land on 2 dp — this test has gone blind"


def test_blend_identity_has_teeth(real_document: dict) -> None:
    """A 1e-3 perturbation must be rejected, or the identity test above proves nothing."""
    tampered = copy.deepcopy(real_document)
    tampered["forecast"][0]["blend_f"] += 1e-3

    with pytest.raises(ContractError) as excinfo:
        validate_forecast(tampered)
    assert "forecast[0].blend_f" in str(excinfo.value), str(excinfo.value)


# --------------------------------------------------------------------------- casing bridge


def test_case_map_is_total_over_the_fetched_models() -> None:
    assert model_case_map(PAYLOAD_MODELS) == {
        "hrrr": "HRRR",
        "gfs": "GFS",
        "nam": "NAM",
        "nbm": "NBM",
    }
    assert set(model_case_map(PAYLOAD_MODELS)) == set(MODELS)


def test_synthetic_build_drops_no_member_to_casing() -> None:
    document = build_synthetic()
    for row in document["forecast"]:
        assert list(row["members"]) == list(PAYLOAD_MODELS), list(row["members"])
        assert list(row["weights"]) == list(PAYLOAD_MODELS), list(row["weights"])
        for payload_name in PAYLOAD_MODELS:
            expected = round(synthetic_temp(payload_name.lower(), row["lead_h"]), 4)
            assert row["members"][payload_name] == expected


def test_an_unexpected_model_key_in_the_records_raises() -> None:
    grid = full_grid()
    records = synthetic_records(grid)
    stray = synthetic_record("hrrr", grid[0])
    stray["model"] = "ecmwf"
    records[("ecmwf", grid[0])] = stray

    with pytest.raises(ContractError) as excinfo:
        build_forecast_document(synthetic_cycle(records, grid), synthetic_fitted(), GENERATED_AT)
    assert "ecmwf" in str(excinfo.value), str(excinfo.value)


def test_a_fitted_member_set_that_is_not_the_fetched_one_raises() -> None:
    grid = full_grid()
    fitted = dataclasses.replace(synthetic_fitted(), models_included=("HRRR", "GFS", "NAM"))

    with pytest.raises(ContractError) as excinfo:
        build_forecast_document(
            synthetic_cycle(synthetic_records(grid), grid), fitted, GENERATED_AT
        )
    message = str(excinfo.value)
    assert "models_included" in message, message
    assert "NBM" not in fitted.models_included


def test_a_partial_member_set_reaching_the_row_builder_raises() -> None:
    """The belt-and-braces guard: such a step is declared in gaps, never blended."""
    grid = full_grid()
    records = synthetic_records(grid, dropped=(("nam", grid[1]),))
    case_map = model_case_map(PAYLOAD_MODELS)

    with pytest.raises(ContractError) as excinfo:
        members_at(records, grid[1], case_map)
    message = str(excinfo.value)
    assert "NAM" in message, message
    assert "weights are never rescaled over a subset of models" in message, message


# --------------------------------------------------------------------------- holes


def test_an_interior_hole_becomes_a_gap_and_leaves_the_other_rows_untouched() -> None:
    grid = full_grid()
    hole = 12

    complete = build_synthetic()
    holed = build_synthetic(absent=(("nam", hole),))

    assert holed["gaps"] == [
        {
            "valid_time": "2026-09-05T00:00:00Z",
            "lead_h": hole,
            "missing_models": ["NAM"],
            "reason": "absent from archive",
        }
    ], holed["gaps"]
    assert hole not in leads_of(holed["forecast"])
    assert holed["meta"]["horizon_h"] == complete["meta"]["horizon_h"] == grid[-1]
    assert len(holed["forecast"]) == len(complete["forecast"]) - 1

    # The no-rescaling proof: every surviving row's vector is byte-identical to the no-gap
    # build's. A rescaled vector over the three survivors would look entirely ordinary here.
    def vectors(document: dict) -> dict[int, str]:
        return {
            row["lead_h"]: json.dumps(row["weights"], sort_keys=True)
            for row in document["forecast"]
        }

    before = vectors(complete)
    after = vectors(holed)
    assert set(after) == set(before) - {hole}
    for lead, serialized in after.items():
        assert serialized == before[lead], f"lead {lead} h: weights changed when a gap appeared"


def test_a_trailing_hole_truncates_the_horizon_and_declares_no_gap_above_it() -> None:
    grid = full_grid()
    tail = grid[-2:]
    document = build_synthetic(absent=tuple(("nam", lead) for lead in tail))

    assert document["meta"]["horizon_h"] == grid[-3]
    assert document["gaps"] == [], document["gaps"]
    assert leads_of(document["forecast"]) == [lead for lead in grid if lead <= grid[-3]]
    for row in document["forecast"]:
        assert row["blend_f"] == pytest.approx(recompute_blend(row), abs=1e-6)


def test_an_interior_hole_and_a_truncated_tail_together_still_validate() -> None:
    grid = full_grid()
    hole = 12
    tail = grid[-2:]
    absent = ((("nam", hole),) + tuple(("gfs", lead) for lead in tail))
    document = build_synthetic(absent=absent)

    validate_forecast(document)
    assert document["meta"]["horizon_h"] == grid[-3]
    assert [gap["lead_h"] for gap in document["gaps"]] == [hole]
    assert hole not in leads_of(document["forecast"])
    assert max(leads_of(document["forecast"])) == grid[-3]


# --------------------------------------------------------------------------- no grid literals


def test_the_grid_comes_from_the_cycle_not_from_a_constant() -> None:
    """Change the probe table and both `horizon_h` and the row count must move with it.

    A test that would still pass with `48` hardcoded in `build.py` is not this test.
    """
    trimmed_table = dict(PROBE_PUBLISHED_LEADS)
    trimmed_table["nam"] = tuple(lead for lead in trimmed_table["nam"] if lead <= 36)

    wide = full_grid()
    narrow = tuple(step_grid(published=trimmed_table))
    assert narrow != wide and narrow[-1] < wide[-1], (narrow[-1], wide[-1])

    documents = {}
    for name, grid in (("wide", wide), ("narrow", narrow)):
        records = synthetic_records(grid)
        documents[name] = build_forecast_document(
            synthetic_cycle(records, grid), synthetic_fitted(), GENERATED_AT
        )

    assert documents["wide"]["meta"]["horizon_h"] == wide[-1]
    assert documents["narrow"]["meta"]["horizon_h"] == narrow[-1]
    assert documents["wide"]["meta"]["horizon_h"] != documents["narrow"]["meta"]["horizon_h"]

    assert len(documents["wide"]["forecast"]) == len(wide)
    assert len(documents["narrow"]["forecast"]) == len(narrow)
    assert len(documents["wide"]["forecast"]) != len(documents["narrow"]["forecast"])

    assert documents["wide"]["meta"]["step_h"] == wide[1] - wide[0]
    assert documents["narrow"]["meta"]["step_h"] == narrow[1] - narrow[0]


# --------------------------------------------------------------------------- banding, staleness


def test_banding_marks_the_extrapolated_region_and_carries_the_longest_fitted_vector() -> None:
    document = build_synthetic()
    fitted = synthetic_fitted()
    longest = max(fitted.fitted_leads)
    rows = {row["lead_h"]: row for row in document["forecast"]}

    assert rows[longest]["is_extrapolated_lead"] is False
    assert rows[longest]["weights_fitted_at_lead_h"] == longest

    beyond = [lead for lead in rows if lead > longest]
    assert beyond, "no lead beyond the fitted range — this test would pass vacuously"
    for lead in beyond:
        assert rows[lead]["is_extrapolated_lead"] is True, lead
        assert rows[lead]["weights_fitted_at_lead_h"] == longest, lead
        assert rows[lead]["weights"] == fitted.vectors[longest], lead

    assert rows[6]["weights_fitted_at_lead_h"] == 6
    assert rows[3]["weights_fitted_at_lead_h"] == 6
    assert rows[3]["is_extrapolated_lead"] is False


def test_a_stale_cycle_is_flagged_with_a_reason_and_still_validates() -> None:
    grid = full_grid()
    records = synthetic_records(grid)
    now = INIT + timedelta(hours=7)
    stale_cycle = synthetic_cycle(records, grid, cycles_fallen_back=1, now=now)

    document = build_forecast_document(
        stale_cycle, synthetic_fitted(), now + timedelta(minutes=4)
    )
    validate_forecast(document)

    meta_cycle = document["meta"]["cycle"]
    assert meta_cycle["is_stale"] is True
    assert meta_cycle["stale_reason"], meta_cycle
    assert meta_cycle["cycles_fallen_back"] == 1
    assert meta_cycle["target_init_time"] > meta_cycle["init_time"]
    assert meta_cycle["age_minutes"] == 420


def test_the_cycle_block_carries_the_eight_locked_keys_and_no_more() -> None:
    """D-F3-D: F2's internal `truncated` and `grid_max_lead_h` stay internal."""
    document = build_synthetic()
    assert set(document["meta"]["cycle"]) == {
        "init_time",
        "run_label",
        "target_init_time",
        "fetched_at",
        "age_minutes",
        "is_stale",
        "stale_reason",
        "cycles_fallen_back",
    }
    assert "truncated" not in json.dumps(document)
    assert "grid_max_lead_h" not in json.dumps(document)


def test_rows_are_ascending_and_serialized_as_iso_z_stamps() -> None:
    document = build_synthetic()
    stamps = [row["valid_time"] for row in document["forecast"]]
    assert stamps == sorted(stamps)
    for stamp in stamps:
        assert stamp.endswith("Z"), stamp
        assert len(stamp) == len("2026-09-04T15:00:00Z"), stamp
    assert document["meta"]["generated_at"] == "2026-09-04T17:04:12Z"
    assert document["forecast"][0]["valid_time"] == "2026-09-04T15:00:00Z"


def test_members_are_stored_at_four_decimal_places() -> None:
    document = build_synthetic()
    for row in document["forecast"]:
        for value in row["members"].values():
            assert value == round(value, 4)
    raw = synthetic_temp("gfs", document["forecast"][0]["lead_h"])
    assert raw != round(raw, 4), "the synthetic values must have a decimal tail to round"
