"""Executable proof that `forecast.contract.validate_forecast` locks the §9 shape.

Every negative case asserts on the *message text*, not merely that something raised —
a validator that rejects everything for the wrong reason is worse than no validator
(the rule `tests/test_results_contract.py` set for the backtest payload).

Hermetic: no network, no server, and nothing under `data/` is read or written. The
document under test is built in memory by `build_doc()` so that FORECAST-SPEC §9
rule 6 holds *by construction* — `blend_f` is computed from the weights and members
rather than transcribed, which is the only way a happy-path fixture can prove the
identity instead of merely agreeing with a number someone typed.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecast import contract as fc
from forecast.contract import (
    ContractError,
    band_for_lead,
    is_extrapolated_lead,
    load_and_validate_forecast,
    validate_forecast,
    write_atomic,
)

MODELS = ["HRRR", "GFS", "NAM", "NBM"]
FITTED_LEADS = [6, 12, 24]
INIT_TIME = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

WEIGHTS_BY_BAND: dict[int, dict[str, float]] = {
    6: {"HRRR": 0.5, "GFS": 0.0, "NAM": 0.1, "NBM": 0.4},
    12: {"HRRR": 0.3, "GFS": 0.2, "NAM": 0.1, "NBM": 0.4},
    24: {"HRRR": 0.2, "GFS": 0.3, "NAM": 0.0, "NBM": 0.5},
}
MODEL_OFFSETS = {"HRRR": 0.0, "GFS": 1.7, "NAM": -0.55, "NBM": 0.3}


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_for_lead(lead_h: float) -> str:
    return stamp(INIT_TIME + timedelta(hours=lead_h))


def members_for_lead(lead_h: int) -> dict[str, float]:
    base = 70.0 + lead_h * 0.15
    return {
        model: round(base + offset * (1.0 + lead_h / 100.0), 2)
        for model, offset in MODEL_OFFSETS.items()
    }


def make_row(lead_h: int) -> dict:
    """A row that satisfies rules 3-7 by construction — nothing is transcribed."""
    band = band_for_lead(lead_h, FITTED_LEADS)
    weights = dict(WEIGHTS_BY_BAND[band])
    members = members_for_lead(lead_h)
    return {
        "valid_time": stamp_for_lead(lead_h),
        "lead_h": lead_h,
        "blend_f": sum(weights[m] * members[m] for m in MODELS),
        "weights": weights,
        "weights_fitted_at_lead_h": band,
        "is_extrapolated_lead": is_extrapolated_lead(lead_h, FITTED_LEADS),
        "members": members,
        "member_spread_f": max(members.values()) - min(members.values()),
    }


def make_gap(lead_h: int, missing: tuple[str, ...] = ("NAM",)) -> dict:
    return {
        "valid_time": stamp_for_lead(lead_h),
        "lead_h": lead_h,
        "missing_models": list(missing),
        "reason": "beyond model horizon",
    }


def make_skill_entry(lead_h: int) -> dict:
    return {
        "lead_h": lead_h,
        "blend_mae": 1.5 + lead_h * 0.05,
        "blend_mae_in_sample": 1.3 + lead_h * 0.05,
        "best_single_model": "HRRR",
        "best_single_mae": 1.7 + lead_h * 0.05,
        "improvement_pct": 4.25,
        "n_test": 40,
        "independent_days_approx": 30,
    }


def build_doc(
    horizon_h: int = 48,
    step_h: int = 3,
    gap_leads: tuple[int, ...] = (48,),
) -> dict:
    universe = list(range(step_h, horizon_h + 1, step_h))
    return {
        "meta": {
            "site": {
                "id": "KOMA",
                "iem_station": "OMA",
                "name": "Omaha Eppley Airfield",
                "lat": 41.3103,
                "lon": -95.8991,
                "station_elev_m": 299.0,
            },
            "variable": "2m_temperature",
            "units": "degF",
            "cycle": {
                "init_time": stamp(INIT_TIME),
                "run_label": "12z",
                "target_init_time": stamp(INIT_TIME),
                "fetched_at": "2026-09-04T17:04:00Z",
                "age_minutes": 304,
                "is_stale": False,
                "stale_reason": None,
                "cycles_fallen_back": 0,
            },
            "weights_source": {
                "path": "data/results.json",
                "generated_at": "2026-09-04T12:53:01Z",
                "weights_age_days": 0,
                "window": {
                    "start": "2026-08-05T00:00:00Z",
                    "end": "2026-09-04T00:00:00Z",
                    "days": 30,
                },
                "split": {"method": "chronological", "train_days": 20, "test_days": 10},
                "fitted_leads": list(FITTED_LEADS),
            },
            "models_included": list(MODELS),
            "horizon_h": horizon_h,
            "step_h": step_h,
            "source": "noaa_s3_grib",
            "generated_at": "2026-09-04T17:04:12Z",
            "is_synthetic": False,
        },
        "forecast": [make_row(lead) for lead in universe if lead not in gap_leads],
        "gaps": [make_gap(lead) for lead in gap_leads],
        "skill": {
            "basis": "historical_out_of_sample",
            "window": {
                "start": "2026-08-05T00:00:00Z",
                "end": "2026-09-04T00:00:00Z",
                "days": 30,
            },
            "note": (
                "Measured over the 30-day backtest window. History, not a prediction "
                "about this forecast."
            ),
            "by_lead": [make_skill_entry(lead) for lead in FITTED_LEADS],
        },
    }


@pytest.fixture()
def doc() -> dict:
    return copy.deepcopy(build_doc())


def _message(document: dict) -> str:
    with pytest.raises(ContractError) as excinfo:
        validate_forecast(document)
    return str(excinfo.value)


def _row_index(document: dict, lead_h: int) -> int:
    return next(i for i, row in enumerate(document["forecast"]) if row["lead_h"] == lead_h)


# --------------------------------------------------------------------------- happy path


def test_canonical_document_validates() -> None:
    assert validate_forecast(build_doc()) is None


def test_canonical_document_covers_the_whole_step_grid() -> None:
    document = build_doc()
    leads = [row["lead_h"] for row in document["forecast"]]
    leads += [gap["lead_h"] for gap in document["gaps"]]
    assert sorted(leads) == list(range(3, 49, 3))


def test_disjoint_and_total_over_a_truncated_horizon() -> None:
    """Rule 8 is derived from meta alone, so a shorter horizon is just as complete."""
    document = build_doc(horizon_h=12, gap_leads=(12,))
    assert validate_forecast(document) is None
    assert [row["lead_h"] for row in document["forecast"]] == [3, 6, 9]


def test_negative_improvement_is_accepted(doc: dict) -> None:
    """SPEC §10: the validator checks arithmetic, never the verdict."""
    doc["skill"]["by_lead"][0]["improvement_pct"] = -18.4
    assert validate_forecast(doc) is None


def test_gap_reason_text_is_not_pinned(doc: dict) -> None:
    """F2 says "absent from archive"; §9's example says "beyond model horizon"."""
    doc["gaps"][0]["reason"] = "absent from archive"
    assert validate_forecast(doc) is None


# ------------------------------------------------------------------- §6.2 banned names


BANNED_INJECTIONS = [
    ("confidence", "confidence", lambda d: d),
    ("meta.confidence_pct", "confidence_pct", lambda d: d["meta"]),
    ("meta.cycle.probability", "probability", lambda d: d["meta"]["cycle"]),
    ("meta.site.p10", "p10", lambda d: d["meta"]["site"]),
    ("meta.weights_source.p50", "p50", lambda d: d["meta"]["weights_source"]),
    ("forecast[0].p90", "p90", lambda d: d["forecast"][0]),
    ("forecast[0].members.percentile", "percentile", lambda d: d["forecast"][0]["members"]),
    ("forecast[0].weights.ci_low", "ci_low", lambda d: d["forecast"][0]["weights"]),
    ("gaps[0].ci_high", "ci_high", lambda d: d["gaps"][0]),
    ("skill.error_bar", "error_bar", lambda d: d["skill"]),
    ("skill.by_lead[0].uncertainty", "uncertainty", lambda d: d["skill"]["by_lead"][0]),
]


@pytest.mark.parametrize(
    ("path", "name", "target"),
    BANNED_INJECTIONS,
    ids=[case[0] for case in BANNED_INJECTIONS],
)
def test_banned_field_name_is_rejected_at_every_level(
    doc: dict, path: str, name: str, target
) -> None:
    target(doc)[name] = 0.5
    message = _message(doc)
    assert message.startswith(f"{path}:")
    assert "§6.2" in message


def test_every_banned_name_in_the_spec_list_is_covered() -> None:
    """The eleven cases above must be the eleven names, not ten of them."""
    assert {case[1] for case in BANNED_INJECTIONS} == set(fc.BANNED_FIELD_NAMES)
    assert len(BANNED_INJECTIONS) == 11


def test_an_ordinary_unexpected_key_is_still_rejected(doc: dict) -> None:
    doc["meta"]["cycle"]["truncated"] = True
    message = _message(doc)
    assert message.startswith("meta.cycle:")
    assert "unexpected key(s) ['truncated']" in message
    assert "§9 shape is locked" in message


def test_grid_max_lead_h_is_not_part_of_the_document(doc: dict) -> None:
    doc["meta"]["grid_max_lead_h"] = 48
    message = _message(doc)
    assert message.startswith("meta:")
    assert "grid_max_lead_h" in message


# ------------------------------------------------------------------------ rules 2 and 3


def test_unsorted_forecast_is_rejected(doc: dict) -> None:
    doc["forecast"][0], doc["forecast"][1] = doc["forecast"][1], doc["forecast"][0]
    message = _message(doc)
    assert message.startswith("forecast[1].valid_time:")
    assert "strictly ascending" in message


def test_duplicate_valid_time_is_rejected(doc: dict) -> None:
    doc["forecast"][1]["valid_time"] = doc["forecast"][0]["valid_time"]
    message = _message(doc)
    assert message.startswith("forecast[1].valid_time:")
    assert "duplicates" in message


def test_lead_h_inconsistent_with_valid_time_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["lead_h"] = 9
    message = _message(doc)
    assert message.startswith("forecast[0].lead_h:")
    assert "is 9 but valid_time is 3 h after meta.cycle.init_time" in message


def test_half_hour_offset_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["valid_time"] = stamp_for_lead(3.5)
    message = _message(doc)
    assert message.startswith("forecast[0].lead_h:")
    assert "not a whole number of hours" in message


# ---------------------------------------------------------------------------- rule 4


def test_weight_keys_must_be_exactly_models_included(doc: dict) -> None:
    doc["forecast"][0]["weights"].pop("NAM")
    message = _message(doc)
    assert message.startswith("forecast[0].weights:")
    assert "keys must be exactly meta.models_included" in message


def test_off_grid_weight_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["weights"] = {"HRRR": 0.5, "GFS": 0.0, "NAM": 0.15, "NBM": 0.35}
    message = _message(doc)
    assert message.startswith("forecast[0].weights.NAM:")
    assert "multiple of 0.1" in message


def test_weights_that_do_not_sum_to_one_are_rejected(doc: dict) -> None:
    doc["forecast"][0]["weights"] = {"HRRR": 0.5, "GFS": 0.0, "NAM": 0.1, "NBM": 0.39}
    message = _message(doc)
    assert message.startswith("forecast[0].weights:")
    assert "must sum to 1.0" in message


def test_negative_weight_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["weights"] = {"HRRR": 0.7, "GFS": 0.0, "NAM": -0.1, "NBM": 0.4}
    message = _message(doc)
    assert message.startswith("forecast[0].weights.NAM:")
    assert "must lie in [0, 1]" in message


# ---------------------------------------------------------------------------- rule 5


def test_weights_fitted_at_a_lead_that_was_never_fitted_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["weights_fitted_at_lead_h"] = 9
    message = _message(doc)
    assert message.startswith("forecast[0].weights_fitted_at_lead_h:")
    assert "not one of meta.weights_source.fitted_leads" in message


def test_wrong_band_is_rejected_where_the_table_says_24(doc: dict) -> None:
    index = _row_index(doc, 21)
    doc["forecast"][index]["weights_fitted_at_lead_h"] = 12
    message = _message(doc)
    assert message.startswith(f"forecast[{index}].weights_fitted_at_lead_h:")
    assert "maps a 21 h lead to the 24 h fitted vector" in message


def test_extrapolated_flag_false_at_27_hours_is_rejected(doc: dict) -> None:
    index = _row_index(doc, 27)
    doc["forecast"][index]["is_extrapolated_lead"] = False
    message = _message(doc)
    assert message.startswith(f"forecast[{index}].is_extrapolated_lead:")
    assert "beyond the longest fitted lead (24 h)" in message


def test_extrapolated_flag_true_at_24_hours_is_rejected(doc: dict) -> None:
    index = _row_index(doc, 24)
    doc["forecast"][index]["is_extrapolated_lead"] = True
    message = _message(doc)
    assert message.startswith(f"forecast[{index}].is_extrapolated_lead:")
    assert "is not beyond the longest fitted lead" in message


# ------------------------------------------------------------------------ rules 6, 6b


def test_blend_f_perturbed_by_a_thousandth_is_rejected(doc: dict) -> None:
    doc["forecast"][4]["blend_f"] += 1e-3
    message = _message(doc)
    assert message.startswith("forecast[4].blend_f:")
    assert "weighted sum of its members" in message
    assert "never repaired" in message


def test_blend_f_perturbed_by_a_billionth_is_accepted(doc: dict) -> None:
    """The 1e-6 tolerance is deliberate, not a rounding accident."""
    doc["forecast"][4]["blend_f"] += 1e-9
    assert validate_forecast(doc) is None


def test_member_spread_perturbed_by_a_thousandth_is_rejected(doc: dict) -> None:
    doc["forecast"][2]["member_spread_f"] += 1e-3
    message = _message(doc)
    assert message.startswith("forecast[2].member_spread_f:")
    assert "max(members) - min(members)" in message


# ---------------------------------------------------------------------------- rule 7


def test_members_missing_a_model_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["members"].pop("NAM")
    message = _message(doc)
    assert message.startswith("forecast[0].members:")
    assert "belongs in gaps, not in forecast" in message


def test_null_member_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["members"]["NAM"] = None
    message = _message(doc)
    assert message.startswith("forecast[0].members.NAM:")
    assert "is null" in message


def test_numeric_string_member_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["members"]["NAM"] = "78.05"
    message = _message(doc)
    assert message.startswith("forecast[0].members.NAM:")
    assert "expected a number, got str" in message


# ---------------------------------------------------------------------------- rule 8


def test_a_lead_in_both_forecast_and_gaps_is_rejected(doc: dict) -> None:
    doc["gaps"].append(make_gap(3))
    message = _message(doc)
    assert message.startswith("gaps:")
    assert "[3] h appear in both forecast and gaps" in message


def test_a_lead_in_neither_forecast_nor_gaps_is_rejected(doc: dict) -> None:
    doc["forecast"].pop(0)
    message = _message(doc)
    assert message.startswith("forecast:")
    assert "[3] h appear in neither forecast nor gaps" in message


def test_a_gap_beyond_the_horizon_is_rejected(doc: dict) -> None:
    doc["gaps"].append(make_gap(51))
    message = _message(doc)
    assert message.startswith("gaps[1].lead_h:")
    assert "beyond meta.horizon_h (48 h)" in message


def test_a_forecast_row_beyond_the_horizon_is_rejected(doc: dict) -> None:
    doc["forecast"].append(make_row(51))
    index = len(doc["forecast"]) - 1
    message = _message(doc)
    assert message.startswith(f"forecast[{index}].lead_h:")
    assert "beyond meta.horizon_h (48 h)" in message


def test_a_lead_off_the_step_grid_is_rejected(doc: dict) -> None:
    doc["forecast"].append(make_row(46))
    index = len(doc["forecast"]) - 1
    message = _message(doc)
    assert message.startswith(f"forecast[{index}].lead_h:")
    assert "not on the meta.step_h grid" in message


def test_step_h_must_divide_horizon_h(doc: dict) -> None:
    doc["meta"]["step_h"] = 5
    message = _message(doc)
    assert message.startswith("meta.step_h:")
    assert "does not divide meta.horizon_h" in message


# ------------------------------------------------------------------------- gap shape


def test_gap_with_no_missing_models_is_rejected(doc: dict) -> None:
    doc["gaps"][0]["missing_models"] = []
    message = _message(doc)
    assert message.startswith("gaps[0].missing_models:")
    assert "at least one model" in message


def test_gap_naming_an_unknown_model_is_rejected(doc: dict) -> None:
    doc["gaps"][0]["missing_models"] = ["RAP"]
    message = _message(doc)
    assert message.startswith("gaps[0].missing_models:")
    assert "not in meta.models_included" in message


def test_lowercase_missing_model_is_rejected(doc: dict) -> None:
    doc["gaps"][0]["missing_models"] = ["nam"]
    message = _message(doc)
    assert message.startswith("gaps[0].missing_models[0]:")
    assert "UPPERCASE" in message


def test_duplicate_missing_model_is_rejected(doc: dict) -> None:
    doc["gaps"][0]["missing_models"] = ["NAM", "NAM"]
    message = _message(doc)
    assert message.startswith("gaps[0].missing_models:")
    assert "must be unique" in message


def test_empty_gap_reason_is_rejected(doc: dict) -> None:
    doc["gaps"][0]["reason"] = "   "
    message = _message(doc)
    assert message.startswith("gaps[0].reason:")
    assert "non-empty string" in message


# ---------------------------------------------------------------------------- rule 9


def test_is_synthetic_as_the_string_true_is_rejected(doc: dict) -> None:
    doc["meta"]["is_synthetic"] = "true"
    message = _message(doc)
    assert message.startswith("meta.is_synthetic:")
    assert "must be a JSON boolean (true/false), got str" in message
    assert 'the string "true" is not a boolean' in message


def test_is_synthetic_as_one_is_rejected(doc: dict) -> None:
    doc["meta"]["is_synthetic"] = 1
    message = _message(doc)
    assert message.startswith("meta.is_synthetic:")
    assert "must be a JSON boolean" in message


def test_is_stale_as_a_string_is_rejected(doc: dict) -> None:
    doc["meta"]["cycle"]["is_stale"] = "false"
    message = _message(doc)
    assert message.startswith("meta.cycle.is_stale:")
    assert "must be a JSON boolean" in message


def test_is_extrapolated_lead_as_a_string_is_rejected(doc: dict) -> None:
    doc["forecast"][0]["is_extrapolated_lead"] = "false"
    message = _message(doc)
    assert message.startswith("forecast[0].is_extrapolated_lead:")
    assert "must be a JSON boolean" in message


# --------------------------------------------------------------------------- rule 10


def test_an_extra_skill_entry_at_an_unfitted_lead_is_rejected(doc: dict) -> None:
    doc["skill"]["by_lead"].append(make_skill_entry(42))
    message = _message(doc)
    assert message.startswith("skill.by_lead:")
    assert "extra lead(s) [42]" in message
    assert "never measured" in message


def test_a_missing_skill_entry_is_rejected(doc: dict) -> None:
    doc["skill"]["by_lead"] = [e for e in doc["skill"]["by_lead"] if e["lead_h"] != 12]
    message = _message(doc)
    assert message.startswith("skill.by_lead:")
    assert "missing lead(s) [12]" in message


def test_duplicate_skill_entry_is_rejected(doc: dict) -> None:
    doc["skill"]["by_lead"].append(make_skill_entry(6))
    message = _message(doc)
    assert message.startswith("skill.by_lead:")
    assert "[6] h appear more than once" in message


# --------------------------------------------------------------------------- rule 11


STALE_ACCEPTED = [(0, 100, False), (1, 100, True), (0, 541, True), (0, 540, False)]
STALE_REJECTED = [(0, 100, True), (1, 100, False), (0, 541, False), (0, 540, True)]


def _set_cycle(document: dict, fallen: int, age: int, stale: bool) -> None:
    cycle = document["meta"]["cycle"]
    cycle["cycles_fallen_back"] = fallen
    cycle["age_minutes"] = age
    cycle["is_stale"] = stale
    cycle["stale_reason"] = "fell back 1 cycle: HRRR f021 absent from archive" if stale else None


@pytest.mark.parametrize(("fallen", "age", "stale"), STALE_ACCEPTED)
def test_consistent_staleness_combinations_are_accepted(
    doc: dict, fallen: int, age: int, stale: bool
) -> None:
    _set_cycle(doc, fallen, age, stale)
    assert validate_forecast(doc) is None


@pytest.mark.parametrize(("fallen", "age", "stale"), STALE_REJECTED)
def test_inconsistent_staleness_combinations_are_rejected(
    doc: dict, fallen: int, age: int, stale: bool
) -> None:
    _set_cycle(doc, fallen, age, stale)
    message = _message(doc)
    assert message.startswith("meta.cycle.is_stale:")
    assert f"cycles_fallen_back={fallen}" in message
    assert "if and only if" in message


def test_stale_reason_null_while_stale_is_rejected(doc: dict) -> None:
    _set_cycle(doc, 1, 100, True)
    doc["meta"]["cycle"]["stale_reason"] = None
    message = _message(doc)
    assert message.startswith("meta.cycle.stale_reason:")
    assert "must name the reason" in message


def test_stale_reason_present_while_fresh_is_rejected(doc: dict) -> None:
    doc["meta"]["cycle"]["stale_reason"] = "no reason at all"
    message = _message(doc)
    assert message.startswith("meta.cycle.stale_reason:")
    assert "must be null when is_stale is false" in message


def test_fetched_at_after_generated_at_is_rejected(doc: dict) -> None:
    doc["meta"]["cycle"]["fetched_at"] = "2026-09-04T18:00:00Z"
    message = _message(doc)
    assert message.startswith("meta.cycle.fetched_at:")
    assert "after meta.generated_at" in message


# ------------------------------------------------------------------- meta odds and ends


def test_empty_forecast_is_rejected(doc: dict) -> None:
    """SPEC §10: an empty forecast scores perfectly against nothing and is fake."""
    doc["forecast"] = []
    doc["gaps"] = [make_gap(lead) for lead in range(3, 49, 3)]
    message = _message(doc)
    assert message.startswith("forecast:")
    assert "at least one row" in message


def test_wrong_variable_is_rejected(doc: dict) -> None:
    doc["meta"]["variable"] = "10m_wind"
    message = _message(doc)
    assert message.startswith("meta.variable:")
    assert "'2m_temperature'" in message


def test_wrong_units_are_rejected(doc: dict) -> None:
    doc["meta"]["units"] = "degC"
    message = _message(doc)
    assert message.startswith("meta.units:")
    assert "'degF'" in message


def test_lowercase_model_name_is_rejected(doc: dict) -> None:
    doc["meta"]["models_included"][0] = "hrrr"
    message = _message(doc)
    assert message.startswith("meta.models_included[0]:")
    assert "UPPERCASE" in message


def test_duplicate_model_name_is_rejected(doc: dict) -> None:
    doc["meta"]["models_included"] = ["HRRR", "HRRR", "NAM", "NBM"]
    message = _message(doc)
    assert message.startswith("meta.models_included:")
    assert "must be unique" in message


def test_negative_weights_age_days_is_rejected(doc: dict) -> None:
    doc["meta"]["weights_source"]["weights_age_days"] = -1
    message = _message(doc)
    assert message.startswith("meta.weights_source.weights_age_days:")
    assert "non-negative integer" in message


def test_empty_fitted_leads_is_rejected(doc: dict) -> None:
    doc["meta"]["weights_source"]["fitted_leads"] = []
    message = _message(doc)
    assert message.startswith("meta.weights_source.fitted_leads:")
    assert "at least one fitted lead" in message


def test_unsorted_fitted_leads_is_rejected(doc: dict) -> None:
    doc["meta"]["weights_source"]["fitted_leads"] = [6, 24, 12]
    message = _message(doc)
    assert message.startswith("meta.weights_source.fitted_leads:")
    assert "strictly ascending" in message


def test_timestamp_without_a_z_is_rejected(doc: dict) -> None:
    doc["meta"]["generated_at"] = "2026-09-04T17:04:12+00:00"
    message = _message(doc)
    assert message.startswith("meta.generated_at:")
    assert "ending in 'Z'" in message


def test_empty_skill_note_is_rejected(doc: dict) -> None:
    doc["skill"]["note"] = ""
    message = _message(doc)
    assert message.startswith("skill.note:")
    assert "non-empty string" in message


def test_unexpected_top_level_key_is_rejected(doc: dict) -> None:
    doc["history"] = []
    message = _message(doc)
    assert message.startswith("$:")
    assert "unexpected key(s) ['history']" in message


# ------------------------------------------------------------------- §7 banding table


BANDING_TABLE = [(3, 6), (9, 6), (12, 12), (18, 12), (21, 24), (24, 24), (27, 24), (48, 24)]


@pytest.mark.parametrize(("lead_h", "expected"), BANDING_TABLE)
def test_banding_table_from_the_spec(lead_h: int, expected: int) -> None:
    assert band_for_lead(lead_h, [6, 12, 24]) == expected


def test_a_tie_bands_to_the_shorter_lead() -> None:
    assert band_for_lead(9, [6, 12]) == 6


def test_banding_is_independent_of_the_order_of_fitted_leads() -> None:
    assert band_for_lead(21, [24, 6, 12]) == 24


def test_band_for_lead_raises_on_empty_fitted_leads() -> None:
    with pytest.raises(ValueError) as excinfo:
        band_for_lead(6, [])
    assert "fitted_leads is empty" in str(excinfo.value)


@pytest.mark.parametrize(
    ("lead_h", "expected"), [(6, False), (24, False), (27, True), (48, True)]
)
def test_extrapolation_boundary_with_the_backtest_leads(lead_h: int, expected: bool) -> None:
    assert is_extrapolated_lead(lead_h, [6, 12, 24]) is expected


@pytest.mark.parametrize(
    ("lead_h", "expected"), [(6, False), (12, False), (18, True), (24, True)]
)
def test_extrapolation_boundary_moves_with_the_fitted_leads(
    lead_h: int, expected: bool
) -> None:
    """Proof that 24 is derived, not hardcoded: refit at [6, 12] and the boundary moves."""
    assert is_extrapolated_lead(lead_h, [6, 12]) is expected


def test_is_extrapolated_lead_raises_on_empty_fitted_leads() -> None:
    with pytest.raises(ValueError) as excinfo:
        is_extrapolated_lead(6, [])
    assert "fitted_leads is empty" in str(excinfo.value)


# ------------------------------------------------------- load_and_validate_forecast


def test_load_and_validate_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "forecast.json"
    target.write_text(json.dumps(build_doc()), encoding="utf-8")
    loaded = load_and_validate_forecast(target)
    assert loaded["meta"]["site"]["id"] == "KOMA"


def test_load_and_validate_names_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(ContractError) as excinfo:
        load_and_validate_forecast(missing)
    assert "nope.json" in str(excinfo.value)
    assert "cannot be read" in str(excinfo.value)


def test_load_and_validate_names_a_non_json_file(tmp_path: Path) -> None:
    target = tmp_path / "forecast.json"
    target.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ContractError) as excinfo:
        load_and_validate_forecast(target)
    assert "forecast.json" in str(excinfo.value)
    assert "is not valid JSON" in str(excinfo.value)


def test_load_and_validate_rejects_a_top_level_array(tmp_path: Path) -> None:
    target = tmp_path / "forecast.json"
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(ContractError) as excinfo:
        load_and_validate_forecast(target)
    assert "forecast.json" in str(excinfo.value)
    assert "top level must be an object, got list" in str(excinfo.value)


# ------------------------------------------------------------------------ write_atomic


def test_write_atomic_writes_a_document_that_loads_back(tmp_path: Path) -> None:
    target = tmp_path / "out" / "forecast.json"
    write_atomic(build_doc(), target)
    loaded = load_and_validate_forecast(target)
    assert loaded["meta"]["horizon_h"] == 48
    assert list(tmp_path.joinpath("out").iterdir()) == [target]


def test_write_atomic_refuses_an_invalid_document_and_leaves_the_target_alone(
    tmp_path: Path,
) -> None:
    target = tmp_path / "forecast.json"
    write_atomic(build_doc(), target)
    before = target.read_bytes()

    broken = build_doc()
    broken["forecast"][0]["blend_f"] += 1.0
    with pytest.raises(ContractError) as excinfo:
        write_atomic(broken, target)
    assert "forecast[0].blend_f" in str(excinfo.value)

    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["forecast.json"]


def test_write_atomic_puts_the_temp_file_beside_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.replace is only atomic within one filesystem, so the temp file must be local."""
    captured: dict[str, Path] = {}
    real_replace = os.replace

    def spy(src, dst):  # noqa: ANN001
        captured["src"] = Path(src)
        real_replace(src, dst)

    monkeypatch.setattr(fc.os, "replace", spy)
    target = tmp_path / "nested" / "forecast.json"
    write_atomic(build_doc(), target)

    assert captured["src"].parent == target.parent
    assert captured["src"].name.startswith(".")


def test_write_atomic_honours_an_explicit_temp_path(tmp_path: Path) -> None:
    target = tmp_path / "forecast.json"
    scratch = tmp_path / "scratch.tmp"
    write_atomic(build_doc(), target, tmp=scratch)
    assert not scratch.exists()
    assert load_and_validate_forecast(target)["meta"]["step_h"] == 3
