"""PATH A — per-model error metrics, computed with no knowledge of weight vectors.

This module is one half of the SPEC §8 acceptance floor.  ``score/blend.py`` computes
the *same* three numbers for a one-hot weight vector by a completely different route
(a pivot and a matrix multiply).  The two must agree **bit-exactly**, and they can only
be evidence of anything if they stay independent: nothing here may import
``score.blend`` or accept a weight vector.  ``grep -n "blend" score/metrics.py`` must
return nothing.

Sign conventions (they are displayed on the page, so they are part of the contract):

* ``bias = mean(forecast - observation)``.  A forecast that runs warm has a
  **positive** bias.
* ``mae``  = ``mean(|forecast - observation|)``
* ``rmse`` = ``sqrt(mean((forecast - observation)^2))``

All three return **unrounded** floats.  Rounding happens exactly once, in
``score/build.py``, after the unrounded one-hot identity has been checked (D5).

Guards are explicit ``raise`` statements, never ``assert`` — ``python -O`` strips
asserts, and an empty input scores perfectly and is fake (SPEC §4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["mae", "rmse", "bias", "model_metrics"]

#: Columns a joined/paired frame must carry for the per-model path.
FORECAST_COL = "temp_f"
OBS_COL = "obs_f"


def _errors(pred, obs) -> np.ndarray:
    """``pred - obs`` as a 1-D contiguous float64 array, with an anti-fake guard."""
    p = np.ascontiguousarray(np.asarray(pred, dtype=np.float64).ravel())
    o = np.ascontiguousarray(np.asarray(obs, dtype=np.float64).ravel())
    if p.size != o.size:
        raise ValueError(
            f"forecast and observation arrays have different lengths ({p.size} vs {o.size}); "
            "they must be the paired, row-aligned samples"
        )
    if p.size == 0:
        raise ValueError(
            "cannot score an empty sample: an empty join scores perfectly and is fake "
            "(SPEC §4). Check the join and the pairing before scoring."
        )
    if not np.isfinite(p).all() or not np.isfinite(o).all():
        raise ValueError(
            "forecast/observation arrays contain non-finite values; observations are never "
            "interpolated or filled, so unmatched rows must be dropped before scoring (SPEC §4)"
        )
    return p - o


def mae(pred, obs) -> float:
    """Mean absolute error, ``mean(|forecast - observation|)``, unrounded."""
    err = _errors(pred, obs)
    return float(np.mean(np.abs(err)))


def rmse(pred, obs) -> float:
    """Root mean squared error, ``sqrt(mean((forecast - observation)^2))``, unrounded."""
    err = _errors(pred, obs)
    return float(np.sqrt(np.mean(err * err)))


def bias(pred, obs) -> float:
    """Signed mean error, ``mean(forecast - observation)``. Warm forecast => positive."""
    err = _errors(pred, obs)
    return float(np.mean(err))


def model_metrics(frame: pd.DataFrame, model: str) -> tuple[float, float, float]:
    """``(mae, rmse, bias)`` for one model over one already-subset frame.

    ``frame`` is a paired frame for a single lead time and a single split, carrying at
    least ``model``, ``valid_time``, ``temp_f`` (forecast) and ``obs_f`` (observation).

    Rows are ordered by ``valid_time`` ascending — the same order ``score.blend``'s
    pivot produces — so the two paths reduce identical arrays in an identical order and
    the SPEC §8 identity is exact rather than approximate.
    """
    for column in ("model", "valid_time", FORECAST_COL, OBS_COL):
        if column not in frame.columns:
            raise ValueError(
                f"model_metrics: frame is missing required column {column!r}; got "
                f"{list(frame.columns)}"
            )
    subset = frame.loc[frame["model"] == model].sort_values("valid_time")
    if subset.empty:
        raise ValueError(
            f"model_metrics: no rows for model {model!r} in this frame; an empty sample "
            "scores perfectly and is fake (SPEC §4)"
        )
    if subset["valid_time"].duplicated().any():
        dupes = subset.loc[subset["valid_time"].duplicated(), "valid_time"].unique()[:3]
        raise ValueError(
            f"model_metrics: model {model!r} has duplicate valid_time(s) {list(dupes)}; "
            "a duplicated valid time would double-count a sample"
        )
    pred = subset[FORECAST_COL].to_numpy(dtype=np.float64)
    obs = subset[OBS_COL].to_numpy(dtype=np.float64)
    return mae(pred, obs), rmse(pred, obs), bias(pred, obs)
