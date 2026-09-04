"""SPEC §7 document assembly — shape, the coverage floor, and the two asymmetries.

Everything here is pure logic on synthetic frames: **no parquet is read and no socket is
opened** (SPEC §13, TR5). The real-data run is exercised by ``score/run.py``, not by the
test suite.

The three things most worth failing on:

* ``models[]`` carries **test-split** numbers, computed by ``metrics.model_metrics``
  (PATH A) and **not copied** from the corner blend — copying would make the contract's
  corner-agreement check trivially true and would test nothing.
* ``winner`` is the **in-sample** argmin, ``best_single_model`` is the **out-of-sample**
  best corner, and ``improvement_pct_vs_best_single`` is signed. A negative improvement
  is a legal, expected result and the contract accepts it.
* The exclusion path is exercised with synthetic 3- and 2-model coverage inputs (D9).
  All four real models sit at 100%, and manufacturing a real exclusion would be tuning
  the experiment (SPEC §10).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backend.contract import ContractError, validate_results
from score import metrics
from score.blend import MODELS
from score.build import (
    COVERAGE_FLOOR_PCT,
    build_document,
    check_one_hot_identity,
    resolve_models,
)
from score.join import pair_valid_times
from score.split import chronological_split

BASE = pd.Timestamp("2026-08-04T12:00:00Z")
LEADS = (6, 12, 24)
N_TIMES = 120  # 6-hourly over 30 days -> the 80/40 split of SPEC §7's example

MODEL_BIAS = {"HRRR": -1.9, "GFS": 2.4, "NAM": 0.6, "NBM": -0.75}
MODEL_SPREAD = {"HRRR": 1.1, "GFS": 2.7, "NAM": 0.6, "NBM": 1.9}
LEAD_SCALE = {6: 1.0, 12: 1.5, 24: 2.3}


def _times(n: int = N_TIMES):
    return pd.to_datetime([BASE + pd.Timedelta(hours=6 * k) for k in range(n)], utc=True).as_unit(
        "us"
    )


def synthetic_matched(n_times: int = N_TIMES, seed: int = 4090) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    times = _times(n_times)
    obs = 71.0 + 10.0 * np.sin(np.arange(n_times) * np.pi / 2.0) + rng.normal(0.0, 1.3, n_times)
    rows = []
    for lead in LEADS:
        for model in MODELS:
            err = MODEL_BIAS[model] * LEAD_SCALE[lead] + rng.normal(
                0.0, MODEL_SPREAD[model] * LEAD_SCALE[lead], n_times
            )
            for k in range(n_times):
                rows.append(
                    {
                        "model": model,
                        "lead_h": lead,
                        "valid_time": times[k],
                        "temp_f": float(obs[k] + err[k]),
                        "obs_f": float(obs[k]),
                        "offset_min": -8.0,
                    }
                )
    return pd.DataFrame(rows)


def synthetic_stats(matched: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (model, lead), group in matched.groupby(["model", "lead_h"]):
        rows.append(
            {
                "model": model,
                "lead_h": lead,
                "n_forecast": len(group),
                "n_matched": len(group),
                "matched_pct": 100.0,
                "mean_abs_offset_min": float(np.mean(np.abs(group["offset_min"]))),
            }
        )
    return pd.DataFrame(rows)


def synthetic_coverage(overrides: dict[str, float] | None = None) -> dict:
    overrides = overrides or {}
    block = {}
    for model in MODELS:
        key = model.lower()
        pct = overrides.get(model, 100.0)
        block[key] = {
            "coverage_pct": pct,
            "by_lead": {str(lead): {"coverage_pct": pct} for lead in LEADS},
        }
    return {"threshold_pct": COVERAGE_FLOOR_PCT, "models": block}


MATCHED = synthetic_matched()
STATS = synthetic_stats(MATCHED)


def build(coverage: dict | None = None, matched: pd.DataFrame | None = None):
    frame = MATCHED if matched is None else matched
    stats = STATS if matched is None else synthetic_stats(frame)
    return build_document(
        frame,
        stats,
        coverage or synthetic_coverage(),
        generated_at="2026-09-04T04:30:00Z",
    )


# ---------------------------------------------------------------------------- shape


def test_the_full_document_passes_the_contract_unchanged():
    doc, _ = build()
    validate_results(doc)  # build_document already did; asserted again explicitly


def test_meta_is_real_not_synthetic():
    doc, _ = build()
    meta = doc["meta"]
    assert meta["is_synthetic"] is False
    assert isinstance(meta["is_synthetic"], bool)
    assert meta["source"] == "noaa_s3_grib"
    assert meta["site"]["id"] == "KOMA"
    assert meta["site"]["name"] == "Omaha Eppley Airfield"
    assert "SYNTHETIC" not in meta["site"]["name"].upper()
    assert meta["split"] == {"method": "chronological", "train_days": 20, "test_days": 10}
    assert meta["init_runs"] == ["00z", "06z", "12z", "18z"]
    assert meta["window"]["days"] == 30
    assert meta["window"]["start"].endswith("Z") and meta["window"]["end"].endswith("Z")


def test_meta_keys_are_locked_the_elevation_delta_cannot_be_smuggled_in():
    doc, _ = build()
    doc["meta"]["grid_elevation_delta_m"] = 12.3
    with pytest.raises(ContractError, match="the SPEC §7 shape is locked"):
        validate_results(doc)


def test_results_keys_are_strings_and_survive_a_json_round_trip():
    doc, _ = build()
    assert sorted(doc["results"]) == ["12", "24", "6"]
    assert doc["lead_times"] == [6, 12, 24]
    reloaded = json.loads(json.dumps(doc))
    assert sorted(reloaded["results"]) == ["12", "24", "6"]
    validate_results(reloaded)


def test_every_lead_has_286_blends_and_an_eighty_forty_split():
    doc, _ = build()
    for lead in ("6", "12", "24"):
        block = doc["results"][lead]
        assert len(block["blends"]) == 286
        assert [b["rank"] for b in block["blends"]] == list(range(1, 287))
        assert block["n_samples"] == {"train": 80, "test": 40}
        assert block["join_diagnostics"]["matched_pct"] == 100.0
        assert block["join_diagnostics"]["mean_abs_offset_min"] == 8.0


def test_models_are_uppercase_and_in_canonical_order():
    doc, _ = build()
    assert doc["meta"]["models_included"] == ["HRRR", "GFS", "NAM", "NBM"]
    for lead in ("6", "12", "24"):
        assert [m["model"] for m in doc["results"][lead]["models"]] == list(MODELS)


# ----------------------------------------------------- PATH A, not copied from a corner


def test_models_metrics_are_the_test_split_numbers_recomputed_independently_here():
    """D2 + D4: the easiest fatal error in the ticket, checked by re-deriving in the test."""
    doc, _ = build()
    for lead in LEADS:
        paired, _ = pair_valid_times(MATCHED, list(MODELS), lead)
        train, test = chronological_split(paired)
        for entry in doc["results"][str(lead)]["models"]:
            expected = metrics.model_metrics(test, entry["model"])
            assert entry["mae"] == round(expected[0], 4)
            assert entry["rmse"] == round(expected[1], 4)
            assert entry["bias"] == round(expected[2], 4)
            # ... and they are NOT the whole-window numbers.
            whole = metrics.model_metrics(paired, entry["model"])
            assert entry["mae"] != round(whole[0], 4)


def test_models_mae_and_its_corner_still_agree_after_serialisation():
    """D5: one rounding helper, so the contract's 1e-9 corner check survives JSON."""
    doc = json.loads(json.dumps(build()[0]))
    for lead in ("6", "12", "24"):
        block = doc["results"][lead]
        corners = {
            next(m for m in MODELS if b["weights"][m] == 1.0): b
            for b in block["blends"]
            if b["is_pure"]
        }
        for entry in block["models"]:
            assert abs(entry["mae"] - corners[entry["model"]]["mae_out_of_sample"]) < 1e-9


def test_the_runtime_one_hot_guard_raises_on_a_corrupted_models_value():
    corner = {
        "mae_out_of_sample": 3.25,
        "rmse_out_of_sample": 4.10,
        "bias_out_of_sample": -0.75,
    }
    check_one_hot_identity(6, "HRRR", (3.25, 4.10, -0.75), corner)  # agrees: no raise
    for corrupted in ((3.2500001, 4.10, -0.75), (3.25, 4.11, -0.75), (3.25, 4.10, -0.74)):
        with pytest.raises(RuntimeError, match="one-hot identity BROKEN"):
            check_one_hot_identity(6, "HRRR", corrupted, corner)


# ------------------------------------------------------------------ winner / best single


def test_winner_is_the_in_sample_argmin_and_is_not_simply_blends_zero():
    doc, _ = build()
    for lead in ("6", "12", "24"):
        block = doc["results"][lead]
        winner = next(b for b in block["blends"] if b["label"] == block["winner"]["label"])
        assert winner["mae_in_sample"] == min(b["mae_in_sample"] for b in block["blends"])
        assert block["winner"]["mae_out_of_sample"] == winner["mae_out_of_sample"]


def test_best_single_model_is_the_lowest_out_of_sample_corner():
    doc, _ = build()
    for lead in ("6", "12", "24"):
        block = doc["results"][lead]
        corners = {
            next(m for m in MODELS if b["weights"][m] == 1.0): b["mae_out_of_sample"]
            for b in block["blends"]
            if b["is_pure"]
        }
        best = block["best_single_model"]
        assert best["mae_out_of_sample"] == min(corners.values())
        assert corners[best["model"]] == best["mae_out_of_sample"]


def test_improvement_is_the_signed_derived_figure_never_clamped():
    doc, _ = build()
    for lead in ("6", "12", "24"):
        block = doc["results"][lead]
        best = block["best_single_model"]["mae_out_of_sample"]
        got = block["winner"]["mae_out_of_sample"]
        assert abs(
            block["winner"]["improvement_pct_vs_best_single"] - (best - got) / best * 100.0
        ) < 0.05


def _adversarial_matched() -> pd.DataFrame:
    """Train: HRRR and GFS errors cancel, so a 50/50 blend is the in-sample argmin.
    Test: HRRR is far and away the best single model and the blend is dragged down by GFS.
    The honest consequence is a **negative** improvement, which must ship as-is (SPEC §10).
    """
    rng = np.random.default_rng(11)
    times = _times()
    obs = 70.0 + rng.normal(0.0, 0.05, N_TIMES)
    rows = []
    for lead in LEADS:
        for k in range(N_TIMES):
            sign = 1.0 if k % 2 == 0 else -1.0
            if k < 80:  # train
                err = {"HRRR": 3.0 * sign, "GFS": -3.0 * sign, "NAM": 5.0, "NBM": -7.0}
            else:  # test
                err = {"HRRR": 0.5 * sign, "GFS": 4.0, "NAM": 6.0, "NBM": -8.0}
            for model in MODELS:
                jitter = rng.normal(0.0, 0.02)
                rows.append(
                    {
                        "model": model,
                        "lead_h": lead,
                        "valid_time": times[k],
                        "temp_f": float(obs[k] + err[model] + jitter),
                        "obs_f": float(obs[k]),
                        "offset_min": -8.0,
                    }
                )
    return pd.DataFrame(rows)


def test_a_negative_improvement_is_produced_and_accepted_by_the_contract():
    doc, _ = build(matched=_adversarial_matched())
    validate_results(doc)
    for lead in ("6", "12", "24"):
        block = doc["results"][lead]
        assert block["winner"]["improvement_pct_vs_best_single"] < 0.0
        assert block["best_single_model"]["model"] == "HRRR"
        # The fitted winner is NOT the out-of-sample leaderboard row 1 (D12).
        assert block["winner"]["label"] != block["blends"][0]["label"]


# --------------------------------------------------------------------- coverage floor (D9)


def test_all_four_models_are_included_at_full_coverage():
    included, excluded, per_lead = resolve_models(synthetic_coverage())
    assert included == list(MODELS)
    assert excluded == []
    assert per_lead["HRRR"]["6"] == 100.0


def test_one_model_below_the_floor_yields_three_models_and_66_blends():
    doc, _ = build(synthetic_coverage({"NAM": 85.0}))
    validate_results(doc)
    assert doc["meta"]["models_included"] == ["HRRR", "GFS", "NBM"]
    assert [e["model"] for e in doc["meta"]["models_excluded"]] == ["NAM"]
    assert doc["meta"]["models_excluded"][0]["coverage_pct"] == 85.0
    assert "90% floor" in doc["meta"]["models_excluded"][0]["reason"]
    for lead in ("6", "12", "24"):
        assert len(doc["results"][lead]["blends"]) == 66
        assert [m["model"] for m in doc["results"][lead]["models"]] == ["HRRR", "GFS", "NBM"]
        assert sorted(doc["results"][lead]["blends"][0]["weights"]) == ["GFS", "HRRR", "NBM"]


def test_two_models_below_the_floor_yields_two_models_and_11_blends():
    doc, _ = build(synthetic_coverage({"NAM": 85.0, "GFS": 12.5}))
    validate_results(doc)
    assert doc["meta"]["models_included"] == ["HRRR", "NBM"]
    assert sorted(e["model"] for e in doc["meta"]["models_excluded"]) == ["GFS", "NAM"]
    for lead in ("6", "12", "24"):
        assert len(doc["results"][lead]["blends"]) == 11


def test_included_and_excluded_lists_are_always_disjoint():
    doc, _ = build(synthetic_coverage({"NAM": 85.0}))
    included = set(doc["meta"]["models_included"])
    excluded = {e["model"] for e in doc["meta"]["models_excluded"]}
    assert included & excluded == set()


def test_the_floor_boundary_exactly_ninety_passes_and_eighty_nine_ninety_nine_excludes():
    included, excluded, _ = resolve_models(synthetic_coverage({"NAM": 90.0}))
    assert "NAM" in included and excluded == []
    included, excluded, _ = resolve_models(synthetic_coverage({"NAM": 89.99}))
    assert "NAM" not in included
    assert [e["model"] for e in excluded] == ["NAM"]


def test_coverage_is_read_not_recomputed_a_missing_model_raises():
    coverage = synthetic_coverage()
    del coverage["models"]["nbm"]
    with pytest.raises(ValueError, match="no entry for model 'NBM'"):
        resolve_models(coverage)


def test_models_coverage_pct_comes_from_the_per_lead_value():
    coverage = synthetic_coverage()
    coverage["models"]["gfs"]["by_lead"]["24"]["coverage_pct"] = 97.5
    doc, _ = build(coverage)
    gfs_24 = next(m for m in doc["results"]["24"]["models"] if m["model"] == "GFS")
    gfs_6 = next(m for m in doc["results"]["6"]["models"] if m["model"] == "GFS")
    assert gfs_24["coverage_pct"] == 97.5
    assert gfs_6["coverage_pct"] == 100.0


# ------------------------------------------------------------------------------ purity


def test_the_build_tests_read_no_parquet_and_open_no_socket():
    """TR5: the default suite is pure logic. Anything touching data/ is `integration`.

    Scanned by AST, not by substring. A raw text scan trips over this very function's
    own list of forbidden tokens, and the only ways to make that green are to weaken
    the check or to stop naming what it forbids. Walking the tree instead lets the
    check stay strict and stay honest: the names below are inspected as imports, as
    called attributes and as string literals everywhere in the module *except* inside
    this function.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(__file__).read_text("utf-8"))
    self_name = "test_the_build_tests_read_no_parquet_and_open_no_socket"
    this = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == self_name
    )
    skip = range(this.lineno, (this.end_lineno or this.lineno) + 1)

    forbidden_roots = {"socket", "requests", "httpx", "urllib", "http", "boto3", "pyarrow"}
    forbidden_calls = {"read_parquet", "to_parquet", "read_feather", "urlopen", "urlretrieve"}

    for node in ast.walk(tree):
        if getattr(node, "lineno", None) in skip:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden_roots, f"imports {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in forbidden_roots, f"imports from {node.module}"
        elif isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_calls, f"calls .{node.attr}()"
        elif isinstance(node, ast.Name):
            assert node.id not in forbidden_calls, f"calls {node.id}()"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert ".parquet" not in node.value, f"names a parquet file: {node.value!r}"
