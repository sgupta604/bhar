"""Executable proof that `forecast.contract.validate_history` locks the §10 shape.

The past-view twin of `tests/test_forecast_contract.py`, and it keeps that file's rule:
every negative case asserts on the *message text*, not merely that something raised. A
validator that rejects a document for the wrong reason passes a test that only checks
`pytest.raises` and still lets the real fault through.

Hermetic: no network, no server, no clock. Every instant is injected. The one test that
touches `data/forecast_history.json` reads it and nothing else, and skips if it is absent.

The document under test is built in memory by `build_history()` so the §10 identities hold
*by construction* — `blend_f` is the weighted sum of the members rounded to the two decimal
places the page publishes, `error_f` is `blend_f - observed_f`, and each day's `mae_f` and
`n_by_lead` are computed from that day's entries. Nothing is transcribed, so the happy path
proves the identities rather than agreeing with numbers somebody typed.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from forecast import contract as fc
from forecast.contract import (
    ContractError,
    load_and_validate_history,
    validate_history,
)

MODELS = ["HRRR", "GFS", "NAM", "NBM"]
LEADS = [6, 12]
DAY_DATES = ["2026-08-20", "2026-08-21"]
INIT_HOURS = [0, 6]

#: Keys are the bare decimal hour count as text — `_lead_key`'s one decision. `"06"` is a
#: different document, and `test_a_zero_padded_lead_key_is_rejected` proves it.
WEIGHTS_BY_LEAD: dict[str, dict[str, float]] = {
    "6": {"HRRR": 0.6, "GFS": 0.0, "NAM": 0.1, "NBM": 0.3},
    "12": {"HRRR": 0.3, "GFS": 0.2, "NAM": 0.1, "NBM": 0.4},
}
BEST_BY_LEAD = {"6": "HRRR", "12": "NBM"}
MODEL_OFFSETS = {"HRRR": 0.0, "GFS": 1.7, "NAM": -0.55, "NBM": 0.3}

#: One signed observation gap and one match offset per (init cycle, lead) slot, so a day's
#: MAE is a mean over two real samples per lead rather than a single absolute error wearing
#: a mean's name — which is what makes the `mae_f` and `n_by_lead` cases below meaningful.
OBS_DELTAS = [0.42, -0.71, 1.13, -0.28]
OBS_OFFSETS_MIN = [-8, 12, -21, 5]


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def default_members(day_index: int, init_h: int, lead_h: int, models: list[str]) -> dict[str, float]:
    """Two-decimal member values, the precision design-target §6 publishes."""
    base = 70.0 + day_index * 1.3 + init_h * 0.05 + lead_h * 0.15
    return {model: round(base + MODEL_OFFSETS.get(model, 0.0), 2) for model in models}


def make_entry(
    day_index: int,
    day_date: str,
    init_h: int,
    lead_h: int,
    slot: int,
    models: list[str],
    weights_by_lead: dict[str, dict[str, float]],
    best_by_lead: dict[str, str],
    members_fn,
) -> dict:
    """One scored step whose four published numbers are derived, never transcribed."""
    init = datetime.combine(date.fromisoformat(day_date), time(hour=init_h), tzinfo=timezone.utc)
    valid = init + timedelta(hours=lead_h)
    key = str(lead_h)
    members = members_fn(day_index, init_h, lead_h, models)
    blend_f = round(sum(weights_by_lead[key][model] * members[model] for model in models), 2)
    observed_f = round(blend_f + OBS_DELTAS[slot % len(OBS_DELTAS)], 2)
    return {
        "valid_time": stamp(valid),
        "init_time": stamp(init),
        "lead_h": lead_h,
        "blend_f": blend_f,
        "observed_f": observed_f,
        "error_f": round(blend_f - observed_f, 2),
        "obs_offset_min": OBS_OFFSETS_MIN[slot % len(OBS_OFFSETS_MIN)],
        "members": members,
        "best_single_model_f": members[best_by_lead[key]],
    }


def make_day(
    day_index: int,
    models: list[str],
    weights_by_lead: dict[str, dict[str, float]],
    best_by_lead: dict[str, str],
    members_fn,
) -> dict:
    day_date = DAY_DATES[day_index]
    entries = []
    slot = 0
    for init_h in INIT_HOURS:
        for lead_h in LEADS:
            entries.append(
                make_entry(
                    day_index,
                    day_date,
                    init_h,
                    lead_h,
                    slot,
                    models,
                    weights_by_lead,
                    best_by_lead,
                    members_fn,
                )
            )
            slot += 1

    mae_f: dict[str, float] = {}
    n_by_lead: dict[str, int] = {}
    for lead_h in LEADS:
        errors = [entry["error_f"] for entry in entries if entry["lead_h"] == lead_h]
        mae_f[str(lead_h)] = sum(abs(error) for error in errors) / len(errors)
        n_by_lead[str(lead_h)] = len(errors)

    return {"date": day_date, "entries": entries, "mae_f": mae_f, "n_by_lead": n_by_lead}


def build_history(
    models: list[str] | None = None,
    weights_by_lead: dict[str, dict[str, float]] | None = None,
    best_by_lead: dict[str, str] | None = None,
    members_fn=None,
) -> dict:
    """A minimal-but-valid §10 document: 2 days, 2 leads, 4 models, 8 scored entries.

    Every call builds a fresh object, so a negative case may mutate whatever it likes
    without leaking the damage into the next test.

    The overridable arguments exist for one test — `HISTORY_TOL` against a two-decimal
    document (see `build_two_decimal_history`) — and are otherwise left alone.
    """
    models = list(models if models is not None else MODELS)
    weights_by_lead = copy.deepcopy(
        weights_by_lead if weights_by_lead is not None else WEIGHTS_BY_LEAD
    )
    best_by_lead = dict(best_by_lead if best_by_lead is not None else BEST_BY_LEAD)
    members_fn = members_fn if members_fn is not None else default_members

    days = [
        make_day(index, models, weights_by_lead, best_by_lead, members_fn)
        for index in range(len(DAY_DATES))
    ]
    n_rows = sum(len(day["entries"]) for day in days)

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
            "window": {
                "start": "2026-08-20T00:00:00Z",
                "end": "2026-08-21T00:00:00Z",
                "days": 2,
            },
            "leads_available": list(LEADS),
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
                "fitted_leads": [6, 12, 24],
            },
            "generated_at": "2026-09-04T16:04:11Z",
            "is_synthetic": False,
            "models_included": models,
            "weights_by_lead": weights_by_lead,
            "best_single_model_by_lead": best_by_lead,
            "join": {
                "tolerance_min": 30,
                "n_forecast_rows": n_rows,
                "n_matched_rows": n_rows,
                "matched_pct": 100.0,
                "mean_abs_offset_min": 11.5,
            },
            "omitted_days": [],
            "source": "noaa_s3_grib",
        },
        "days": days,
    }


@pytest.fixture()
def history() -> dict:
    """A fresh deep copy per test. Negative cases mutate it freely; nothing carries over."""
    return copy.deepcopy(build_history())


def _message(document: dict) -> str:
    with pytest.raises(ContractError) as excinfo:
        validate_history(document)
    return str(excinfo.value)


# ------------------------------------------------------------------------------ the seam


def test_load_and_validate_history_resolves_by_name_on_the_module() -> None:
    """The exact lookup `backend/forecast_api.py:_history_validator` performs per request.

    That endpoint does `getattr(forecast_contract, "load_and_validate_history", None)` on
    the imported **module object**, on every call, and serves 503 while it returns `None`.
    This assertion is therefore the thing that lights up `GET /api/forecast/history` — if
    the name is ever renamed, moved behind a class, or exported only through `__all__`, the
    endpoint goes dark with no other test noticing.
    """
    resolved = getattr(fc, "load_and_validate_history", None)
    assert resolved is not None
    assert callable(resolved)


def test_the_history_entry_points_are_exported() -> None:
    """`__all__` is the published surface; a seam that is not in it invites a re-import."""
    assert {"validate_history", "load_and_validate_history", "HISTORY_TOL"} <= set(fc.__all__)


# ---------------------------------------------------------------------------- happy path


def test_canonical_history_document_validates() -> None:
    assert validate_history(build_history()) is None


def test_canonical_history_document_is_derived_not_transcribed() -> None:
    """If this ever fails, the happy path stopped proving the identity it claims to prove."""
    document = build_history()
    entry = document["days"][0]["entries"][0]
    weights = document["meta"]["weights_by_lead"][str(entry["lead_h"])]
    expected = sum(weights[model] * entry["members"][model] for model in MODELS)
    assert abs(entry["blend_f"] - expected) <= fc.HISTORY_TOL
    assert sum(len(day["entries"]) for day in document["days"]) == 8


def test_load_and_validate_history_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "forecast_history.json"
    target.write_text(json.dumps(build_history()), encoding="utf-8")
    loaded = load_and_validate_history(target)
    assert loaded["meta"]["site"]["id"] == "KOMA"
    assert len(loaded["days"]) == 2


def test_load_and_validate_history_surfaces_a_contract_failure_by_path(tmp_path: Path) -> None:
    """The loader is the seam's contract: a path in, `ContractError` naming the path out."""
    broken = build_history()
    broken["days"][0]["entries"][0]["blend_f"] += 0.5
    target = tmp_path / "forecast_history.json"
    target.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ContractError) as excinfo:
        load_and_validate_history(target)
    assert "days[0].entries[0].blend_f" in str(excinfo.value)


def test_load_and_validate_history_names_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ContractError) as excinfo:
        load_and_validate_history(tmp_path / "nope.json")
    assert "nope.json" in str(excinfo.value)
    assert "cannot be read" in str(excinfo.value)


def test_load_and_validate_history_rejects_a_top_level_array(tmp_path: Path) -> None:
    target = tmp_path / "forecast_history.json"
    target.write_text("[]", encoding="utf-8")
    with pytest.raises(ContractError) as excinfo:
        load_and_validate_history(target)
    assert "top level must be an object, got list" in str(excinfo.value)


# -------------------------------------------------------------------- §6.2 banned names


BANNED_NAMES = sorted(fc.BANNED_FIELD_NAMES)


@pytest.mark.parametrize("name", BANNED_NAMES, ids=BANNED_NAMES)
def test_banned_field_name_inside_an_entry_is_rejected_as_a_banned_name(
    history: dict, name: str
) -> None:
    """Every §6.2 name, injected **nested** — inside an entry, not at the top level.

    The exact key sets would already reject these as "unexpected key(s)", which reads like
    a typo and invites someone to add the key to `_HISTORY_ENTRY_KEYS`. `_sweep_banned_names`
    runs first precisely so the message says *why the field may never exist*. Asserting the
    §6.2 wording at depth is what proves the sweep still runs before the shape check; a
    generic "unexpected key" here would mean the ordering had silently flipped.
    """
    history["days"][0]["entries"][0][name] = 0.5
    message = _message(history)
    assert message.startswith(f"days[0].entries[0].{name}:")
    assert "§6.2" in message
    assert "unexpected key(s)" not in message


def test_the_banned_name_list_is_the_eleven_names_the_spec_bans() -> None:
    """A shrunk banlist would quietly shrink the parametrized suite above; this catches it."""
    assert len(BANNED_NAMES) == 11
    assert set(BANNED_NAMES) == set(fc.BANNED_FIELD_NAMES)


def test_an_ordinary_unexpected_key_is_still_a_shape_failure(history: dict) -> None:
    """The counterpart: a non-banned stray key reports as the §10 shape being locked."""
    history["days"][0]["entries"][0]["forecast_hour"] = 6
    message = _message(history)
    assert message.startswith("days[0].entries[0]:")
    assert "unexpected key(s) ['forecast_hour']" in message
    assert "§10 shape is locked" in message


# ------------------------------------------------------------------------- locked shape


def test_unknown_top_level_key_is_rejected(history: dict) -> None:
    history["gaps"] = []
    message = _message(history)
    assert message.startswith("$:")
    assert "unexpected key(s) ['gaps']" in message
    assert "§10 shape is locked" in message


def test_unknown_meta_key_is_rejected(history: dict) -> None:
    """§9's `horizon_h` has no meaning in the past view and must not leak into it."""
    history["meta"]["horizon_h"] = 48
    message = _message(history)
    assert message.startswith("meta:")
    assert "unexpected key(s) ['horizon_h']" in message
    assert "§10 shape is locked" in message


def test_missing_obs_offset_min_is_rejected(history: dict) -> None:
    """Without it a reader cannot tell a clean match from one at the edge of the window."""
    del history["days"][0]["entries"][0]["obs_offset_min"]
    message = _message(history)
    assert message.startswith("days[0].entries[0]:")
    assert "missing required key(s) ['obs_offset_min']" in message


def test_members_key_set_must_equal_models_included(history: dict) -> None:
    """An entry short of a member was never blended; no weight is ever rescaled to cover it."""
    del history["days"][1]["entries"][2]["members"]["NAM"]
    message = _message(history)
    assert message.startswith("days[1].entries[2].members:")
    assert "keys must be exactly meta.models_included" in message
    assert "belongs nowhere in this document" in message


def test_a_non_z_timestamp_is_rejected(history: dict) -> None:
    """UTC everywhere, spelled one way. An offset form sorts differently in the page."""
    history["days"][0]["entries"][1]["valid_time"] = "2026-08-20T12:00:00+00:00"
    message = _message(history)
    assert message.startswith("days[0].entries[1].valid_time:")
    assert "ending in 'Z'" in message


def test_is_synthetic_as_the_string_true_is_rejected(history: dict) -> None:
    """`"true"` is truthy in JS, so the string would render the banner *off* for real data."""
    history["meta"]["is_synthetic"] = "true"
    message = _message(history)
    assert message.startswith("meta.is_synthetic:")
    assert "must be a JSON boolean" in message
    assert "would defeat the synthetic banner" in message


@pytest.mark.parametrize("block", ["weights_by_lead", "best_single_model_by_lead"])
def test_a_zero_padded_lead_key_is_rejected(history: dict, block: str) -> None:
    """`"06"` is not `"6"`: JSON has no integer keys, so the page's lookups would all miss.

    The failure this prevents is the silent one — a padded key renders a table that is
    quietly empty rather than a page that errors.
    """
    history["meta"][block]["06"] = history["meta"][block].pop("6")
    message = _message(history)
    assert message.startswith(f"meta.{block}:")
    assert "keys must be exactly ['12', '6']" in message
    assert "unexpected ['06']" in message


def test_a_zero_padded_lead_key_in_a_day_summary_is_rejected(history: dict) -> None:
    history["days"][0]["mae_f"]["06"] = history["days"][0]["mae_f"].pop("6")
    message = _message(history)
    assert message.startswith("days[0].mae_f:")
    assert "the lead hours actually present in days[0].entries" in message
    assert "unexpected ['06']" in message


# ---------------------------------------------------------------------- the §10 identities


def test_obs_offset_beyond_the_match_window_is_rejected(history: dict) -> None:
    """An observation further out than 30 min is dropped, never shifted or carried forward."""
    history["days"][0]["entries"][2]["obs_offset_min"] = 31
    message = _message(history)
    assert message.startswith("days[0].entries[2].obs_offset_min:")
    assert "outside the 30-minute match window" in message


def test_a_negative_obs_offset_beyond_the_window_is_rejected(history: dict) -> None:
    """The bound is on the magnitude: an observation 31 min *early* is just as unmatched."""
    history["days"][0]["entries"][2]["obs_offset_min"] = -31
    message = _message(history)
    assert message.startswith("days[0].entries[2].obs_offset_min:")
    assert "outside the 30-minute match window" in message


def test_a_lead_outside_leads_available_is_rejected(history: dict) -> None:
    """Consistent with its own instants, and still not a lead the archive was fetched at.

    `init_time` is moved with `lead_h` deliberately: otherwise the lead/valid-time identity
    fires first and this case would pass for the wrong reason.
    """
    entry = history["days"][0]["entries"][0]
    valid = datetime.strptime(entry["valid_time"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    entry["lead_h"] = 9
    entry["init_time"] = stamp(valid - timedelta(hours=9))
    message = _message(history)
    assert message.startswith("days[0].entries[0].lead_h:")
    assert "is 9, which is not one of meta.leads_available [6, 12]" in message


def test_blend_inconsistent_with_the_weighted_sum_is_rejected(history: dict) -> None:
    """The one non-negotiable: the displayed number *is* the weighted sum of its members."""
    history["days"][1]["entries"][3]["blend_f"] += 0.5
    message = _message(history)
    assert message.startswith("days[1].entries[3].blend_f:")
    assert "sum(meta.weights_by_lead['12'][m] * members[m])" in message
    assert "rejected, never repaired" in message


def test_error_inconsistent_with_blend_minus_observed_is_rejected(history: dict) -> None:
    history["days"][0]["entries"][1]["error_f"] += 1.0
    message = _message(history)
    assert message.startswith("days[0].entries[1].error_f:")
    assert "blend_f - observed_f" in message


def test_an_unsigned_error_is_rejected(history: dict) -> None:
    """abs() here would erase the warm/cold bias the page exists to show."""
    entry = history["days"][0]["entries"][0]
    assert entry["error_f"] < 0
    entry["error_f"] = abs(entry["error_f"])
    message = _message(history)
    assert message.startswith("days[0].entries[0].error_f:")
    assert "The error is SIGNED" in message


def test_best_single_model_f_taken_from_another_member_is_rejected(history: dict) -> None:
    """The look-ahead-bias case: comparing against whichever member happened to land best.

    `meta.best_single_model_by_lead` names the comparison model **in advance**, from the
    backtest. Copying a different member's value into `best_single_model_f` reads the
    observation before choosing, and would flatter the blend on every day it lost.
    """
    entry = history["days"][0]["entries"][0]
    assert history["meta"]["best_single_model_by_lead"]["6"] == "HRRR"
    entry["best_single_model_f"] = entry["members"]["NBM"]
    message = _message(history)
    assert message.startswith("days[0].entries[0].best_single_model_f:")
    assert "'HRRR' is what meta.best_single_model_by_lead names at 6 h" in message
    assert "picking after the fact reads the observation before choosing" in message


def test_mae_inconsistent_with_the_entries_it_summarizes_is_rejected(history: dict) -> None:
    history["days"][0]["mae_f"]["6"] += 1.0
    message = _message(history)
    assert message.startswith("days[0].mae_f.6:")
    assert "the mean of abs(error_f) over this day's 2 entries at 6 h" in message


def test_a_negative_mae_is_rejected(history: dict) -> None:
    history["days"][0]["mae_f"]["12"] = -0.5
    message = _message(history)
    assert message.startswith("days[0].mae_f.12:")
    assert "a mean absolute error cannot be negative" in message


def test_n_by_lead_inconsistent_with_the_entry_count_is_rejected(history: dict) -> None:
    """The count is what tells a one-sample daily MAE apart from a two-sample one."""
    history["days"][0]["n_by_lead"]["6"] = 5
    message = _message(history)
    assert message.startswith("days[0].n_by_lead.6:")
    assert "is 5 but this day carries 2 entries at 6 h" in message


# ------------------------------------------------------------- the fake-perfect-score bug


def test_an_empty_entries_array_is_rejected_and_the_message_explains_why(history: dict) -> None:
    """SPEC §10's headline fault: an empty join scores perfectly and is fake.

    A day with no entries has no errors, so every summary over it is a zero that reads like
    a flawless forecast. The message must say that — a bare "must be non-empty" would let
    the next reader "fix" it by publishing the empty day anyway.
    """
    history["days"][0]["entries"] = []
    message = _message(history)
    assert message.startswith("days[0].entries:")
    assert "scores perfectly against nothing" in message
    assert "fake zero error" in message
    assert "meta.omitted_days" in message


def test_an_empty_days_array_is_rejected(history: dict) -> None:
    history["days"] = []
    message = _message(history)
    assert message.startswith("days:")
    assert "scores perfectly against nothing" in message


def test_a_date_that_is_both_scored_and_omitted_is_rejected(history: dict) -> None:
    """The same bug wearing a reason string: a day cannot be unmatched *and* carry entries."""
    history["meta"]["omitted_days"] = [
        {
            "date": DAY_DATES[0],
            "reason": "no observations within the 30-minute window",
            "n_forecast_rows": 4,
            "n_matched_rows": 0,
        }
    ]
    message = _message(history)
    assert message.startswith("meta.omitted_days[0].date:")
    assert "also appears in days" in message
    assert "fake-perfect-score bug" in message


def test_an_omitted_day_with_matched_rows_is_rejected(history: dict) -> None:
    """A date with matched rows was scorable; it belongs in `days`, scored, not omitted."""
    history["meta"]["omitted_days"] = [
        {
            "date": "2026-08-19",
            "reason": "no observations within the 30-minute window",
            "n_forecast_rows": 4,
            "n_matched_rows": 2,
        }
    ]
    message = _message(history)
    assert message.startswith("meta.omitted_days[0].n_matched_rows:")
    assert "an omitted day is by definition one on which nothing matched" in message


# --------------------------------------------------------------------------- day ordering


def test_duplicate_day_dates_are_rejected(history: dict) -> None:
    history["days"][1]["date"] = history["days"][0]["date"]
    message = _message(history)
    assert message.startswith("days[1].date:")
    assert "does not follow days[0].date" in message
    assert "strictly ascending" in message


def test_descending_day_dates_are_rejected(history: dict) -> None:
    """Sorted ascending, each date once — the order the back-arrow walks."""
    history["days"].reverse()
    message = _message(history)
    assert message.startswith("days[1].date:")
    assert "strictly ascending" in message


def test_a_day_outside_the_declared_window_is_rejected(history: dict) -> None:
    history["days"][1]["date"] = "2026-08-25"
    message = _message(history)
    assert message.startswith("days[1].date:")
    assert "lies outside meta.window" in message


# ------------------------------------------------------------- HISTORY_TOL (decision D-F6-4)

#: A genuinely correct row at the precision design-target §6 publishes: weights on the 0.1
#: grid, members at two decimals. 0.6*71.03 + 0.4*70.07 = 70.646 exactly, published 70.65.
TOL_WEIGHTS = {"HRRR": 0.6, "NAM": 0.4}
TOL_MEMBERS = {"HRRR": 71.03, "NAM": 70.07}


def build_two_decimal_history() -> dict:
    """The same builder, narrowed to the two-model row whose rounding gap is the point."""
    return build_history(
        models=["HRRR", "NAM"],
        weights_by_lead={key: dict(TOL_WEIGHTS) for key in ("6", "12")},
        best_by_lead={"6": "HRRR", "12": "HRRR"},
        members_fn=lambda day_index, init_h, lead_h, models: dict(TOL_MEMBERS),
    )


def test_history_tol_accepts_a_two_decimal_document_that_blend_tol_would_reject() -> None:
    """Why §9's `BLEND_TOL` is not reusable here — the whole of decision D-F6-4, in numbers.

    §10 publishes both the members and the blend rounded to two decimals, so the validator
    recomputes `Σ w·m` from *rounded* inputs and compares against a *rounded* output. The
    two can honestly differ by up to half a unit in the last published place before anyone
    has made a mistake. Here the exact sum is 70.646 and the published value is 70.65: a
    gap of 0.004, four thousand times `BLEND_TOL`. Reusing 1e-6 would reject a correct
    document — and the "fix" would be to publish more decimals than the page shows, or to
    loosen the number until it passed. `HISTORY_TOL` is derived from the precision instead.
    """
    exact = sum(TOL_WEIGHTS[model] * TOL_MEMBERS[model] for model in TOL_WEIGHTS)
    published = round(exact, 2)
    gap = abs(published - exact)

    assert exact == pytest.approx(70.646, abs=1e-12)
    assert published == 70.65
    assert gap == pytest.approx(0.004, abs=1e-9)
    assert gap > fc.BLEND_TOL
    assert gap <= fc.HISTORY_TOL

    document = build_two_decimal_history()
    assert document["days"][0]["entries"][0]["blend_f"] == published
    assert validate_history(document) is None


def test_history_tol_is_derived_from_the_published_precision_not_chosen() -> None:
    """0.005 is half a unit in the second decimal place; the 1e-9 covers the binary form."""
    assert fc.HISTORY_TOL == 0.005 + fc.FLOAT_TOL
    assert fc.BLEND_TOL == 1e-6
    assert fc.HISTORY_TOL > fc.BLEND_TOL


def test_history_tol_still_rejects_a_blend_off_by_five_hundredths() -> None:
    """Not a rubber stamp. A wrong weight vector moves `blend_f` by tenths, not thousandths.

    0.05 is an order of magnitude above the rounding gap the tolerance exists to absorb,
    and it is rejected — which is what stops `HISTORY_TOL` from being a blanket excuse.
    """
    document = build_two_decimal_history()
    entry = document["days"][0]["entries"][0]
    assert 0.05 > fc.HISTORY_TOL
    entry["blend_f"] = round(entry["blend_f"] + 0.05, 2)
    message = _message(document)
    assert message.startswith("days[0].entries[0].blend_f:")
    assert "weighted sum of its members" in message


# ------------------------------------------------------------------ the committed payload


def test_the_committed_history_payload_passes_the_contract(REPO_ROOT: Path) -> None:
    """`data/forecast_history.json` as committed, through the same seam the endpoint uses.

    32 days and 360 entries. Note that `meta.window.days` is **30** and `len(days)` is 32:
    those are two different facts, not a discrepancy. The window is the 30 whole days the
    weights were fitted over, copied verbatim from `results.json`; the archive's UTC
    calendar dates include two partial days at the edges of it. No test here asserts
    `len(days) == meta.window.days`, and none ever should — trimming the edges so the two
    numbers agree would be tuning the experiment to produce a tidier result (SPEC §10).
    """
    target = REPO_ROOT / "data" / "forecast_history.json"
    if not target.exists():
        pytest.skip(f"{target} is not present in this checkout")

    document = load_and_validate_history(target)

    assert len(document["days"]) == 32
    assert sum(len(day["entries"]) for day in document["days"]) == 360
    assert document["meta"]["omitted_days"] == []
    assert document["meta"]["window"]["days"] == 30
    assert document["meta"]["is_synthetic"] is False
