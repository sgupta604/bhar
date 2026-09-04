"""SPEC §4 join tests, including the two ``merge_asof`` behaviours the research refused
to guess.

Task 2.1 was a **probe**: run the library, write down what it actually did, then build on
the observed answer. Observed on **pandas 3.0.5**, and asserted below:

* ``tolerance`` is **INCLUSIVE at exactly 30 minutes** — an observation exactly 30 min
  away matches on either side; 31 min does not.
* On an exact equidistant tie (observations at −15 and +15 min) ``direction="nearest"``
  picks the **EARLIER** observation.

Both are the behaviour SPEC §4 wants, so the named fallback (an explicit
``abs(offset_min) <= 30`` filter with a deterministic earlier-wins tie rule implemented
in ``join.py``) was **not** needed. ``join.py`` still carries a defensive raise on any
surviving row outside the window, so a future library change cannot quietly widen it.

The sign convention is pinned here too: ``offset_min = obs_time - valid_time``, so the
real data's "METAR at :52, model valid at :00" reads **−8.0**.
"""

from __future__ import annotations

import pandas as pd
import pytest

from score.join import MATCH_FLOOR_FRACTION, join_forecasts_to_obs, pair_valid_times

BASE = pd.Timestamp("2026-08-04T12:00:00Z")


def _forecasts(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True).dt.as_unit("us")
    frame["init_time"] = frame["valid_time"] - pd.to_timedelta(frame["lead_h"], unit="h")
    return frame


def _obs(times: list[pd.Timestamp], temps: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "valid_time": pd.to_datetime(times, utc=True).as_unit("us"),
            "temp_f": temps,
        }
    )


def _one(offset_minutes: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One forecast at 12:00Z and one observation ``offset_minutes`` away from it."""
    fc = _forecasts([{"model": "hrrr", "valid_time": BASE, "lead_h": 6, "temp_f": 70.0}])
    obs = _obs([BASE + pd.Timedelta(minutes=offset_minutes)], [69.0])
    return fc, obs


# --------------------------------------------------------------------- probe: tolerance


def test_observation_eight_minutes_early_matches_and_offset_is_negative_eight():
    """The real shape: METAR at :52, model valid at :00 => offset_min == -8.0."""
    matched, _ = join_forecasts_to_obs(*_one(-8))
    assert len(matched) == 1
    assert matched.loc[0, "offset_min"] == -8.0
    assert matched.loc[0, "obs_f"] == 69.0


def test_tolerance_is_inclusive_at_exactly_thirty_minutes_observed_on_pandas_3_0_5():
    """OBSERVED, not assumed: exactly ±30 min DOES match on pandas 3.0.5."""
    for offset in (30, -30):
        matched, _ = join_forecasts_to_obs(*_one(offset))
        assert len(matched) == 1, f"±{offset} min should match; tolerance is inclusive"
        assert matched.loc[0, "offset_min"] == float(offset)


def test_thirty_one_minutes_does_not_match():
    for offset in (31, -31):
        with pytest.raises(RuntimeError, match="below the 80% floor"):
            join_forecasts_to_obs(*_one(offset))


def test_equidistant_tie_picks_the_earlier_observation_observed_on_pandas_3_0_5():
    """OBSERVED, not assumed: with obs at −15 and +15 min, the EARLIER one wins."""
    fc = _forecasts([{"model": "hrrr", "valid_time": BASE, "lead_h": 6, "temp_f": 70.0}])
    obs = _obs(
        [BASE - pd.Timedelta(minutes=15), BASE + pd.Timedelta(minutes=15)],
        [60.0, 61.0],
    )
    matched, _ = join_forecasts_to_obs(fc, obs)
    assert matched.loc[0, "offset_min"] == -15.0
    assert matched.loc[0, "obs_f"] == 60.0  # 60.0 is the earlier observation


def test_nearest_beats_earlier_when_it_is_genuinely_closer():
    fc = _forecasts([{"model": "hrrr", "valid_time": BASE, "lead_h": 6, "temp_f": 70.0}])
    obs = _obs(
        [BASE - pd.Timedelta(minutes=20), BASE + pd.Timedelta(minutes=5)],
        [60.0, 61.0],
    )
    matched, _ = join_forecasts_to_obs(fc, obs)
    assert matched.loc[0, "offset_min"] == 5.0
    assert matched.loc[0, "obs_f"] == 61.0


# ------------------------------------------------------------------ shape and diagnostics


def _grid(n_times: int = 20, models=("hrrr", "gfs", "nam", "nbm"), leads=(6, 12)):
    rows = []
    for k in range(n_times):
        valid = BASE + pd.Timedelta(hours=6 * k)
        for lead in leads:
            for i, model in enumerate(models):
                rows.append(
                    {
                        "model": model,
                        "valid_time": valid,
                        "lead_h": lead,
                        "temp_f": 70.0 + i + 0.5 * k,
                    }
                )
    obs = _obs(
        [BASE + pd.Timedelta(hours=6 * k) - pd.Timedelta(minutes=8) for k in range(n_times)],
        [69.0 + 0.5 * k for k in range(n_times)],
    )
    return _forecasts(rows), obs


def test_model_names_are_mapped_to_uppercase_exactly_once():
    matched, stats = join_forecasts_to_obs(*_grid())
    assert sorted(matched["model"].unique()) == ["GFS", "HRRR", "NAM", "NBM"]
    assert sorted(stats["model"].unique()) == ["GFS", "HRRR", "NAM", "NBM"]


def test_an_unmapped_model_id_raises_rather_than_leaking_lowercase_into_the_json():
    fc, obs = _grid()
    fc.loc[0, "model"] = "rap"
    with pytest.raises(ValueError, match="unknown model id"):
        join_forecasts_to_obs(fc, obs)


def test_offset_min_is_recorded_on_every_matched_row():
    matched, stats = join_forecasts_to_obs(*_grid())
    assert matched["offset_min"].notna().all()
    assert (matched["offset_min"] == -8.0).all()
    assert (stats["matched_pct"] == 100.0).all()
    assert (stats["mean_abs_offset_min"] == 8.0).all()
    assert stats["n_forecast"].sum() == len(matched)


def test_unmatched_rows_are_dropped_never_filled():
    fc, obs = _grid()
    # Remove three observations: 17 of 20 valid times survive => 85%, above the floor.
    obs = obs.drop(index=[3, 9, 15]).reset_index(drop=True)
    matched, stats = join_forecasts_to_obs(fc, obs)
    assert matched["obs_f"].notna().all()
    assert len(matched) == 17 * 4 * 2
    assert stats["matched_pct"].round(4).unique().tolist() == [85.0]


# --------------------------------------------------------------------------- FR3 guard


def test_the_eighty_percent_guard_fires_on_a_sparse_join():
    fc, obs = _grid()
    obs = obs.head(15).reset_index(drop=True)  # 75% < 80%
    with pytest.raises(RuntimeError) as excinfo:
        join_forecasts_to_obs(fc, obs)
    message = str(excinfo.value)
    assert "below the 80% floor" in message
    assert "75.00%" in message
    assert "HRRR" in message or "GFS" in message


def test_the_eighty_percent_guard_does_not_fire_at_full_coverage():
    matched, stats = join_forecasts_to_obs(*_grid())
    assert (stats["matched_pct"] >= MATCH_FLOOR_FRACTION * 100.0).all()
    assert len(matched) == 20 * 4 * 2


def test_the_guard_is_a_raise_not_an_assert_so_python_O_cannot_strip_it():
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "score").rglob("*.py")
    offenders = []
    for path in source:
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("assert ") or stripped.startswith("assert("):
                offenders.append(f"{path.name}:{number}")
    assert offenders == [], f"bare assert in pipeline code (stripped by python -O): {offenders}"


def test_observations_are_never_interpolated_filled_resampled_or_reindexed():
    from pathlib import Path

    banned = ("interpolate(", "fillna(", "resample(", "ffill(", "bfill(")
    offenders = []
    for path in (Path(__file__).resolve().parent.parent / "score").rglob("*.py"):
        text = path.read_text("utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert offenders == [], f"observations must never be filled (SPEC §4 FR2): {offenders}"


# --------------------------------------------------------------------------- tz / dupes


def test_a_tz_naive_join_key_raises():
    fc, obs = _grid()
    fc["valid_time"] = fc["valid_time"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="tz-aware"):
        join_forecasts_to_obs(fc, obs)


def test_duplicate_observation_timestamps_raise():
    fc, obs = _grid()
    obs = pd.concat([obs, obs.head(1)], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate timestamps"):
        join_forecasts_to_obs(fc, obs)


# --------------------------------------------------------------------------- FR4 pairing


def test_pairing_keeps_only_valid_times_every_included_model_has():
    fc, obs = _grid(leads=(6,))
    matched, _ = join_forecasts_to_obs(fc, obs)
    # Drop NAM at two valid times: those two valid times must leave the paired sample.
    drop = matched.index[
        (matched["model"] == "NAM") & matched["valid_time"].isin(matched["valid_time"].unique()[:2])
    ]
    thinned = matched.drop(index=drop)
    paired, n_dropped = pair_valid_times(thinned, ["HRRR", "GFS", "NAM", "NBM"], 6)
    assert n_dropped == 2
    assert paired["valid_time"].nunique() == 18
    assert len(paired) == 18 * 4
    counts = paired.groupby("valid_time")["model"].nunique()
    assert (counts == 4).all()


def test_pairing_drops_nothing_when_every_model_is_complete():
    fc, obs = _grid(leads=(6,))
    matched, _ = join_forecasts_to_obs(fc, obs)
    paired, n_dropped = pair_valid_times(matched, ["HRRR", "GFS", "NAM", "NBM"], 6)
    assert n_dropped == 0
    assert paired["valid_time"].nunique() == 20


def test_pairing_over_a_reduced_included_set_ignores_the_excluded_model():
    fc, obs = _grid(leads=(6,))
    matched, _ = join_forecasts_to_obs(fc, obs)
    paired, n_dropped = pair_valid_times(matched, ["HRRR", "GFS", "NBM"], 6)
    assert n_dropped == 0
    assert set(paired["model"].unique()) == {"HRRR", "GFS", "NBM"}
    assert len(paired) == 20 * 3


def test_pairing_raises_when_nothing_survives():
    fc, obs = _grid(leads=(6,))
    matched, _ = join_forecasts_to_obs(fc, obs)
    thinned = matched.loc[matched["model"] != "NAM"]
    with pytest.raises(RuntimeError, match="no matched rows|nothing to compare"):
        pair_valid_times(thinned, ["HRRR", "GFS", "NAM", "NBM"], 6)
