"""SPEC §4 — join forecasts to the nearest observation within ±30 minutes.

The observations are true METAR readings taken a few minutes before the hour (KOMA
reports at ``:52``), so a forecast valid at ``12:00Z`` is scored against the ``11:52Z``
observation eight minutes earlier.  That offset is recorded on **every** matched row and
shipped in ``join_diagnostics`` — it is a fact about the experiment, not an
implementation detail to bury.

Observed ``merge_asof`` behaviour, pinned by ``tests/test_join.py`` on pandas 3.0.5
rather than assumed (the research explicitly refused to guess either):

* ``tolerance`` is **inclusive** at exactly 30 minutes; 31 minutes does not match.
* On an exact equidistant tie (observations at −15 and +15 min) ``direction="nearest"``
  picks the **earlier** observation.

Both are the behaviour we want, so no explicit re-implementation of the rule was needed.
A defensive ``raise`` still checks that no surviving row exceeds the tolerance, so a
library change cannot quietly widen the window.

Failure modes this module exists to prevent
-------------------------------------------
* **A join that looks perfect because it matched nothing.**  ``matched_pct`` is computed
  *before* unmatched rows are dropped, and a per-``(model, lead)`` match rate below 80%
  **raises**: the pipeline does not proceed (FR3).
* **Filling the gaps.**  Observations are never interpolated, resampled, reindexed or
  forward-filled.  Unmatched forecast rows are dropped (FR2).
* **A left frame that looks sorted and is not.**  ``sort_values(["model", "valid_time"])``
  passes a casual glance and is wrong for ``merge_asof``; the sort is on ``valid_time``
  **only**.
* **A dictionary-encoded ``model`` column** silently breaking key comparison — T4 pins
  plain strings on round-trip; this module works on the display names anyway.

Every guard is an explicit ``raise``.  ``python -O`` strips ``assert``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from score.blend import canonical_model_name

__all__ = [
    "TOLERANCE",
    "MATCH_FLOOR_FRACTION",
    "join_forecasts_to_obs",
    "pair_valid_times",
]

#: SPEC §4 join window. Nearest observation within ±30 minutes of the forecast valid time.
TOLERANCE = pd.Timedelta(minutes=30)

#: SPEC §4 / FR3 hard floor. Below this share of matched rows the pipeline raises.
MATCH_FLOOR_FRACTION = 0.80


def _require_tz_aware(series: pd.Series, label: str) -> None:
    dtype = series.dtype
    if not isinstance(dtype, pd.DatetimeTZDtype):
        raise ValueError(
            f"{label} must be a tz-aware datetime column, got dtype {dtype!r}; a tz-naive "
            "side makes the ±30 min window meaningless (UTC everywhere — CLAUDE.md)"
        )
    if str(dtype.tz) != "UTC":
        raise ValueError(f"{label} must be UTC, got timezone {dtype.tz!r}")


def join_forecasts_to_obs(
    forecasts: pd.DataFrame, obs: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join every forecast row to its nearest observation within ±30 minutes.

    Returns ``(matched, stats)``:

    * ``matched`` — one row per *matched* forecast, with ``model`` mapped to its display
      name and an ``offset_min`` column (``obs_time - valid_time``, signed, minutes) on
      **every** row.
    * ``stats`` — per ``(model, lead_h)``: ``n_forecast``, ``n_matched``, ``matched_pct``
      and ``mean_abs_offset_min``, computed before any row was dropped.

    Raises if any ``(model, lead_h)`` group matched fewer than 80% of its forecast rows.
    """
    for column in ("model", "init_time", "valid_time", "lead_h", "temp_f"):
        if column not in forecasts.columns:
            raise ValueError(
                f"forecasts frame is missing required column {column!r}; got "
                f"{list(forecasts.columns)}"
            )
    for column in ("valid_time", "temp_f"):
        if column not in obs.columns:
            raise ValueError(
                f"obs frame is missing required column {column!r}; got {list(obs.columns)}"
            )
    if forecasts.empty:
        raise ValueError("forecasts frame is empty; there is nothing to score (SPEC §4)")
    if obs.empty:
        raise ValueError("obs frame is empty; an empty join scores perfectly and is fake (SPEC §4)")

    _require_tz_aware(forecasts["valid_time"], "forecasts.valid_time")
    _require_tz_aware(obs["valid_time"], "obs.valid_time")
    if forecasts["valid_time"].dtype != obs["valid_time"].dtype:
        raise ValueError(
            f"join keys have different dtypes: forecasts {forecasts['valid_time'].dtype!r} vs "
            f"obs {obs['valid_time'].dtype!r}; a mixed resolution can coerce silently"
        )

    left = forecasts.copy()
    left["model"] = [canonical_model_name(m) for m in left["model"]]
    if left["valid_time"].isna().any():
        raise ValueError("forecasts.valid_time contains NaT; merge_asof keys may not be null")
    # Sort by valid_time ONLY. A per-model sort looks sorted and is not.
    left = left.sort_values("valid_time", kind="mergesort").reset_index(drop=True)

    right = obs.dropna(subset=["temp_f"]).copy()
    if right["valid_time"].isna().any():
        raise ValueError("obs.valid_time contains NaT; merge_asof keys may not be null")
    right = right.rename(columns={"valid_time": "obs_time", "temp_f": "obs_f"})
    right = right[["obs_time", "obs_f"]].sort_values("obs_time", kind="mergesort")
    if right["obs_time"].duplicated().any():
        dupes = right.loc[right["obs_time"].duplicated(), "obs_time"].unique()[:5]
        raise ValueError(
            f"obs has duplicate timestamps {list(dupes)}; duplicates make merge_asof's "
            "'nearest' pick order-dependent, so the scored observation would depend on row order"
        )
    right = right.reset_index(drop=True)
    if right.empty:
        raise ValueError(
            "no usable observations after dropping missing values; an empty join scores "
            "perfectly and is fake (SPEC §4)"
        )

    joined = pd.merge_asof(
        left,
        right,
        left_on="valid_time",
        right_on="obs_time",
        direction="nearest",
        tolerance=TOLERANCE,
        allow_exact_matches=True,
    )
    # No `by=` argument: the observations are one global series, not a per-model one.
    joined["offset_min"] = (
        joined["obs_time"] - joined["valid_time"]
    ).dt.total_seconds() / 60.0
    joined["is_matched"] = joined["obs_f"].notna()

    stats = (
        joined.groupby(["model", "lead_h"], dropna=False)
        .apply(
            lambda g: pd.Series(
                {
                    "n_forecast": int(len(g)),
                    "n_matched": int(g["is_matched"].sum()),
                    "matched_pct": 100.0 * float(g["is_matched"].sum()) / float(len(g)),
                    "mean_abs_offset_min": float(
                        np.mean(np.abs(g.loc[g["is_matched"], "offset_min"].to_numpy()))
                    )
                    if bool(g["is_matched"].any())
                    else float("nan"),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    stats["n_forecast"] = stats["n_forecast"].astype(int)
    stats["n_matched"] = stats["n_matched"].astype(int)

    # --- FR3: the hard guard. A join that matched nothing scores perfectly and is fake.
    floor_pct = MATCH_FLOOR_FRACTION * 100.0
    short = stats.loc[stats["matched_pct"] < floor_pct]
    if not short.empty:
        row = short.iloc[0]
        raise RuntimeError(
            f"join match rate below the {floor_pct:.0f}% floor for model {row['model']} at "
            f"lead {int(row['lead_h'])}h: {int(row['n_matched'])} of {int(row['n_forecast'])} "
            f"forecast rows matched an observation within ±{int(TOLERANCE.total_seconds() // 60)} "
            f"min ({row['matched_pct']:.2f}%). SPEC §4 requires the pipeline to stop rather than "
            "score a sample this thin — an unmatched forecast is never filled or interpolated"
        )

    matched = joined.loc[joined["is_matched"]].drop(columns=["is_matched"]).copy()
    if matched.empty:
        raise RuntimeError("no forecast row matched an observation; refusing to score nothing")

    over = matched.loc[matched["offset_min"].abs() > TOLERANCE.total_seconds() / 60.0 + 1e-9]
    if not over.empty:
        raise RuntimeError(
            f"{len(over)} matched row(s) lie outside the ±{TOLERANCE} join window "
            f"(worst {over['offset_min'].abs().max():.3f} min); the tolerance must never widen"
        )
    return matched.reset_index(drop=True), stats


def pair_valid_times(
    frame: pd.DataFrame, included_models: list[str], lead_h: int
) -> tuple[pd.DataFrame, int]:
    """SPEC §5 paired comparison: keep a ``valid_time`` only if **every** included model has it.

    Returns ``(paired, n_dropped)`` where ``n_dropped`` counts valid times present for at
    least one model but not for all of them.  Comparing models over different samples is
    the difference between a benchmark and a coincidence.
    """
    if not included_models:
        raise ValueError("pair_valid_times: the included model set is empty")
    subset = frame.loc[
        (frame["lead_h"] == lead_h) & (frame["model"].isin(included_models))
    ].copy()
    if subset.empty:
        raise RuntimeError(
            f"pair_valid_times: no matched rows at lead {lead_h}h for models {included_models}"
        )
    if subset.duplicated(subset=["model", "valid_time"]).any():
        raise RuntimeError(
            f"pair_valid_times: duplicate (model, valid_time) rows at lead {lead_h}h"
        )
    counts = subset.groupby("valid_time")["model"].nunique()
    complete = counts.index[counts == len(included_models)]
    n_dropped = int(len(counts) - len(complete))
    paired = subset.loc[subset["valid_time"].isin(complete)].sort_values(
        ["valid_time", "model"], kind="mergesort"
    )
    if paired.empty:
        raise RuntimeError(
            f"pair_valid_times: no valid_time at lead {lead_h}h is covered by all "
            f"{len(included_models)} included models {included_models}; there is nothing to "
            "compare (FR4). An empty paired sample scores perfectly and is fake"
        )
    expected_rows = len(complete) * len(included_models)
    if len(paired) != expected_rows:
        raise RuntimeError(
            f"pair_valid_times: expected {expected_rows} paired rows at lead {lead_h}h "
            f"({len(complete)} valid times x {len(included_models)} models), got {len(paired)}"
        )
    return paired.reset_index(drop=True), n_dropped
