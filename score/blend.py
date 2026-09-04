"""PATH B — the simplex weight grid and the vectorised blend evaluator.

Three jobs live here:

1. ``MODELS`` — the **single** canonical model order for the whole ``score/`` package.
   The pivot columns, the weight-matrix columns, the ``weights`` dict keys, the
   ``models[]`` array and the blend labels all take their order from this one tuple.
2. ``simplex_grid`` / ``blend_label`` — re-implemented here rather than imported from
   ``backend.make_fixture`` (D6).  ``make_fixture`` is the *fake data* generator; wiring
   the real science to it would couple the two.  ``tests/test_blend.py`` holds a
   286-vector parity test that gets the guarantee without the coupling.
3. ``blend_metrics`` / ``blend_table`` — the blend error path: pivot the paired frame to
   ``P`` (n_valid x n_models), stack the weight vectors into ``W`` (n_grid x n_models),
   and evaluate ``P @ W.T`` in one matrix multiply.

Why the matmul, and why the guard
---------------------------------
A mis-ordered model column produces confident, wrong numbers with no error anywhere —
the top risk in this ticket.  Vectorising removes 286 hand-written indexings, and
:func:`evaluate_design` **raises** if ``P``'s columns are not exactly ``models`` before
it multiplies anything.  That guard lives in production code, not only in a test.

Why the per-vector reduction loop
---------------------------------
The matmul is one operation, but each vector's mean is reduced from its own **1-D
contiguous** array.  That is deliberate: ``score.metrics`` reduces 1-D contiguous arrays
too, so the two paths run byte-identical floating-point reductions and the SPEC §8
one-hot identity holds **bit-exactly, with no tolerance**.  Reducing along axis 0 of the
2-D result would use a different summation order and would force a tolerance — which is
exactly the crack the bug we are hunting would hide in.
"""

from __future__ import annotations

from itertools import product
from math import comb
from typing import Sequence

import numpy as np
import pandas as pd

__all__ = [
    "MODELS",
    "MODEL_NAME_MAP",
    "GRID_STEP_DENOM",
    "canonical_model_name",
    "simplex_grid",
    "blend_label",
    "one_hot",
    "design_matrix",
    "evaluate_design",
    "blend_metrics",
    "blend_table",
]

#: Canonical model order — the single source of truth for ordering in ``score/``.
MODELS: tuple[str, ...] = ("HRRR", "GFS", "NAM", "NBM")

#: The parquet stores lowercase model ids; the JSON and the frontend use these names.
#: Mapped in exactly one place, and the mapping is asserted total at the boundary.
MODEL_NAME_MAP: dict[str, str] = {"hrrr": "HRRR", "gfs": "GFS", "nam": "NAM", "nbm": "NBM"}

#: Weight grid step: ten tenths per unit (SPEC §5, D5). Matches ``contract.GRID_STEP_DENOM``.
GRID_STEP_DENOM = 10

#: Weight vectors must sum to 1 within this; ``contract.py`` uses the same figure.
WEIGHT_SUM_TOL = 1e-9


def canonical_model_name(raw: str) -> str:
    """Map a parquet model id to its display name. Raises if the mapping is not total."""
    key = str(raw).strip().lower()
    if key not in MODEL_NAME_MAP:
        raise ValueError(
            f"unknown model id {raw!r}: MODEL_NAME_MAP covers {sorted(MODEL_NAME_MAP)} only. "
            "An unmapped id would leak a lowercase name into results.json and break the "
            "frontend's model list"
        )
    return MODEL_NAME_MAP[key]


def simplex_grid(
    models: Sequence[str] | int = MODELS, step_denom: int = GRID_STEP_DENOM
) -> list[tuple[float, ...]]:
    """Every weight vector on the full simplex at step ``1/step_denom``, in a fixed order.

    The order is the lexicographic ``product(range(step_denom + 1), repeat=n)`` order
    filtered to ``sum == step_denom``.  A vector's position in this list is its
    ``grid_index`` — the deterministic tie-break key (D7).
    """
    n_models = models if isinstance(models, int) else len(models)
    if n_models < 1:
        raise ValueError(f"simplex_grid needs at least one model, got {n_models}")
    grid = [
        tuple(round(k / step_denom, 10) for k in combo)
        for combo in product(range(step_denom + 1), repeat=n_models)
        if sum(combo) == step_denom
    ]
    expected = comb(step_denom + n_models - 1, n_models - 1)
    if len(grid) != expected:
        raise RuntimeError(
            f"simplex grid has {len(grid)} vectors, expected {expected} "
            f"(C({step_denom + n_models - 1}, {n_models - 1})); a truncated grid silently "
            "breaks the weight slider (FR7/D5)"
        )
    return grid


def blend_label(weights: Sequence[float], models: Sequence[str] = MODELS) -> str:
    """Unique human label for a weight vector.

    One nonzero weight -> ``"HRRR only"``; otherwise ``" / "``-joined
    ``"<MODEL> <integer percent>"`` for every nonzero weight, in canonical order:
    ``"HRRR 70 / GFS 30"``.  Character-for-character identical to
    ``backend.make_fixture.blend_label`` (parity-tested over all 286 vectors), because
    the frontend locates the winner row **by label** and ``contract.py`` requires a label
    to identify exactly one blend.
    """
    if len(weights) != len(models):
        raise ValueError(
            f"blend_label: {len(weights)} weights for {len(models)} models {list(models)}"
        )
    parts = [
        (model, int(round(w * 100)))
        for model, w in zip(models, weights)
        if int(round(w * GRID_STEP_DENOM)) > 0
    ]
    if not parts:
        raise ValueError(f"blend_label: weight vector {tuple(weights)} has no nonzero weight")
    if len(parts) == 1:
        return f"{parts[0][0]} only"
    return " / ".join(f"{model} {pct}" for model, pct in parts)


def one_hot(model: str, models: Sequence[str] = MODELS) -> tuple[float, ...]:
    """The corner weight vector that selects ``model`` and nothing else."""
    if model not in models:
        raise ValueError(f"one_hot: {model!r} is not in {list(models)}")
    return tuple(1.0 if m == model else 0.0 for m in models)


# --------------------------------------------------------------------------- design


def design_matrix(
    frame: pd.DataFrame, models: Sequence[str] = MODELS
) -> tuple[pd.DataFrame, np.ndarray]:
    """Pivot a paired frame to ``(P, obs)``.

    ``P`` is ``(n_valid x n_models)`` with **columns explicitly reindexed to ``models``**
    — never left in whatever order ``pivot`` happened to produce — and its index is
    ``valid_time`` ascending, the same order :func:`score.metrics.model_metrics` reduces
    in.  ``obs`` is the matching 1-D observation array.
    """
    models = list(models)
    for column in ("model", "valid_time", "temp_f", "obs_f"):
        if column not in frame.columns:
            raise ValueError(
                f"design_matrix: frame is missing required column {column!r}; got "
                f"{list(frame.columns)}"
            )
    if frame.empty:
        raise ValueError(
            "design_matrix: empty frame; an empty sample scores perfectly and is fake (SPEC §4)"
        )
    extra = sorted(set(frame["model"].unique()) - set(models))
    if extra:
        raise ValueError(
            f"design_matrix: frame carries model(s) {extra} that are not in the included set "
            f"{models}; excluded models must be dropped before scoring (FR5)"
        )
    if frame.duplicated(subset=["model", "valid_time"]).any():
        raise ValueError(
            "design_matrix: duplicate (model, valid_time) rows would double-count a sample"
        )

    pivot = frame.pivot(index="valid_time", columns="model", values="temp_f")
    missing = [m for m in models if m not in pivot.columns]
    if missing:
        raise ValueError(
            f"design_matrix: no forecast rows for model(s) {missing}; the frame must be "
            "paired across every included model before scoring (FR4)"
        )
    P = pivot[models]  # explicit reindex — the ONLY place column order is established
    if P.isna().to_numpy().any():
        raise ValueError(
            "design_matrix: the pivot has holes, so some valid_time is missing a model; "
            "pair_valid_times() must run first (FR4). Observations are never filled (FR2)"
        )

    obs_series = (
        frame.drop_duplicates(subset=["valid_time"])
        .set_index("valid_time")["obs_f"]
        .reindex(P.index)
    )
    if obs_series.isna().any():
        raise ValueError("design_matrix: an observation is missing for a paired valid_time")
    # One valid_time must carry exactly one observation, whichever model row it came from.
    spread = frame.groupby("valid_time")["obs_f"].nunique(dropna=False)
    if (spread > 1).any():
        bad = spread[spread > 1].index[:3]
        raise ValueError(
            f"design_matrix: valid_time(s) {list(bad)} carry more than one observation value; "
            "observations are a single global series"
        )
    return P, np.ascontiguousarray(obs_series.to_numpy(dtype=np.float64))


def _metrics_1d(pred: np.ndarray, obs: np.ndarray) -> tuple[float, float, float]:
    """``(mae, rmse, bias)`` from two 1-D contiguous float64 arrays."""
    err = pred - obs
    return (
        float(np.mean(np.abs(err))),
        float(np.sqrt(np.mean(err * err))),
        float(np.mean(err)),
    )


def evaluate_design(
    P: pd.DataFrame, obs: np.ndarray, W: np.ndarray, models: Sequence[str] = MODELS
) -> np.ndarray:
    """Evaluate every weight vector in ``W`` against ``(P, obs)``.

    Returns an ``(n_grid, 3)`` array of ``(mae, rmse, bias)``.

    **The column-order guard below is the most important line in this module.**  A
    permuted ``P`` produces perfectly plausible, entirely wrong numbers and raises
    nothing anywhere else in the pipeline, so it raises here, in production code.
    """
    models = list(models)
    if not isinstance(P, pd.DataFrame):
        raise TypeError(f"evaluate_design: P must be a DataFrame so its columns can be checked, got {type(P).__name__}")
    if list(P.columns) != models:
        raise RuntimeError(
            f"evaluate_design: design matrix columns {list(P.columns)} are not the canonical "
            f"model order {models}. A permuted column order silently mixes one model's "
            "forecasts into another's weight and produces confident, wrong numbers (D10)"
        )
    W = np.ascontiguousarray(np.asarray(W, dtype=np.float64))
    if W.ndim != 2 or W.shape[1] != len(models):
        raise ValueError(
            f"evaluate_design: W has shape {W.shape}, expected (n_grid, {len(models)}) with "
            f"columns in the same order as P: {models}"
        )
    sums = W.sum(axis=1)
    off = np.nonzero(np.abs(sums - 1.0) > WEIGHT_SUM_TOL)[0]
    if off.size:
        raise ValueError(
            f"evaluate_design: weight vector at row {int(off[0])} sums to {sums[off[0]]!r}, "
            "not 1.0 within 1e-9"
        )
    Pm = np.ascontiguousarray(P.to_numpy(dtype=np.float64))
    if Pm.shape[0] != obs.shape[0]:
        raise ValueError(
            f"evaluate_design: P has {Pm.shape[0]} rows but obs has {obs.shape[0]}"
        )
    if Pm.shape[0] == 0:
        raise ValueError(
            "evaluate_design: empty sample; an empty join scores perfectly and is fake (SPEC §4)"
        )

    preds = Pm @ W.T  # (n_valid, n_grid) — one matmul, no per-model indexing
    obs_c = np.ascontiguousarray(obs, dtype=np.float64)
    out = np.empty((W.shape[0], 3), dtype=np.float64)
    for j in range(W.shape[0]):
        out[j] = _metrics_1d(np.ascontiguousarray(preds[:, j]), obs_c)
    return out


def blend_metrics(
    frame: pd.DataFrame, weights: Sequence[float], models: Sequence[str] = MODELS
) -> tuple[float, float, float]:
    """``(mae, rmse, bias)`` for a **single** weight vector — the SPEC §8 PATH B.

    Shares the identical matmul and reduction code path as :func:`blend_table`; a
    separate scalar implementation would defeat the whole point of the one-hot test.
    """
    P, obs = design_matrix(frame, models)
    row = evaluate_design(P, obs, np.asarray([list(weights)], dtype=np.float64), models)[0]
    return float(row[0]), float(row[1]), float(row[2])


def blend_table(
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    models: Sequence[str] = MODELS,
    grid: Sequence[Sequence[float]] | None = None,
) -> list[dict]:
    """Score the whole simplex on both splits and return the sorted ``blends`` rows.

    Sorted by ``(mae_out_of_sample, grid_index)`` ascending (D7), ranks assigned 1..N.
    **Every vector is emitted — no truncation, ever.**  The demo slider does an exact
    lookup into this array and every one-hot corner must be present whatever its rank.
    """
    models = list(models)
    grid = list(simplex_grid(models)) if grid is None else [tuple(v) for v in grid]
    W = np.asarray(grid, dtype=np.float64)

    P_tr, obs_tr = design_matrix(train_frame, models)
    P_te, obs_te = design_matrix(test_frame, models)
    in_sample = evaluate_design(P_tr, obs_tr, W, models)
    out_sample = evaluate_design(P_te, obs_te, W, models)

    rows: list[dict] = []
    for index, vector in enumerate(grid):
        tenths = [int(round(w * GRID_STEP_DENOM)) for w in vector]
        rows.append(
            {
                "grid_index": index,
                "weights": {m: float(w) for m, w in zip(models, vector)},
                "label": blend_label(vector, models),
                "is_pure": max(tenths) == GRID_STEP_DENOM,
                "mae_in_sample": float(in_sample[index, 0]),
                "mae_out_of_sample": float(out_sample[index, 0]),
                "rmse_out_of_sample": float(out_sample[index, 1]),
                "bias_out_of_sample": float(out_sample[index, 2]),
            }
        )

    labels = [r["label"] for r in rows]
    if len(set(labels)) != len(labels):
        raise RuntimeError(
            "blend_table: blend labels are not unique; the frontend finds the winner row by "
            "label and contract.py requires a label to identify exactly one blend (TR3)"
        )
    rows.sort(key=lambda r: (r["mae_out_of_sample"], r["grid_index"]))
    if len(rows) != len(grid):
        raise RuntimeError(f"blend_table: emitted {len(rows)} of {len(grid)} blends; never truncate")
    return rows
