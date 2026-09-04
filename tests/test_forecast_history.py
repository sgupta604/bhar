"""F6 Stream 3 — the ``forecast/history.py`` builder, and the omission branch above all.

FORECAST-SPEC §10 tests for :mod:`forecast.history`. Hermetic: no network, no server
process, no writes outside ``tmp_path``, and **no write of any kind to a parquet** — the two
input archives are symlinks into another checkout, and this file reads them and nothing else.

Three facts about the numbers here, recorded once so nobody "fixes" them later
--------------------------------------------------------------------------------

1. **`len(days)` is 32 while `meta.window.days` is 30, and that is correct.** The window is
   copied verbatim from ``results.json``: it is the 30 whole days the weights were fitted on.
   ``days`` counts the UTC calendar dates the archive touches, and the archive begins at
   12:00Z on 2026-08-04 and ends at 00:00Z on 2026-09-04, so two partial dates sit at the
   edges. They are two different facts. **No test in this file asserts
   ``len(days) == meta.window.days``**, and none ever should — it fails on correct data, and
   trimming the edges to reconcile them is exactly the tuning SPEC §10 forbids.

2. **The published per-lead MAE differs from an unrounded one in the fourth decimal.** The
   F6 plan quotes 1.8253 / 1.9707 / 2.0449, computed over unrounded errors. The document
   publishes ``error_f`` at 2 dp (§10), and the mean of those stored 2-dp errors is
   1.825250 / 1.971250 / 2.045500. Both were measured; they disagree by <2e-4. The
   assertions below are against what the document **actually contains**, because that is the
   number a reader can recompute from the page. The rounding is not adjusted to chase the
   plan's figures.

3. **The realized in-window MAE is not the out-of-sample MAE and must never be shown as
   skill.** This document scores the fitted blend over the same window it was fitted on:
   ~1.83 / 1.97 / 2.05. ``results.json`` reports the out-of-sample figures the page quotes
   as skill: 1.9173 / 1.9661 / 2.1066. Different samples, different claims. A test that
   compared them, or a page that presented the first as the second, would be publishing an
   in-sample number as evidence of forecasting ability.

The synthetic fixture, and the 80% floor it has to clear
--------------------------------------------------------

Task 3.1's branch is **unreachable on real data**: the real archive matches 1440 of 1440
rows and populates all 32 dates. It has to be provoked, and there is a sharp edge in the way:
:func:`score.join.join_forecasts_to_obs` **raises** when any ``(model, lead_h)`` group falls
below :data:`score.join.MATCH_FLOOR_FRACTION`. A fixture of three dates with one of them
unmatched trips that floor and tests nothing — the join dies before the omission logic is
ever reached. :func:`test_a_short_fixture_trips_the_floor_before_the_omission_is_reachable`
pins that, and is the reason this fixture spans **eleven** dates: losing one of them leaves
every group at 20/22 = 90.9%, so the join returns and the omission is what is under test.

Shifting a day's observations by a constant does **not** work either: hourly readings stay
within 30 minutes of *some* hour, so the day matches anyway against a neighbouring reading.
The two readings that can serve a date are **removed** instead — including the **previous
day's 23:52 reading**, without which a forecast valid at 00:00Z on the target date still
matches backwards across midnight.
"""

from __future__ import annotations

import ast
import copy
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.main
from forecast import history as history_module
from forecast.contract import ContractError, HISTORY_TOL, load_and_validate_history, validate_history
from forecast.history import (
    DEFAULT_OUTPUT,
    OMITTED_DAY_REASON,
    RESULTS_PATH,
    build_history_document,
    main,
    match_forecasts,
    now_utc,
    read_forecasts,
    read_observations,
    temp_path_for,
)
from forecast.weights import load_fitted_weights, select_winner_blend
from score.join import MATCH_FLOOR_FRACTION, join_forecasts_to_obs

# --------------------------------------------------------------------------- pinned inputs

#: A fixed aware-UTC instant, later than ``data/results.json``'s ``meta.generated_at``
#: (2026-09-04T12:53:01Z) so the weight age is a real non-negative number. Never a wall clock:
#: `build_history_document` takes `generated_at` as an argument precisely so a test can pin it.
PINNED_NOW = datetime(2026, 9, 4, 16, 0, 0, tzinfo=timezone.utc)

#: The parquet ``model`` ids, lowercase as the archive stores them.
MODEL_IDS = ("hrrr", "gfs", "nam", "nbm")

#: The payload's names, uppercase as ``results.json`` publishes them.
PAYLOAD_NAMES = ("HRRR", "GFS", "NAM", "NBM")

LEADS = (6, 12, 24)

#: Deliberately chosen so that the member closest to the observation is **not** the model
#: `meta.best_single_model_by_lead` names (HRRR at every lead). At the 12:00Z steps the
#: observation is 68.1: NAM (68.0) is 0.1 away and HRRR (70.0) is 1.9 away. GFS is parked far
#: out at 100.0 and carries a fitted weight of exactly 0.0 at all three leads — it must still
#: appear in every `members` map, and must move `blend_f` not at all.
MEMBER_F = {"hrrr": 70.0, "gfs": 100.0, "nam": 68.0, "nbm": 69.0}

#: Eleven consecutive UTC dates, all inside `meta.window` [2026-08-04, 2026-09-04].
SYNTHETIC_DATES = tuple(pd.Timestamp(f"2026-08-{day:02d}T00:00:00Z") for day in range(10, 21))

#: Two forecast steps a day. The 00:00Z one is what forces the cross-midnight removal.
SYNTHETIC_HOURS = (0, 12)

#: The date whose observations are removed. Mid-fixture, so it is neither edge.
UNMATCHED_DATE = pd.Timestamp("2026-08-15T00:00:00Z")

#: Observations sit at :52 past the hour, the real KOMA METAR shape, so every match lands at
#: `offset_min == -8`. The two temperatures that are actually scored: the 23:52 reading serves
#: the next date's 00:00Z step (72.5 — the blend runs COLD there, a negative error) and the
#: 11:52 reading serves the same date's 12:00Z step (68.1 — the blend runs WARM, positive).
OBS_BY_HOUR = {23: 72.5, 11: 68.1}
OBS_ELSEWHERE_F = 60.0

#: The two readings a fixture must drop to starve `UNMATCHED_DATE`: the previous day's last
#: reading and this day's 11:52. Nothing else is touched — every other date stays whole.
STARVED_READINGS = (
    UNMATCHED_DATE - pd.Timedelta(minutes=8),
    UNMATCHED_DATE + pd.Timedelta(hours=11, minutes=52),
)

#: Real-data anchors, measured (F6 research + this file's own integration run).
REAL_N_DAYS = 32
REAL_N_ENTRIES = 360
REAL_N_PER_LEAD = 120
REAL_MEAN_ABS_OFFSET_MIN = 7.9194
REAL_PUBLISHED_MAE = {"6": 1.825250, "12": 1.971250, "24": 2.045500}
REAL_WINDOW_DAYS = 30
FIRST_PARTIAL_DAY = "2026-08-04"
LAST_PARTIAL_DAY = "2026-09-04"


# --------------------------------------------------------------------------- fixture builders


def _synthetic_forecasts(
    dates=SYNTHETIC_DATES, hours=SYNTHETIC_HOURS, leads=LEADS, extra: list[dict] | None = None
) -> pd.DataFrame:
    """One row per (date, hour, lead, model). `init_time` is derived, never labelled."""
    rows: list[dict] = []
    for day in dates:
        for hour in hours:
            valid_time = day + pd.Timedelta(hours=hour)
            for lead in leads:
                for model in MODEL_IDS:
                    rows.append(
                        {
                            "model": model,
                            "init_time": valid_time - pd.Timedelta(hours=lead),
                            "lead_h": lead,
                            "valid_time": valid_time,
                            "temp_f": MEMBER_F[model],
                        }
                    )
    rows.extend(extra or [])
    frame = pd.DataFrame(rows)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True).dt.as_unit("us")
    frame["init_time"] = pd.to_datetime(frame["init_time"], utc=True).dt.as_unit("us")
    return frame


def _synthetic_obs(drop=(), dates=SYNTHETIC_DATES) -> pd.DataFrame:
    """Hourly readings at :52, spanning a day either side of the forecast dates."""
    dropped = set(drop)
    moment = dates[0] - pd.Timedelta(days=1) + pd.Timedelta(minutes=52)
    last = dates[-1] + pd.Timedelta(days=1)

    times: list[pd.Timestamp] = []
    temps: list[float] = []
    while moment <= last:
        if moment not in dropped:
            times.append(moment)
            temps.append(OBS_BY_HOUR.get(moment.hour, OBS_ELSEWHERE_F))
        moment += pd.Timedelta(hours=1)

    return pd.DataFrame(
        {"valid_time": pd.to_datetime(times, utc=True).as_unit("us"), "temp_f": temps}
    )


@pytest.fixture(scope="module")
def fitted():
    """The real fitted vectors, label-matched out of ``data/results.json``."""
    return load_fitted_weights(RESULTS_PATH, PINNED_NOW)


@pytest.fixture(scope="module")
def starved_document(fitted) -> dict:
    """The fixture under test: eleven dates, one of them with nothing to match against."""
    return build_history_document(
        _synthetic_forecasts(),
        _synthetic_obs(drop=STARVED_READINGS),
        fitted,
        generated_at=PINNED_NOW,
    )


@pytest.fixture(scope="module")
def control_document(fitted) -> dict:
    """THE POSITIVE CONTROL: byte-for-byte the same fixture with those two readings restored."""
    return build_history_document(
        _synthetic_forecasts(), _synthetic_obs(), fitted, generated_at=PINNED_NOW
    )


@pytest.fixture(scope="module")
def real_document(fitted) -> dict:
    """The real archive, scored. Read-only: `pandas.read_parquet` and nothing else."""
    return build_history_document(
        read_forecasts(), read_observations(), fitted, generated_at=PINNED_NOW
    )


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    """In-process, over the shipped app object. Never the :8021 process — see TEST-6."""
    return TestClient(backend.main.app)


def _dates(document: dict) -> list[str]:
    return [day["date"] for day in document["days"]]


def _entries(document: dict):
    for day in document["days"]:
        for entry in day["entries"]:
            yield day, entry


# ==================================================================================
# Task 3.1 — the zero-match omission. An empty join scores perfectly and is fake.
# ==================================================================================


def test_a_short_fixture_trips_the_floor_before_the_omission_is_reachable(fitted) -> None:
    """THE SHARP EDGE, pinned: a three-date fixture never reaches the omission at all.

    One unmatched date out of three leaves every `(model, lead_h)` group at 4 of 6 rows —
    66.7%, under the 80% floor — so `join_forecasts_to_obs` raises and `_omitted_days` is
    never called. A test built on such a fixture asserts nothing about the omission, and this
    is the assertion that stops one being written by accident.
    """
    short_dates = SYNTHETIC_DATES[:3]
    starved = (
        short_dates[1] - pd.Timedelta(minutes=8),
        short_dates[1] + pd.Timedelta(hours=11, minutes=52),
    )

    with pytest.raises(RuntimeError, match="below the 80% floor"):
        match_forecasts(
            _synthetic_forecasts(dates=short_dates),
            _synthetic_obs(drop=starved, dates=short_dates),
            fitted,
        )


def test_the_eleven_date_fixture_clears_the_floor_so_the_join_returns(fitted) -> None:
    """The fixture is only a test of the omission if the join survives it. Prove it does."""
    _, stats = match_forecasts(
        _synthetic_forecasts(), _synthetic_obs(drop=STARVED_READINGS), fitted
    )

    worst = stats["matched_pct"].min()
    assert worst >= MATCH_FLOOR_FRACTION * 100.0, (
        f"the fixture must clear the {MATCH_FLOOR_FRACTION:.0%} floor or the join raises "
        f"before the omission runs; worst group matched {worst}%"
    )
    assert set(stats["n_matched"]) == {20} and set(stats["n_forecast"]) == {22}, (
        "each (model, lead) group should lose exactly the two steps of the starved date"
    )


def test_the_starved_date_is_absent_from_days(starved_document: dict) -> None:
    """NON-NEGOTIABLE (SPEC §4/§10): a date the join could not score is never a scored day."""
    assert UNMATCHED_DATE.date().isoformat() not in _dates(starved_document)
    assert len(starved_document["days"]) == len(SYNTHETIC_DATES) - 1


def test_the_starved_date_is_declared_in_omitted_days_with_a_reason_and_zero_matches(
    starved_document: dict,
) -> None:
    """The disappearance is *declared*, not left for the reader to notice."""
    omitted = starved_document["meta"]["omitted_days"]
    assert len(omitted) == 1, f"exactly one date was starved, got {omitted}"

    record = omitted[0]
    assert record["date"] == UNMATCHED_DATE.date().isoformat()
    assert record["reason"].strip(), "an omitted day with a blank reason explains nothing"
    assert record["reason"] == OMITTED_DAY_REASON
    assert record["n_matched_rows"] == 0
    # 2 steps x 3 leads x 4 models were offered to the join and every one of them was dropped.
    assert record["n_forecast_rows"] == len(SYNTHETIC_HOURS) * len(LEADS) * len(MODEL_IDS)


def test_the_starved_date_never_appears_anywhere_carrying_a_zero_mae(
    starved_document: dict,
) -> None:
    """THE BUG THIS TICKET EXISTS FOR: a scored-looking zero for a day that scored nothing.

    An empty day would validate as "0.00 F mean absolute error" and render on the page as a
    perfect forecast. It is asserted three ways: the date is in no day record, no day carries
    an empty `entries` array, and no `mae_f` anywhere in the document is zero.
    """
    starved = UNMATCHED_DATE.date().isoformat()

    for day in starved_document["days"]:
        assert day["date"] != starved, f"{starved} scored nothing and must not be a day"
        assert day["entries"], f"{day['date']} carries no entries; that MAE would be a fake zero"
        for lead_key, mae in day["mae_f"].items():
            assert mae != 0.0, (
                f"days[{day['date']}].mae_f[{lead_key}] is 0.0 — a day that matched nothing "
                "scores perfectly and is fake (SPEC §10)"
            )

    # Belt and braces: the starved date is carried as a `date` exactly once in the whole
    # serialized document, and that one occurrence is its omitted_days record. (The bare
    # string still appears in neighbouring entries' `init_time` values — a run initialized on
    # the starved date and valid the next morning matched perfectly well, which is why this
    # counts the `date` key rather than the substring.)
    assert json.dumps(starved_document).count(f'"date": "{starved}"') == 1


def test_the_positive_control_emits_the_same_date_as_an_ordinary_scored_day(
    control_document: dict, starved_document: dict
) -> None:
    """POSITIVE CONTROL. Without this the omission test could be passing on a fixture that
    never contained the date at all — which would prove nothing whatsoever.

    Same forecasts, same eleven dates, same everything: only the two observations are put
    back. The date returns as a fully scored day and `omitted_days` empties.
    """
    restored = UNMATCHED_DATE.date().isoformat()

    assert restored in _dates(control_document)
    assert control_document["meta"]["omitted_days"] == []
    assert len(control_document["days"]) == len(SYNTHETIC_DATES)

    day = next(item for item in control_document["days"] if item["date"] == restored)
    assert day["n_by_lead"] == {"6": 2, "12": 2, "24": 2}
    assert set(day["mae_f"]) == {"6", "12", "24"}

    # Every OTHER date is identical between the two runs, so the two readings are the only
    # difference and the omission is the only thing this pair measures.
    control_others = [item for item in control_document["days"] if item["date"] != restored]
    assert control_others == starved_document["days"]


def test_the_omitted_set_and_the_scored_set_are_disjoint(starved_document: dict) -> None:
    scored = set(_dates(starved_document))
    omitted = {record["date"] for record in starved_document["meta"]["omitted_days"]}
    assert scored & omitted == set(), "a date is scored or omitted, never both"


def test_validate_history_rejects_a_date_that_is_both_scored_and_omitted(
    control_document: dict,
) -> None:
    """The hand-edit the contract has to catch: a day carrying entries *and* an excuse."""
    tampered = copy.deepcopy(control_document)
    scored = tampered["days"][3]["date"]
    tampered["meta"]["omitted_days"].append(
        {
            "date": scored,
            "reason": OMITTED_DAY_REASON,
            "n_forecast_rows": 24,
            "n_matched_rows": 0,
        }
    )

    with pytest.raises(ContractError, match="never both"):
        validate_history(tampered)


def test_an_unmatched_forecast_row_is_dropped_and_nothing_is_put_in_its_place(
    starved_document: dict, control_document: dict
) -> None:
    """FR2: never interpolated, resampled, reindexed or carried forward.

    The starved date's 24 forecast rows are simply gone: the join reports them as offered and
    unmatched, the entry count falls by exactly those rows, and the surviving days' MAEs are
    computed over matched rows only — identical to the control, which had the same rows.
    """
    join = starved_document["meta"]["join"]
    control_join = control_document["meta"]["join"]

    assert join["n_forecast_rows"] == control_join["n_forecast_rows"], (
        "the same rows were offered to the join in both runs"
    )
    assert join["n_matched_rows"] == control_join["n_matched_rows"] - 24
    assert join["matched_pct"] < 100.0

    starved_entries = sum(len(day["entries"]) for day in starved_document["days"])
    control_entries = sum(len(day["entries"]) for day in control_document["days"])
    assert starved_entries == control_entries - 6, "6 steps (2 hours x 3 leads) were dropped"

    # Nothing was filled in: no entry anywhere is dated on the starved date, and no entry
    # carries an observation drawn from outside the window.
    starved = UNMATCHED_DATE.date().isoformat()
    for _, entry in _entries(starved_document):
        assert not entry["valid_time"].startswith(starved)
        assert abs(entry["obs_offset_min"]) <= 30

    # And the day either side is untouched: a carry-forward would have changed them.
    for date_text in ("2026-08-14", "2026-08-16"):
        starved_day = next(d for d in starved_document["days"] if d["date"] == date_text)
        control_day = next(d for d in control_document["days"] if d["date"] == date_text)
        assert starved_day == control_day


# ==================================================================================
# Task 3.2 — identities, signs, offsets, leads
# ==================================================================================


def _assert_blend_identity(document: dict) -> int:
    weights = document["meta"]["weights_by_lead"]
    names = document["meta"]["models_included"]
    checked = 0
    for day, entry in _entries(document):
        lead_key = str(entry["lead_h"])
        expected = sum(weights[lead_key][name] * entry["members"][name] for name in names)
        assert abs(entry["blend_f"] - expected) <= HISTORY_TOL, (
            f"days[{day['date']}] {entry['valid_time']} @ {lead_key}h: blend_f "
            f"{entry['blend_f']} != sum(w*m) {expected}"
        )
        checked += 1
    return checked


def test_blend_f_is_the_weighted_sum_of_its_members_at_every_synthetic_entry(
    control_document: dict,
) -> None:
    assert _assert_blend_identity(control_document) == 66


@pytest.mark.integration
def test_blend_f_is_the_weighted_sum_of_its_members_at_every_real_entry(
    real_document: dict,
) -> None:
    """NON-NEGOTIABLE §10, on all 360 real entries — not a sample of them."""
    assert _assert_blend_identity(real_document) == REAL_N_ENTRIES


def test_every_members_map_carries_the_zero_weighted_member_too(control_document: dict) -> None:
    """GFS is weighted 0.0 at all three leads and is still published on every entry.

    Dropping it would make the document describe a blend over three models, and the weights
    are never rescaled over a subset.
    """
    for _, entry in _entries(control_document):
        assert tuple(entry["members"]) == PAYLOAD_NAMES
    for lead_key, vector in control_document["meta"]["weights_by_lead"].items():
        assert vector["GFS"] == 0.0, f"lead {lead_key} should carry GFS at zero weight"
        assert abs(sum(vector.values()) - 1.0) < 1e-9


def test_the_published_vector_is_the_label_matched_winner_not_blends_index_zero(
    control_document: dict,
) -> None:
    """THE ANTI-LOOK-AHEAD GUARD. `blends[]` is ranked by OUT-OF-SAMPLE error, so `blends[0]`
    is the leaderboard leader rather than the vector the training split actually chose.

    The real ``results.json`` is itself the fixture the plan asks for: the winner sits at
    index 4 / 22 / 4, and `blends[0]` is a *different* vector at all three leads. If the
    builder had reached for index 0, every assertion below would fail.
    """
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    published = control_document["meta"]["weights_by_lead"]

    for lead in LEADS:
        lead_result = results["results"][str(lead)]
        winner = select_winner_blend(lead, lead_result)
        first = lead_result["blends"][0]["weights"]

        assert first != winner["weights"], (
            f"lead {lead}: blends[0] equals the winner in this results.json, so this test "
            "cannot tell the two apart — it is no longer a guard"
        )
        assert published[str(lead)] == {
            name: round(float(winner["weights"][name]), 1) for name in PAYLOAD_NAMES
        }
        assert published[str(lead)] != {
            name: round(float(first[name]), 1) for name in PAYLOAD_NAMES
        }


def test_error_f_is_signed_and_a_cold_blend_yields_a_negative_value(
    control_document: dict,
) -> None:
    """SIGNED, always. An absolute value would erase the bias the page exists to show.

    The 00:00Z steps are observed at 72.5 against a blend near 69.4 — the blend ran COLD, so
    the error is negative. The 12:00Z steps are observed at 68.1 — WARM, positive. Both signs
    appear, so a builder that published `abs(error)` could not pass this.
    """
    cold: list[float] = []
    warm: list[float] = []

    for _, entry in _entries(control_document):
        expected = round(entry["blend_f"] - entry["observed_f"], 2)
        assert abs(entry["error_f"] - expected) <= HISTORY_TOL
        (cold if entry["valid_time"].endswith("T00:00:00Z") else warm).append(entry["error_f"])

    assert cold and all(value < 0 for value in cold), f"the 00:00Z steps must run cold: {cold}"
    assert warm and all(value > 0 for value in warm), f"the 12:00Z steps must run warm: {warm}"


@pytest.mark.integration
def test_error_f_is_signed_on_every_real_entry_and_both_signs_occur(real_document: dict) -> None:
    signs = set()
    for day, entry in _entries(real_document):
        expected = round(entry["blend_f"] - entry["observed_f"], 2)
        assert abs(entry["error_f"] - expected) <= HISTORY_TOL, (
            f"days[{day['date']}] {entry['valid_time']}: error_f is not blend_f - observed_f"
        )
        if entry["error_f"]:
            signs.add(entry["error_f"] > 0)
    assert signs == {True, False}, "a real 30-day record runs both warm and cold"


def test_obs_offset_min_is_present_and_an_integer_inside_the_window_on_every_entry(
    control_document: dict,
) -> None:
    for _, entry in _entries(control_document):
        offset = entry["obs_offset_min"]
        assert isinstance(offset, int) and not isinstance(offset, bool)
        assert abs(offset) <= 30
        # The KOMA shape: METAR at :52, model valid at :00.
        assert offset == -8


@pytest.mark.integration
def test_obs_offset_min_is_present_and_an_integer_on_every_real_entry(
    real_document: dict,
) -> None:
    for day, entry in _entries(real_document):
        offset = entry["obs_offset_min"]
        assert isinstance(offset, int) and not isinstance(offset, bool), (
            f"days[{day['date']}] {entry['valid_time']}: obs_offset_min is {offset!r}"
        )
        assert abs(offset) <= 30


def test_a_fractional_observation_offset_raises_rather_than_being_rounded(fitted) -> None:
    """A rounded offset states a match that did not happen.

    One reading is nudged 30 seconds later, so the 12:00Z step matches it at -7.5 min. The
    builder must refuse rather than publish `-8` and imply a match that never occurred.
    """
    obs = _synthetic_obs()
    target = SYNTHETIC_DATES[0] + pd.Timedelta(hours=11, minutes=52)
    obs.loc[obs["valid_time"] == target, "valid_time"] = target + pd.Timedelta(seconds=30)
    obs = obs.sort_values("valid_time").reset_index(drop=True)

    with pytest.raises(ContractError, match="fractional number of minutes"):
        build_history_document(_synthetic_forecasts(), obs, fitted, generated_at=PINNED_NOW)


def test_only_the_fitted_leads_appear_in_the_document(control_document: dict) -> None:
    assert control_document["meta"]["leads_available"] == list(LEADS)
    assert {entry["lead_h"] for _, entry in _entries(control_document)} == set(LEADS)


def test_a_lead_the_backtest_never_fitted_raises_rather_than_being_blended(fitted) -> None:
    """A 3 h step has no fitted vector. It is never banded onto 6 h and never blended."""
    valid_time = SYNTHETIC_DATES[0] + pd.Timedelta(hours=12)
    intruder = [
        {
            "model": model,
            "init_time": valid_time - pd.Timedelta(hours=3),
            "lead_h": 3,
            "valid_time": valid_time,
            "temp_f": MEMBER_F[model],
        }
        for model in MODEL_IDS
    ]

    with pytest.raises(ContractError, match="the backtest never fitted"):
        build_history_document(
            _synthetic_forecasts(extra=intruder),
            _synthetic_obs(),
            fitted,
            generated_at=PINNED_NOW,
        )


def test_best_single_model_f_is_the_named_model_even_when_another_member_lands_closer(
    control_document: dict,
) -> None:
    """Picking the closest member on the day reads the observation before choosing — the same
    class of look-ahead bias as reaching for `blends[0]`.

    At the 12:00Z steps the observation is 68.1: NAM (68.0) is nearest by a mile and HRRR
    (70.0) is what `meta.best_single_model_by_lead` names. `best_single_model_f` must be
    HRRR's 70.0 on every one of those entries.
    """
    named = control_document["meta"]["best_single_model_by_lead"]
    assert set(named.values()) == {"HRRR"}

    proved = 0
    for _, entry in _entries(control_document):
        best_name = named[str(entry["lead_h"])]
        assert entry["best_single_model_f"] == entry["members"][best_name]

        closest = min(entry["members"], key=lambda m: abs(entry["members"][m] - entry["observed_f"]))
        if closest != best_name:
            assert entry["best_single_model_f"] != entry["members"][closest]
            proved += 1

    assert proved == 33, (
        "the fixture must contain entries where the closest member differs from the named "
        f"one, or this test proves nothing; found {proved}"
    )


@pytest.mark.integration
def test_best_single_model_f_is_the_named_model_on_every_real_entry(real_document: dict) -> None:
    named = real_document["meta"]["best_single_model_by_lead"]
    assert named == {"6": "HRRR", "12": "HRRR", "24": "HRRR"}
    for day, entry in _entries(real_document):
        best_name = named[str(entry["lead_h"])]
        assert entry["best_single_model_f"] == entry["members"][best_name], (
            f"days[{day['date']}] {entry['valid_time']}: best_single_model_f is not "
            f"members[{best_name}]"
        )


def _assert_day_summaries(document: dict) -> None:
    for day in document["days"]:
        errors = defaultdict(list)
        for entry in day["entries"]:
            errors[str(entry["lead_h"])].append(entry["error_f"])

        assert set(day["mae_f"]) == set(errors), (
            f"days[{day['date']}].mae_f is keyed by {sorted(day['mae_f'])} but the day carries "
            f"leads {sorted(errors)}; the summary is keyed by the leads PRESENT that day, "
            "never padded out to meta.leads_available"
        )
        assert set(day["n_by_lead"]) == set(errors)

        for lead_key, values in errors.items():
            expected = sum(abs(value) for value in values) / len(values)
            assert abs(day["mae_f"][lead_key] - expected) <= HISTORY_TOL
            assert day["n_by_lead"][lead_key] == len(values)


def test_daily_mae_and_counts_are_recomputed_from_the_entries_they_summarize(
    control_document: dict,
) -> None:
    _assert_day_summaries(control_document)
    for day in control_document["days"]:
        assert day["n_by_lead"] == {"6": 2, "12": 2, "24": 2}


@pytest.mark.integration
def test_daily_mae_and_counts_hold_on_the_real_record_including_both_partial_edge_days(
    real_document: dict,
) -> None:
    """The two edge days are the whole reason `mae_f` is keyed by the leads present.

    2026-08-04 begins at 12:00Z and never reaches a 24 h step; 2026-09-04 ends at 00:00Z and
    carries exactly one. Padding either out to `meta.leads_available` would have to invent an
    MAE for a lead with no entries — a zero that reads like a perfect forecast.
    """
    _assert_day_summaries(real_document)

    first = real_document["days"][0]
    assert first["date"] == FIRST_PARTIAL_DAY
    assert first["n_by_lead"] == {"6": 2, "12": 1}
    assert set(first["mae_f"]) == {"6", "12"}
    assert "24" not in first["mae_f"], "the first day has no 24 h step and must claim none"

    last = real_document["days"][-1]
    assert last["date"] == LAST_PARTIAL_DAY
    assert last["n_by_lead"] == {"24": 1}
    assert set(last["mae_f"]) == {"24"}

    # And a one-sample MAE is exactly that one sample's error, published with the count that
    # tells the reader so.
    only = last["entries"][0]
    assert last["mae_f"]["24"] == abs(only["error_f"])


@pytest.mark.integration
def test_every_real_entry_count_reconciles_with_the_joins_own_matched_row_count(
    real_document: dict,
) -> None:
    n_entries = sum(len(day["entries"]) for day in real_document["days"])
    join = real_document["meta"]["join"]
    assert n_entries * len(PAYLOAD_NAMES) == join["n_matched_rows"]

    per_lead = defaultdict(int)
    for _, entry in _entries(real_document):
        per_lead[str(entry["lead_h"])] += 1
    assert dict(per_lead) == {key: REAL_N_PER_LEAD for key in ("6", "12", "24")}


def test_identical_inputs_and_an_identical_generated_at_produce_a_byte_identical_document(
    fitted,
) -> None:
    """Determinism: no wall clock, no dict ordering drift, no absolute path from this machine."""
    first = build_history_document(
        _synthetic_forecasts(), _synthetic_obs(), fitted, generated_at=PINNED_NOW
    )
    second = build_history_document(
        _synthetic_forecasts(), _synthetic_obs(), fitted, generated_at=PINNED_NOW
    )

    assert json.dumps(first, indent=2).encode() == json.dumps(second, indent=2).encode()
    assert "/Users/" not in json.dumps(first), (
        "an absolute path in the payload prints the operator's home directory onto a customer "
        "page and makes two correct runs differ byte for byte"
    )


def test_build_history_document_reads_no_clock(fitted) -> None:
    """`generated_at` is injected, and a naive instant is refused rather than assumed UTC."""
    assert now_utc().tzinfo is not None

    with pytest.raises(ContractError, match="naive datetime"):
        build_history_document(
            _synthetic_forecasts(),
            _synthetic_obs(),
            fitted,
            generated_at=datetime(2026, 9, 4, 16, 0, 0),
        )


# --- the parquets are symlinks into another checkout: nothing here may ever write one ---

_WRITE_CALLS = frozenset(
    {
        "open",
        "replace",
        "rename",
        "unlink",
        "write",
        "writelines",
        "write_text",
        "write_bytes",
        "write_atomic",
        "mkdir",
        "touch",
        "dump",
        "to_parquet",
        "to_csv",
        "to_json",
        "to_pickle",
        "to_feather",
    }
)


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def test_no_write_call_in_the_history_module_targets_a_parquet_path() -> None:
    """`data/forecasts.parquet` and `data/obs.parquet` are symlinks into a live checkout this
    repository does not own. A write through either destroys another session's data.

    Checked structurally rather than by reading carefully: the only parquet API the module may
    name is `read_parquet`, and no write-shaped call may mention a parquet anywhere in its
    arguments.
    """
    source = Path(history_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    parquet_apis = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and "parquet" in node.attr.lower()
    }
    assert parquet_apis == {"read_parquet"}, (
        f"forecast/history.py names parquet API(s) {sorted(parquet_apis)}; it may read parquet "
        "and must never write one"
    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in _WRITE_CALLS:
            continue
        rendered = " ".join(
            ast.unparse(argument)
            for argument in list(node.args) + [kw.value for kw in node.keywords]
        )
        assert "parquet" not in rendered.lower(), (
            f"the write call {name}({rendered}) mentions a parquet target"
        )


def test_writing_to_a_parquet_output_path_is_refused_and_nothing_lands(tmp_path: Path) -> None:
    """The runtime half of the same guard: `--out something.parquet` never gets as far as a
    write, and leaves no scratch file behind either."""
    target = tmp_path / "obs.parquet"

    with pytest.raises(ContractError, match="never writes it"):
        main(["--out", str(target)])

    assert not target.exists()
    assert not temp_path_for(target).exists()
    assert list(tmp_path.iterdir()) == []


def test_the_scratch_file_sits_beside_its_target(tmp_path: Path) -> None:
    """`os.replace` is atomic only within one filesystem, so the temp file shares the dir."""
    target = tmp_path / "forecast_history.json"
    scratch = temp_path_for(target)
    assert scratch.parent == target.parent
    assert scratch.name == ".forecast_history.json.tmp"


# ==================================================================================
# Task 3.3 — the real-data anchors, the committed file, and the endpoint
# ==================================================================================


@pytest.mark.integration
def test_the_real_archive_scores_to_the_measured_anchors(real_document: dict) -> None:
    """The F6 research anchors, asserted against a fresh build off the real parquets.

    On the MAE: these are the means of the **published** 2-dp `error_f` values, which is what
    a reader can recompute from the document. Computed unrounded they come out 1.8253 /
    1.9707 / 2.0449 — a disagreement in the fourth decimal, expected, reported, and not
    rounded away in either direction.
    """
    days = real_document["days"]
    entries = [entry for _, entry in _entries(real_document)]

    assert len(days) == REAL_N_DAYS
    assert len(entries) == REAL_N_ENTRIES

    join = real_document["meta"]["join"]
    assert join["n_forecast_rows"] == 1440
    assert join["n_matched_rows"] == 1440
    assert join["matched_pct"] == 100.0
    assert join["tolerance_min"] == 30
    assert abs(join["mean_abs_offset_min"] - REAL_MEAN_ABS_OFFSET_MIN) <= 1e-3

    # 1440 of 1440 matched and all 32 dates populated: the omission branch is UNREACHABLE on
    # real data, which is exactly why Task 3.1 provokes it with a synthetic fixture.
    assert real_document["meta"]["omitted_days"] == []

    by_lead = defaultdict(list)
    for entry in entries:
        by_lead[str(entry["lead_h"])].append(abs(entry["error_f"]))

    for lead_key, expected in REAL_PUBLISHED_MAE.items():
        values = by_lead[lead_key]
        assert len(values) == REAL_N_PER_LEAD
        measured = sum(values) / len(values)
        assert abs(measured - expected) <= 1e-3, (
            f"lead {lead_key}h published MAE is {measured!r}, expected ~{expected}. If this "
            "ever disagrees, report the number — never adjust the build to reproduce it."
        )


@pytest.mark.integration
def test_there_are_thirty_two_scored_days_against_a_thirty_day_fitted_window(
    real_document: dict,
) -> None:
    """`len(days) == 32` and `meta.window.days == 30`. BOTH ARE CORRECT AND THEY DIFFER.

    `meta.window` is copied verbatim from `results.json`: the 30 whole days the weights were
    fitted on. `days` counts the UTC calendar dates the archive touches, and the archive runs
    from 12:00Z on 2026-08-04 to 00:00Z on 2026-09-04, so two partial dates sit at the edges.

    NO TEST MAY ASSERT `len(days) == meta.window.days`. It fails on correct data, and trimming
    the edges to make the two numbers agree is tuning the experiment to produce a tidier
    result — the thing SPEC §10 forbids.
    """
    assert len(real_document["days"]) == REAL_N_DAYS
    assert real_document["meta"]["window"]["days"] == REAL_WINDOW_DAYS
    assert real_document["days"][0]["date"] == FIRST_PARTIAL_DAY
    assert real_document["days"][-1]["date"] == LAST_PARTIAL_DAY


@pytest.mark.integration
def test_the_in_window_mae_is_not_the_out_of_sample_mae_and_is_never_shown_as_skill(
    real_document: dict, fitted
) -> None:
    """Two different numbers about two different samples, pinned so neither can drift into
    the other's place.

    The document's ~1.83 / 1.97 / 2.05 is the fitted blend scored over the very window it was
    fitted on. `results.json`'s 1.9173 / 1.9661 / 2.1066 is out-of-sample, and it is the only
    one of the two that is a claim about forecasting ability. The history page shows the
    former as a record of what happened; it must never be captioned as skill.
    """
    out_of_sample = {
        str(entry["lead_h"]): entry["blend_mae"] for entry in fitted.skill["by_lead"]
    }
    assert out_of_sample == {"6": 1.9173, "12": 1.9661, "24": 2.1066}

    for lead_key, in_window in REAL_PUBLISHED_MAE.items():
        assert abs(in_window - out_of_sample[lead_key]) > 1e-3, (
            f"lead {lead_key}h: the in-window and out-of-sample MAEs coincide, which would "
            "make it impossible to tell whether the page is quoting the right one"
        )

    # The history document publishes no skill block at all — the §10 payload is a record.
    assert "skill" not in real_document
    assert "skill" not in real_document["meta"]


@pytest.mark.integration
def test_the_committed_history_payload_passes_the_section_10_validator() -> None:
    """A hand-edit or a stale regeneration of `data/forecast_history.json` fails here."""
    assert DEFAULT_OUTPUT.exists(), (
        f"{DEFAULT_OUTPUT} is missing; it is produced by "
        "'uv run --no-sync python -m forecast.history'"
    )

    document = load_and_validate_history(DEFAULT_OUTPUT)

    assert len(document["days"]) == REAL_N_DAYS
    assert sum(len(day["entries"]) for day in document["days"]) == REAL_N_ENTRIES
    assert document["meta"]["is_synthetic"] is False
    assert not Path(document["meta"]["weights_source"]["path"]).is_absolute()


@pytest.mark.integration
def test_the_committed_payload_matches_a_fresh_build_from_the_parquets(
    real_document: dict,
) -> None:
    """Stale-file guard: everything but the generation stamp must be reproducible from the
    archive that is on disk right now."""
    committed = load_and_validate_history(DEFAULT_OUTPUT)

    fresh = copy.deepcopy(real_document)
    for document in (committed, fresh):
        document["meta"].pop("generated_at")
        document["meta"]["weights_source"].pop("weights_age_days")

    assert committed == fresh


@pytest.mark.integration
def test_the_cli_regenerates_the_document_atomically(tmp_path: Path, capsys) -> None:
    """`main()` end to end into `tmp_path`: exit 0, a valid document, no scratch left over."""
    target = tmp_path / "forecast_history.json"

    assert main(["--out", str(target)]) == 0

    document = load_and_validate_history(target)
    assert len(document["days"]) == REAL_N_DAYS
    assert not temp_path_for(target).exists(), "the scratch dotfile must be replaced, not left"

    printed = capsys.readouterr().out
    assert str(target) in printed
    assert "1440/1440 matched" in printed


@pytest.mark.integration
def test_the_history_endpoint_serves_the_whole_validated_document(
    api_client: TestClient,
) -> None:
    """`GET /api/forecast/history` -> 200, in process over the shipped app object.

    Deliberately NOT a request to the running :8021 server: that process predates the
    contract change, still 503s, and is a user's — it is neither restarted nor curled here.
    """
    response = api_client.get("/api/forecast/history")

    assert response.status_code == 200, response.text
    document = response.json()

    assert set(document) == {"meta", "days"}
    assert len(document["days"]) == REAL_N_DAYS
    assert sum(len(day["entries"]) for day in document["days"]) == REAL_N_ENTRIES
    assert document["meta"]["units"] == "degF"

    # Served whole, not summarised: the body is the validated document itself.
    validate_history(document)
    assert document == load_and_validate_history(DEFAULT_OUTPUT)
