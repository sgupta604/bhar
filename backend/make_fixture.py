"""Deterministic synthetic ``results.json`` generator — the demo's insurance artifact.

Run it with::

    uv run python -m backend.make_fixture

It writes both ``data/results.synthetic.json`` (durable copy, never auto-served) and
``data/results.json`` (the file the API serves), pretty-printed with a trailing
newline, after ``backend.contract.validate_results`` has accepted the document.
Nothing is written if validation fails.

**This payload is fake and says so loudly** (SPEC §10, D2/D3): ``meta.is_synthetic``
is ``true``, ``meta.source`` is ``"synthetic_fixture"``, the site name carries
``(SYNTHETIC FIXTURE)``, and every headline number is a repdigit — 5.55, 6.66, 7.77,
8.88 — so no one mistakes it for a real MAE at 16:00.

How the numbers are built
-------------------------
Each lead time gets two error surfaces, one in-sample and one out-of-sample.  A model
*i* is given a 2-D error vector ``m_i * (cos θ_i, sin θ_i)``; a blend's error is the
norm of the weighted sum::

    mae(w) = || Σ w_i · m_i · (cos θ_i, sin θ_i) ||

That is convex, reproduces each pure model's MAE exactly at its own corner (the corner
value is ``m_i`` regardless of angle), and has a genuine interior dip whenever the
angles differ — errors that point in different directions partly cancel.  The in-sample
and out-of-sample surfaces use different magnitudes and different angles, so their
minima sit in different places: exactly what a train/test split looks like.

The out-of-sample angles are the base angles scaled by ``alpha``.  As ``alpha → 0`` the
models' errors become collinear, the surface becomes linear, and no blend can beat the
best pure corner.  ``alpha`` is therefore the knob that decides the sign of the reported
improvement, and it is chosen by a **deterministic scan** over a fixed, ordered list of
candidates per lead — the first candidate landing in that lead's target band wins, and
the band is re-asserted afterwards.  No randomness is involved.

Blend labels
------------
A label must identify exactly one blend, because the frontend locates the winner row by
label (D13) and the SPEC's ``"70 / 30"`` example is ambiguous across model pairs.  The
rule here is:

* pure blend  → ``"HRRR only"``
* mixed blend → model name + integer percent for every **nonzero** weight, in canonical
  model order, joined by ``" / "`` — ``"HRRR 70 / GFS 30"``, ``"HRRR 50 / GFS 30 / NBM 20"``.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

from backend.contract import ContractError, validate_results

__all__ = ["build_document", "write_fixture", "simplex_grid", "blend_label", "main"]

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
SYNTHETIC_FILENAME = "results.synthetic.json"
SERVED_FILENAME = "results.json"

#: Canonical model order. Used for weights keys, labels and the models[] array.
MODELS: tuple[str, ...] = ("HRRR", "GFS", "NAM", "NBM")
LEAD_TIMES: tuple[int, ...] = (6, 12, 24)
GRID_STEP_DENOM = 10

#: The real KOMA block (SPEC §3) with a name that cannot be mistaken for real data.
SITE = {
    "id": "KOMA",
    "iem_station": "OMA",
    "name": "Omaha Eppley Airfield (SYNTHETIC FIXTURE)",
    "lat": 41.3032,
    "lon": -95.8941,
    "station_elev_m": 295.7,
}

#: Pure-model out-of-sample MAEs, in degF. Repdigits on purpose (D3).
#: Every models[].mae equals the model's own one-hot blend mae_out_of_sample.
PURE_MAE: dict[int, dict[str, float]] = {
    6: {"HRRR": 5.55, "GFS": 7.77, "NAM": 8.88, "NBM": 6.66},
    12: {"HRRR": 6.66, "GFS": 8.88, "NAM": 9.99, "NBM": 7.77},
    24: {"HRRR": 8.88, "GFS": 9.99, "NAM": 11.11, "NBM": 7.77},
}

#: Base error-vector directions, degrees. Spread under 180° so the origin stays outside
#: the hull and no blend can reach a physically silly MAE of zero.
BASE_ANGLE_DEG: dict[str, float] = {"HRRR": -40.0, "GFS": 25.0, "NAM": 50.0, "NBM": -5.0}

#: In-sample magnitudes are the out-of-sample ones scaled per model. The factors differ
#: between models so the fitted (in-sample) optimum is not the out-of-sample optimum.
IN_SAMPLE_MAG_FACTOR: dict[str, float] = {"HRRR": 0.86, "GFS": 0.90, "NAM": 0.84, "NBM": 0.92}

#: Per-model signed bias, degF. Blend bias is the weighted sum (bias is linear in w).
MODEL_BIAS: dict[str, float] = {"HRRR": -0.55, "GFS": 1.11, "NAM": -2.22, "NBM": 0.33}

#: Per-model coverage, all above the 90% floor — the excluded model is RAP (D14).
MODEL_COVERAGE: dict[str, float] = {"HRRR": 99.9, "GFS": 98.8, "NAM": 96.6, "NBM": 97.7}

RMSE_FACTOR = 1.27

JOIN_DIAGNOSTICS = {"matched_pct": 88.88, "mean_abs_offset_min": 8.88}
N_SAMPLES = {"train": 88, "test": 44}

#: Ordered alpha candidates. Descending is used where the demo wants the *most* aligned
#: surface still satisfying the band; ascending where it wants the least.
_ALPHA_DESC: tuple[float, ...] = tuple(round(1.0 - 0.005 * k, 3) for k in range(191))
_ALPHA_ASC: tuple[float, ...] = tuple(reversed(_ALPHA_DESC))


def _shape_6h(improvement: float, winner_is_oos_argmin: bool) -> bool:
    # Positive with room to spare, and the fitted winner must NOT be leaderboard row 1 —
    # otherwise a frontend that reads blends[0] would look correct here (D13).
    return improvement > 1.0 and not winner_is_oos_argmin


def _shape_12h(improvement: float, winner_is_oos_argmin: bool) -> bool:
    return abs(improvement) <= 0.05


def _shape_24h(improvement: float, winner_is_oos_argmin: bool) -> bool:
    # Visibly negative, not a rounding-width negative, so the honest-loss path is legible.
    return improvement < -1.0


#: lead -> (ordered candidate alphas, scan predicate, required band, band description)
_LEAD_SCAN = {
    6: (_ALPHA_DESC, _shape_6h, lambda imp: imp > 0.05, "improvement > +0.05 pp"),
    12: (_ALPHA_ASC, _shape_12h, lambda imp: abs(imp) <= 0.05, "|improvement| <= 0.05 pp"),
    24: (_ALPHA_DESC, _shape_24h, lambda imp: imp < -0.05, "improvement < -0.05 pp"),
}


def simplex_grid(n_models: int = len(MODELS), step_denom: int = GRID_STEP_DENOM) -> list[tuple]:
    """Every weight vector on the full simplex at step ``1/step_denom``, in a fixed order."""
    grid = [
        tuple(round(k / step_denom, 10) for k in combo)
        for combo in product(range(step_denom + 1), repeat=n_models)
        if sum(combo) == step_denom
    ]
    expected = math.comb(step_denom + n_models - 1, n_models - 1)
    if len(grid) != expected:
        raise RuntimeError(
            f"simplex grid has {len(grid)} vectors, expected {expected} "
            f"(C({step_denom + n_models - 1}, {n_models - 1})); a truncated grid breaks "
            "the weight slider (FR8/D5)"
        )
    return grid


def blend_label(weights: tuple[float, ...]) -> str:
    """Unique human label for a weight vector. See the module docstring for the rule."""
    parts = [
        (model, int(round(w * 100)))
        for model, w in zip(MODELS, weights)
        if int(round(w * GRID_STEP_DENOM)) > 0
    ]
    if len(parts) == 1:
        return f"{parts[0][0]} only"
    return " / ".join(f"{model} {pct}" for model, pct in parts)


def _surface_mae(
    weights: tuple[float, ...],
    magnitudes: dict[str, float],
    angles_deg: dict[str, float],
) -> float:
    """Norm of the weighted sum of the models' 2-D error vectors."""
    x = 0.0
    y = 0.0
    for model, w in zip(MODELS, weights):
        radians = math.radians(angles_deg[model])
        x += w * magnitudes[model] * math.cos(radians)
        y += w * magnitudes[model] * math.sin(radians)
    return math.hypot(x, y)


def _argmin_index(values: list[float]) -> int:
    """Index of the smallest value, ties broken by the fixed grid order."""
    return min(range(len(values)), key=lambda i: (values[i], i))


def _build_lead(lead: int, grid: list[tuple]) -> dict:
    oos_mag = PURE_MAE[lead]
    in_mag = {m: oos_mag[m] * IN_SAMPLE_MAG_FACTOR[m] for m in MODELS}

    in_sample = [round(_surface_mae(w, in_mag, BASE_ANGLE_DEG), 2) for w in grid]
    fitted_index = _argmin_index(in_sample)

    # best_single_model is a corner value, and corner values do not depend on the angles,
    # so it is fixed before the scan.
    best_model = min(MODELS, key=lambda m: (round(oos_mag[m], 2), MODELS.index(m)))
    best_single_mae = round(oos_mag[best_model], 2)

    candidates, shape_ok, band_ok, band_text = _LEAD_SCAN[lead]
    chosen = None
    for alpha in candidates:
        angles = {m: BASE_ANGLE_DEG[m] * alpha for m in MODELS}
        oos = [round(_surface_mae(w, oos_mag, angles), 2) for w in grid]
        improvement = round((best_single_mae - oos[fitted_index]) / best_single_mae * 100.0, 2)
        if shape_ok(improvement, _argmin_index(oos) == fitted_index):
            chosen = (alpha, angles, oos, improvement)
            break
    if chosen is None:
        raise RuntimeError(f"lead {lead}h: no candidate alpha produced {band_text}")
    alpha, angles, out_of_sample, improvement = chosen
    if not band_ok(improvement):
        raise RuntimeError(
            f"lead {lead}h: alpha {alpha} gives improvement {improvement} pp, "
            f"outside the required band ({band_text})"
        )

    entries = []
    for index, weights in enumerate(grid):
        nonzero = [int(round(w * GRID_STEP_DENOM)) for w in weights]
        entries.append(
            {
                "_index": index,
                "weights": {m: w for m, w in zip(MODELS, weights)},
                "label": blend_label(weights),
                "is_pure": max(nonzero) == GRID_STEP_DENOM,
                "mae_in_sample": in_sample[index],
                "mae_out_of_sample": out_of_sample[index],
                "rmse_out_of_sample": round(
                    _surface_mae(weights, oos_mag, angles) * RMSE_FACTOR, 2
                ),
                "bias_out_of_sample": round(
                    sum(w * MODEL_BIAS[m] for m, w in zip(MODELS, weights)), 2
                ),
            }
        )

    winner_entry = entries[fitted_index]
    ordered = sorted(entries, key=lambda e: (e["mae_out_of_sample"], e["_index"]))
    blends = []
    for rank, entry in enumerate(ordered, start=1):
        blend = {"rank": rank}
        blend.update({k: v for k, v in entry.items() if k != "_index"})
        blends.append(blend)

    return {
        "n_samples": dict(N_SAMPLES),
        "join_diagnostics": dict(JOIN_DIAGNOSTICS),
        "models": [
            {
                "model": m,
                "mae": round(oos_mag[m], 2),
                "rmse": round(oos_mag[m] * RMSE_FACTOR, 2),
                "bias": MODEL_BIAS[m],
                "coverage_pct": MODEL_COVERAGE[m],
            }
            for m in MODELS
        ],
        "blends": blends,
        "best_single_model": {"model": best_model, "mae_out_of_sample": best_single_mae},
        "winner": {
            "label": winner_entry["label"],
            "mae_out_of_sample": winner_entry["mae_out_of_sample"],
            "improvement_pct_vs_best_single": improvement,
        },
    }


def _utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_document(generated_at: str | None = None) -> dict:
    """Build the whole synthetic document.

    ``generated_at`` defaults to the real current UTC time — honest metadata about a
    dishonest payload. Tests pin it to assert byte-identical output.
    """
    grid = simplex_grid()
    return {
        "meta": {
            "site": dict(SITE),
            "variable": "2m_temperature",
            "units": "degF",
            "window": {"start": "2026-08-05T00:00:00Z", "end": "2026-09-04T00:00:00Z", "days": 30},
            "init_runs": ["00z", "06z", "12z", "18z"],
            "source": "synthetic_fixture",
            "generated_at": generated_at or _utc_now_stamp(),
            "is_synthetic": True,
            "models_included": list(MODELS),
            "models_excluded": [
                {"model": "RAP", "coverage_pct": 71.2, "reason": "below 90% coverage floor"}
            ],
            "split": {"method": "chronological", "train_days": 20, "test_days": 10},
        },
        "lead_times": list(LEAD_TIMES),
        "results": {str(lead): _build_lead(lead, grid) for lead in LEAD_TIMES},
    }


def write_fixture(out_dir: str | Path, generated_at: str | None = None) -> dict:
    """Validate, then write both fixture files into ``out_dir``. Returns the document."""
    doc = build_document(generated_at=generated_at)
    validate_results(doc)  # raises ContractError; nothing is written on failure
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, indent=2) + "\n"
    for name in (SYNTHETIC_FILENAME, SERVED_FILENAME):
        (target / name).write_text(payload, encoding="utf-8")
    return doc


def main() -> int:
    try:
        doc = write_fixture(DATA_DIR)
    except ContractError as exc:
        print(f"REFUSING TO WRITE: the generated document violates the contract\n  {exc}")
        return 1
    print(f"wrote {DATA_DIR / SYNTHETIC_FILENAME}")
    print(f"wrote {DATA_DIR / SERVED_FILENAME}")
    print(f"generated_at={doc['meta']['generated_at']}  is_synthetic={doc['meta']['is_synthetic']}")
    for lead in LEAD_TIMES:
        block = doc["results"][str(lead)]
        winner = block["winner"]
        best = block["best_single_model"]
        print(
            f"  {lead:>2}h  blends={len(block['blends'])}  "
            f"best_single={best['model']} {best['mae_out_of_sample']}  "
            f"winner={winner['label']} {winner['mae_out_of_sample']}  "
            f"improvement={winner['improvement_pct_vs_best_single']:+.2f} pp  "
            f"(winner is leaderboard row "
            f"{next(b['rank'] for b in block['blends'] if b['label'] == winner['label'])})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
