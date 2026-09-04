"""SPEC §7 — assemble the results document, with the guards that make it trustworthy.

This module turns a matched, paired frame into the exact JSON shape ``backend/contract.py``
locks, and refuses to hand back a document it cannot defend.  Three of its rules are the
difference between a real experiment and a confident-looking fiction:

1. **``models[].mae/rmse/bias`` are TEST-SPLIT (out-of-sample) numbers** (D2).  "MAE per
   model" reads like a whole-window number; it is not.  ``contract.py``'s
   corner-agreement check forces this, and getting it wrong is the single easiest fatal
   mistake in the ticket.
2. **They are computed by ``score.metrics.model_metrics`` — PATH A — and are never
   copied from the corner blend** (D4).  Copying would make the contract's corner check
   trivially true and would leave the SPEC §8 identity testing nothing at all.
3. **The one-hot identity is re-checked at runtime, on the real numbers, before
   rounding** (:func:`check_one_hot_identity`).  ``tests/test_blend.py`` proves the
   identity on synthetic data; this proves it on the data that actually shipped.  An
   explicit ``raise``, never an ``assert`` — ``python -O`` strips asserts.

Two further asymmetries are deliberate and enforced (D12/D13):

* **``winner`` is the in-sample argmin**, reported out-of-sample.  ``blends[0]`` — the
  out-of-sample leader — is explicitly *rejected* as the winner rule, because choosing
  the winner on the test split makes a win true by construction.
* **``best_single_model`` is the lowest out-of-sample corner.**  The baseline gets
  hindsight; the blend does not.  This makes it *harder* for the blend to win, which is
  what makes a win mean anything.  ``improvement_pct_vs_best_single`` is signed and is
  never clamped: zero and negative are legal, expected results (SPEC §10).

``meta``'s keys are exactly locked by ``contract._exact_keys``.  The grid-cell vs station
elevation delta and any other diagnostic **cannot** go here; they belong in T6's README.

Coverage is **read** from ``data/coverage.json``, never recomputed (D3) — T4 owns it, and
two sources of truth will disagree at 16:00.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

import numpy as np
import pandas as pd

from backend.contract import validate_results  # read-only; never make_fixture (D6)
from score import metrics
from score.blend import GRID_STEP_DENOM, MODELS, blend_table, canonical_model_name
from score.join import pair_valid_times
from score.split import TEST_DAYS, TRAIN_DAYS, chronological_split

__all__ = [
    "SITE",
    "LEAD_TIMES",
    "COVERAGE_FLOOR_PCT",
    "ROUND_DP",
    "ONE_HOT_TOL",
    "resolve_models",
    "check_one_hot_identity",
    "build_document",
]

#: The real KOMA block (SPEC §3). No "(SYNTHETIC FIXTURE)" suffix — this document is real.
SITE: dict = {
    "id": "KOMA",
    "iem_station": "OMA",
    "name": "Omaha Eppley Airfield",
    "lat": 41.3032,
    "lon": -95.8941,
    "station_elev_m": 295.7,
}

LEAD_TIMES: tuple[int, ...] = (6, 12, 24)
INIT_RUNS: tuple[str, ...] = ("00z", "06z", "12z", "18z")
WINDOW_DAYS = 30
SOURCE = "noaa_s3_grib"
VARIABLE = "2m_temperature"
UNITS = "degF"

#: SPEC §5 / FR5 coverage floor. Exactly 90.0 passes; 89.99 excludes.
COVERAGE_FLOOR_PCT = 90.0

#: Every emitted float goes through one rounding helper so the contract's 1e-9 corner
#: agreement survives serialisation (D5).
ROUND_DP = 4

#: Runtime one-hot identity tolerance. The pytest version uses none at all; this one
#: allows 1e-9 only because it also guards rmse/bias against a genuinely different path.
ONE_HOT_TOL = 1e-9


def _round(value: float) -> float:
    """The single rounding helper. Applied identically to models[] and to the corners."""
    return round(float(value), ROUND_DP)


def _iso_z(ts) -> str:
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        raise ValueError(f"timestamp {stamp!r} is tz-naive; UTC everywhere (CLAUDE.md)")
    return stamp.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- coverage


def resolve_models(
    coverage: dict, models: Sequence[str] = MODELS
) -> tuple[list[str], list[dict], dict[str, dict[str, float]]]:
    """Apply the 90% coverage floor, reading — never recomputing — ``coverage.json`` (D3).

    Returns ``(included, excluded_entries, per_lead_pct)``.  The floor is applied to the
    **overall per-model** ``coverage_pct``; ``models[].coverage_pct`` reports the
    **per-(model, lead)** value.  A model below the floor is dropped from the study
    entirely: the grid, the pairing and every metric shrink to the included set.
    """
    if not isinstance(coverage, dict) or "models" not in coverage:
        raise ValueError("coverage document is missing its 'models' block (T4 owns this file)")
    block = coverage["models"]
    included: list[str] = []
    excluded: list[dict] = []
    per_lead: dict[str, dict[str, float]] = {}

    for display in models:
        key = next((k for k in block if canonical_model_name(k) == display), None)
        if key is None:
            raise ValueError(
                f"coverage document has no entry for model {display!r}; it lists "
                f"{sorted(block)}. Coverage is read from data/coverage.json and never "
                "recomputed here (D3), so a missing model cannot be filled in"
            )
        entry = block[key]
        overall = float(entry["coverage_pct"])
        per_lead[display] = {
            str(lead): float(sub["coverage_pct"]) for lead, sub in entry.get("by_lead", {}).items()
        }
        if overall < COVERAGE_FLOOR_PCT:
            excluded.append(
                {
                    "model": display,
                    "coverage_pct": _round(overall),
                    "reason": (
                        f"coverage {overall:.2f}% is below the {COVERAGE_FLOOR_PCT:.0f}% floor "
                        "(SPEC §5); the model is dropped from the study rather than scored on a "
                        "different sample from the others"
                    ),
                }
            )
        else:
            included.append(display)

    if not included:
        raise RuntimeError(
            f"every model is below the {COVERAGE_FLOOR_PCT:.0f}% coverage floor; there is "
            "nothing to score"
        )
    overlap = sorted(set(included) & {e["model"] for e in excluded})
    if overlap:
        raise RuntimeError(f"model(s) {overlap} are both included and excluded")
    return included, excluded, per_lead


# --------------------------------------------------------------------------- guards


def check_one_hot_identity(
    lead_h: int,
    model: str,
    path_a: tuple[float, float, float],
    corner: dict,
    tol: float = ONE_HOT_TOL,
) -> None:
    """SPEC §8 acceptance floor, enforced in production on the real, **unrounded** numbers.

    ``path_a`` is ``score.metrics.model_metrics`` on the test split; ``corner`` is that
    model's one-hot row from ``score.blend.blend_table``.  The two were computed by
    completely different routes and must agree.  A mismatch means a model column was
    mixed up in the matmul, and every number on the page would be fiction — so this
    raises rather than warns.
    """
    pairs = (
        ("mae", path_a[0], float(corner["mae_out_of_sample"])),
        ("rmse", path_a[1], float(corner["rmse_out_of_sample"])),
        ("bias", path_a[2], float(corner["bias_out_of_sample"])),
    )
    for name, a, b in pairs:
        if not np.isfinite(a) or not np.isfinite(b):
            raise RuntimeError(
                f"one-hot identity check at lead {lead_h}h, model {model}: {name} is not "
                f"finite (PATH A {a!r}, one-hot corner {b!r})"
            )
        if abs(a - b) > tol:
            raise RuntimeError(
                f"one-hot identity BROKEN at lead {lead_h}h for model {model}: "
                f"metrics.model_metrics {name}={a!r} but the one-hot corner blend reports "
                f"{name}_out_of_sample={b!r} (difference {abs(a - b)!r} > {tol}). "
                "A one-hot weight vector must reproduce that model's own error exactly "
                "(SPEC §8). This almost always means the design matrix columns and the "
                "weight vector columns disagree — every blended number would be wrong"
            )


def _corner_rows(blends: list[dict], included: list[str]) -> dict[str, dict]:
    corners: dict[str, dict] = {}
    for row in blends:
        pure = [
            m
            for m in included
            if int(round(float(row["weights"][m]) * GRID_STEP_DENOM)) == GRID_STEP_DENOM
        ]
        if pure:
            corners[pure[0]] = row
    missing = [m for m in included if m not in corners]
    if missing:
        raise RuntimeError(
            f"one-hot corner(s) for {missing} are missing from the blend table; every pure "
            "model must be present regardless of rank (SPEC §7) — truncation silently breaks "
            "the demo slider"
        )
    return corners


# --------------------------------------------------------------------------- assembly


def _build_lead(
    lead_h: int,
    matched: pd.DataFrame,
    stats: pd.DataFrame,
    included: list[str],
    per_lead_coverage: dict[str, dict[str, float]],
) -> tuple[dict, pd.Series]:
    paired, n_dropped_pairing = pair_valid_times(matched, included, lead_h)
    train, test = chronological_split(paired)

    lead_stats = stats.loc[
        (stats["lead_h"] == lead_h) & (stats["model"].isin(included))
    ]
    if lead_stats.empty:
        raise RuntimeError(f"no join statistics for lead {lead_h}h; cannot report diagnostics")
    n_forecast = int(lead_stats["n_forecast"].sum())
    n_matched = int(lead_stats["n_matched"].sum())
    matched_pct = 100.0 * n_matched / n_forecast
    lead_rows = matched.loc[
        (matched["lead_h"] == lead_h) & (matched["model"].isin(included))
    ]
    mean_abs_offset = float(np.mean(np.abs(lead_rows["offset_min"].to_numpy(dtype=float))))

    blends = blend_table(train, test, included)
    corners = _corner_rows(blends, included)

    model_entries = []
    for model in included:
        # PATH A — computed independently of the blend engine, NEVER copied from the corner.
        path_a = metrics.model_metrics(test, model)
        # PATH B — the same model as a one-hot weight vector. Checked BEFORE rounding.
        check_one_hot_identity(lead_h, model, path_a, corners[model])
        coverage_pct = per_lead_coverage.get(model, {}).get(str(lead_h))
        if coverage_pct is None:
            raise ValueError(
                f"coverage.json has no by_lead entry for model {model} at lead {lead_h}h; "
                "coverage is read, never recomputed (D3)"
            )
        model_entries.append(
            {
                "model": model,
                "mae": _round(path_a[0]),
                "rmse": _round(path_a[1]),
                "bias": _round(path_a[2]),
                "coverage_pct": _round(coverage_pct),
            }
        )

    # Winner: the in-sample argmin, tie broken by lowest grid_index (D7/D12).
    # blends[0] — the out-of-sample leader — is deliberately NOT the rule.
    winner_row = min(blends, key=lambda r: (r["mae_in_sample"], r["grid_index"]))
    # best_single_model: the lowest OUT-OF-SAMPLE corner. The baseline gets hindsight.
    best_model = min(
        included, key=lambda m: (corners[m]["mae_out_of_sample"], included.index(m))
    )

    emitted_blends = [
        {
            "rank": index + 1,
            "weights": {m: _round(row["weights"][m]) for m in included},
            "label": row["label"],
            "is_pure": bool(row["is_pure"]),
            "mae_in_sample": _round(row["mae_in_sample"]),
            "mae_out_of_sample": _round(row["mae_out_of_sample"]),
            "rmse_out_of_sample": _round(row["rmse_out_of_sample"]),
            "bias_out_of_sample": _round(row["bias_out_of_sample"]),
        }
        for index, row in enumerate(blends)
    ]

    winner_label = winner_row["label"]
    winner_emitted = next(b for b in emitted_blends if b["label"] == winner_label)
    best_single_mae = _round(corners[best_model]["mae_out_of_sample"])
    winner_mae = winner_emitted["mae_out_of_sample"]
    if best_single_mae == 0:
        raise RuntimeError(
            f"lead {lead_h}h: best single model {best_model} has an out-of-sample MAE of "
            "exactly zero. A perfect forecast is not a result, it is a bug — investigate "
            "the join before shipping (SPEC §10)"
        )
    # Signed, never clamped, never abs()'d. Zero and negative are legal results (SPEC §10).
    improvement = (best_single_mae - winner_mae) / best_single_mae * 100.0

    lead_doc = {
        "n_samples": {
            "train": int(train["valid_time"].nunique()),
            "test": int(test["valid_time"].nunique()),
        },
        "join_diagnostics": {
            "matched_pct": _round(matched_pct),
            "mean_abs_offset_min": _round(mean_abs_offset),
        },
        "models": model_entries,
        "blends": emitted_blends,
        "best_single_model": {"model": best_model, "mae_out_of_sample": best_single_mae},
        "winner": {
            "label": winner_label,
            "mae_out_of_sample": winner_mae,
            "improvement_pct_vs_best_single": _round(improvement),
        },
    }
    diagnostics = {
        "lead_h": lead_h,
        "n_paired_valid_times": int(paired["valid_time"].nunique()),
        "n_dropped_to_pairing": n_dropped_pairing,
        "n_forecast_rows": n_forecast,
        "n_matched_rows": n_matched,
        "max_abs_offset_min": float(np.max(np.abs(lead_rows["offset_min"].to_numpy(dtype=float)))),
        "winner_oos_rank": winner_emitted["rank"],
    }
    return lead_doc, (paired["valid_time"], diagnostics)


def build_document(
    matched: pd.DataFrame,
    stats: pd.DataFrame,
    coverage: dict,
    *,
    lead_times: Sequence[int] = LEAD_TIMES,
    generated_at: str | None = None,
    site: dict | None = None,
    validate: bool = True,
) -> tuple[dict, list[dict]]:
    """Build the SPEC §7 document. Returns ``(document, per_lead_diagnostics)``.

    ``matched`` is the joined frame from :func:`score.join.join_forecasts_to_obs`,
    ``stats`` its per-``(model, lead)`` companion, and ``coverage`` the parsed
    ``data/coverage.json``.  With ``validate=True`` the finished document is put through
    ``backend.contract.validate_results`` before it is returned, so an invalid document
    can never reach a caller — let alone disk.
    """
    included, excluded, per_lead_coverage = resolve_models(coverage)
    stray = sorted(set(matched["model"].unique()) - set(included) - {e["model"] for e in excluded})
    if stray:
        raise ValueError(f"matched frame carries unrecognised model(s) {stray}")

    results: dict[str, dict] = {}
    diagnostics: list[dict] = []
    window_times: list[pd.Series] = []
    for lead in lead_times:
        lead_doc, (valid_times, diag) = _build_lead(
            int(lead), matched, stats, included, per_lead_coverage
        )
        results[str(int(lead))] = lead_doc
        diagnostics.append(diag)
        window_times.append(valid_times)

    all_times = pd.concat(window_times)
    document = {
        "meta": {
            "site": dict(site or SITE),
            "variable": VARIABLE,
            "units": UNITS,
            "window": {
                "start": _iso_z(all_times.min()),
                "end": _iso_z(all_times.max()),
                "days": WINDOW_DAYS,
            },
            "init_runs": list(INIT_RUNS),
            "source": SOURCE,
            "generated_at": generated_at
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "is_synthetic": False,
            "models_included": list(included),
            "models_excluded": excluded,
            "split": {
                "method": "chronological",
                "train_days": TRAIN_DAYS,
                "test_days": TEST_DAYS,
            },
        },
        "lead_times": [int(lead) for lead in lead_times],
        "results": results,
    }
    if validate:
        validate_results(document)
    return document, diagnostics
