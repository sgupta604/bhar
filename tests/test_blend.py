"""The simplex grid, the labels, and **the single most important test in the project**.

``test_one_hot_reproduces_pure_model_metrics`` is SPEC §8's T5 acceptance floor: a
one-hot weight vector must reproduce that pure model's own MAE. It is checked across two
**independent code paths** — ``score.metrics.model_metrics`` (PATH A, which has never
heard of a weight vector) versus ``score.blend.blend_metrics`` (PATH B, a pivot and a
matrix multiply) — over 4 models x 3 leads x 2 splits x 3 metrics.

**It is asserted bit-exactly, with NO tolerance.** ``1.0*x + 0.0*y + 0.0*z + 0.0*w`` is
exact in IEEE-754, so exact equality is the correct assertion. A tolerance here would
hide precisely the bug the test exists to catch — a model column mixed up in the matmul,
which produces confident, plausible, entirely wrong numbers and raises nothing. If this
test ever goes red, **the code is wrong**; do not add a tolerance to make it pass.

The comparison is made **pre-rounding**. Rounding happens once, in ``score/build.py``,
after this identity already holds.

A test that cannot fail is SPEC §10's failure class in miniature, so the negative
controls below prove this one can: a permuted weight vector must *disagree*, and a
permuted design matrix must *raise*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend import make_fixture  # TEST ONLY — score/ never imports the fake-data module
from score import metrics
from score.blend import (
    GRID_STEP_DENOM,
    MODELS,
    blend_label,
    blend_metrics,
    blend_table,
    design_matrix,
    evaluate_design,
    one_hot,
    simplex_grid,
)

BASE = pd.Timestamp("2026-08-04T12:00:00Z")
LEADS = (6, 12, 24)

#: Deliberately different per-model error signatures — different bias SIGNS and
#: different spreads. Symmetric or identical model errors would let a column mix-up pass
#: by coincidence, which would make the whole test worthless.
MODEL_BIAS = {"HRRR": -2.5, "GFS": 1.75, "NAM": 0.4, "NBM": -0.9}
MODEL_SPREAD = {"HRRR": 1.0, "GFS": 2.6, "NAM": 0.55, "NBM": 1.8}
LEAD_SCALE = {6: 1.0, 12: 1.45, 24: 2.2}

N_TIMES = 40
N_TRAIN = 25


def synthetic_joined_frame(n_times: int = N_TIMES, seed: int = 20260904) -> pd.DataFrame:
    """A paired frame with no parquet and no network (SPEC §13, TR5)."""
    rng = np.random.default_rng(seed)
    times = pd.to_datetime(
        [BASE + pd.Timedelta(hours=6 * k) for k in range(n_times)], utc=True
    ).as_unit("us")
    obs = 72.0 + 11.0 * np.sin(np.arange(n_times) * np.pi / 2.0) + rng.normal(0.0, 1.4, n_times)
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
    frame = pd.DataFrame(rows)
    # Shuffled on purpose: neither path may depend on incoming row order.
    return frame.sample(frac=1.0, random_state=7).reset_index(drop=True)


FRAME = synthetic_joined_frame()
SPLIT_BOUNDARY = sorted(FRAME["valid_time"].unique())[N_TRAIN]


def subset(lead: int, split: str) -> pd.DataFrame:
    part = FRAME.loc[FRAME["lead_h"] == lead]
    if split == "train":
        return part.loc[part["valid_time"] < SPLIT_BOUNDARY].copy()
    return part.loc[part["valid_time"] >= SPLIT_BOUNDARY].copy()


# ======================================================================== Task 1.1/1.2
# Grid and label parity with backend.make_fixture, over every vector.


def test_simplex_grid_sizes_are_286_66_and_11():
    assert len(simplex_grid(MODELS)) == 286
    assert len(simplex_grid(MODELS[:3])) == 66
    assert len(simplex_grid(MODELS[:2])) == 11


def test_every_weight_vector_sums_to_one():
    for n in (2, 3, 4):
        for vector in simplex_grid(MODELS[:n]):
            assert abs(sum(vector) - 1.0) < 1e-9


@pytest.mark.parametrize("n", [2, 3, 4])
def test_grid_parity_with_make_fixture_element_for_element_and_in_order(n):
    ours = simplex_grid(MODELS[:n])
    theirs = make_fixture.simplex_grid(n)
    assert len(ours) == len(theirs)
    assert ours == theirs


@pytest.mark.parametrize("n", [2, 3, 4])
def test_label_parity_with_make_fixture_character_for_character(n):
    for vector in simplex_grid(MODELS[:n]):
        assert blend_label(vector, MODELS[:n]) == make_fixture.blend_label(vector)


def test_all_286_labels_are_unique():
    labels = [blend_label(v) for v in simplex_grid(MODELS)]
    assert len(set(labels)) == 286


def test_label_rule_examples():
    assert blend_label((1.0, 0.0, 0.0, 0.0)) == "HRRR only"
    assert blend_label((0.0, 0.0, 0.0, 1.0)) == "NBM only"
    assert blend_label((0.7, 0.3, 0.0, 0.0)) == "HRRR 70 / GFS 30"
    assert blend_label((0.5, 0.3, 0.0, 0.2)) == "HRRR 50 / GFS 30 / NBM 20"


def test_score_package_never_imports_the_fake_data_generator():
    """D6: coupling the real science to the synthetic fixture generator is the thing
    being avoided. ``backend.contract`` (read-only) is the only permitted backend import."""
    import ast
    from pathlib import Path

    for path in (Path(__file__).resolve().parent.parent / "score").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        backend_imports = sorted(m for m in modules if m.startswith("backend"))
        assert backend_imports in ([], ["backend.contract"]), f"{path.name}: {backend_imports}"


# ============================================================================ Task 3.2
# THE NON-NEGOTIABLE TEST.


def test_one_hot_reproduces_pure_model_metrics():
    """SPEC §8 acceptance floor. Two independent paths, bit-exact, ZERO tolerance.

    4 models x 3 leads x 2 splits x 3 metrics = 72 exact equalities.
    """
    checked = 0
    for lead in LEADS:
        for split in ("train", "test"):
            frame = subset(lead, split)
            for model in MODELS:
                a = metrics.model_metrics(frame, model)  # PATH A
                b = blend_metrics(frame, one_hot(model))  # PATH B
                for name, left, right in zip(("mae", "rmse", "bias"), a, b):
                    assert abs(left - right) == 0.0, (
                        f"one-hot identity broken at lead {lead}h, model {model}, "
                        f"split {split}, metric {name}: PATH A {left!r} vs PATH B {right!r}. "
                        "The code is wrong — do NOT add a tolerance."
                    )
                    checked += 1
    assert checked == 4 * 3 * 2 * 3 == 72


def test_the_synthetic_models_actually_have_different_error_signatures():
    """Guards the guard: identical models would make the test above pass while broken."""
    frame = subset(6, "test")
    maes = {m: metrics.model_metrics(frame, m)[0] for m in MODELS}
    biases = {m: metrics.model_metrics(frame, m)[2] for m in MODELS}
    assert len(set(round(v, 6) for v in maes.values())) == 4
    assert min(biases.values()) < 0.0 < max(biases.values())  # both bias signs present


# ============================================================================ Task 3.3
# Negative controls — proof that the test above can fail.


def test_negative_control_a_permuted_weight_vector_must_disagree():
    frame = subset(12, "test")
    disagreements = 0
    for model in MODELS:
        a = metrics.model_metrics(frame, model)
        for other in MODELS:
            if other == model:
                continue
            b = blend_metrics(frame, one_hot(other))
            assert a[0] != b[0], (
                f"{model}'s MAE equals the one-hot corner of {other}; the identity test "
                "cannot distinguish the models and therefore proves nothing"
            )
            disagreements += 1
    assert disagreements == 12


def test_negative_control_reversing_the_model_order_breaks_the_identity():
    """The exact mutant the guard exists for: design columns and weight columns disagree."""
    frame = subset(6, "test")
    reversed_models = tuple(reversed(MODELS))
    for model in MODELS[:2]:
        a = metrics.model_metrics(frame, model)
        mutant = blend_metrics(frame, one_hot(model, MODELS), models=reversed_models)
        assert abs(a[0] - mutant[0]) > 1e-9, (
            "reversing the model order did not change the answer, so the identity test "
            "would not catch a column-ordering bug"
        )


def test_negative_control_a_permuted_design_matrix_raises_in_production_code():
    frame = subset(6, "test")
    P, obs = design_matrix(frame, MODELS)
    permuted = P[list(reversed(MODELS))]
    W = np.asarray([one_hot("HRRR")], dtype=np.float64)
    with pytest.raises(RuntimeError, match="canonical model order"):
        evaluate_design(permuted, obs, W, MODELS)


def test_weights_that_do_not_sum_to_one_raise():
    frame = subset(6, "test")
    with pytest.raises(ValueError, match="not 1.0 within 1e-9"):
        blend_metrics(frame, (0.5, 0.3, 0.1, 0.0))


# ============================================================================ Task 3.4
# Model-column ordering.


def test_the_pivot_columns_are_the_canonical_model_order():
    P, _ = design_matrix(subset(24, "train"), MODELS)
    assert list(P.columns) == list(MODELS)


def test_the_pivot_row_order_matches_the_order_path_a_reduces_in():
    frame = subset(24, "train")
    P, obs = design_matrix(frame, MODELS)
    expected = sorted(frame["valid_time"].unique())
    assert list(P.index) == expected
    hrrr = frame.loc[frame["model"] == "HRRR"].sort_values("valid_time")
    assert np.array_equal(P["HRRR"].to_numpy(), hrrr["temp_f"].to_numpy())
    assert np.array_equal(obs, hrrr["obs_f"].to_numpy())


def test_weight_matrix_columns_use_the_same_order_as_the_design_matrix():
    frame = subset(6, "test")
    P, obs = design_matrix(frame, MODELS)
    grid = simplex_grid(MODELS)
    W = np.asarray(grid, dtype=np.float64)
    assert W.shape == (286, len(MODELS))
    # The i-th weight column belongs to MODELS[i]: a one-hot in column i must reproduce
    # the i-th design column's own metrics.
    for i, model in enumerate(MODELS):
        vector = np.zeros(len(MODELS))
        vector[i] = 1.0
        row = evaluate_design(P, obs, vector.reshape(1, -1), MODELS)[0]
        assert row[0] == metrics.model_metrics(frame, model)[0]


def test_a_blend_reread_by_key_not_by_position_reproduces_the_same_mae():
    """The JSON carries weights as a dict; the frontend reads them by name.

    A *mixed* blend re-evaluated on its own is compared within 1e-9 rather than bit
    exactly: BLAS uses a different kernel for a (n x 4) @ (4 x 1) product than for
    (n x 4) @ (4 x 286), so the four nonzero terms can be summed in a different order
    and land one ulp apart. That freedom does not exist for a one-hot vector — the three
    zero products and the single `1.0 * x` are exact in IEEE-754 whatever the order —
    which is exactly why the SPEC §8 identity above can demand, and gets, zero tolerance.
    """
    train, test = subset(12, "train"), subset(12, "test")
    rows = blend_table(train, test, MODELS)
    for row in (rows[0], rows[5], rows[len(rows) // 2], rows[-1]):
        by_key = tuple(row["weights"][m] for m in MODELS)  # re-read by NAME
        mae, rmse, bias = blend_metrics(test, by_key)
        assert abs(mae - row["mae_out_of_sample"]) < 1e-9
        assert abs(rmse - row["rmse_out_of_sample"]) < 1e-9
        assert abs(bias - row["bias_out_of_sample"]) < 1e-9


def test_the_full_286_table_corners_are_bit_exact_against_path_a():
    """The production path: build.py checks PATH A against the corner rows of the FULL
    286-vector table, not against a one-row re-evaluation. Bit exactness must hold there
    too, or the runtime guard in score/build.py would need a tolerance it must not have.
    """
    for lead in LEADS:
        train, test = subset(lead, "train"), subset(lead, "test")
        rows = blend_table(train, test, MODELS)
        corners = {r["label"]: r for r in rows if r["is_pure"]}
        for model in MODELS:
            a_mae, a_rmse, a_bias = metrics.model_metrics(test, model)
            corner = corners[f"{model} only"]
            assert abs(a_mae - corner["mae_out_of_sample"]) == 0.0
            assert abs(a_rmse - corner["rmse_out_of_sample"]) == 0.0
            assert abs(a_bias - corner["bias_out_of_sample"]) == 0.0
            a_train = metrics.model_metrics(train, model)
            assert abs(a_train[0] - corner["mae_in_sample"]) == 0.0


# =========================================================== Task 3.1 — the blend table


def test_blend_table_emits_every_vector_sorted_with_contiguous_ranks():
    train, test = subset(6, "train"), subset(6, "test")
    rows = blend_table(train, test, MODELS)
    assert len(rows) == 286
    maes = [r["mae_out_of_sample"] for r in rows]
    assert maes == sorted(maes)
    assert [r["grid_index"] for r in rows] != list(range(286))  # genuinely re-sorted
    assert sorted(r["grid_index"] for r in rows) == list(range(286))


def test_every_one_hot_corner_is_present_whatever_its_rank():
    train, test = subset(24, "train"), subset(24, "test")
    rows = blend_table(train, test, MODELS)
    corners = {r["label"]: r for r in rows if r["is_pure"]}
    assert sorted(corners) == sorted(f"{m} only" for m in MODELS)
    for model in MODELS:
        corner = corners[f"{model} only"]
        assert corner["weights"][model] == 1.0
        assert sum(corner["weights"].values()) == 1.0


def test_the_blend_sort_tie_break_is_the_grid_index():
    """D7: equal out-of-sample MAE must order by grid_index, so reruns are identical."""
    train, test = subset(12, "train"), subset(12, "test")
    rows = blend_table(train, test, MODELS)
    for previous, current in zip(rows, rows[1:]):
        if previous["mae_out_of_sample"] == current["mae_out_of_sample"]:
            assert previous["grid_index"] < current["grid_index"]


def test_is_pure_is_true_for_exactly_the_four_corners():
    train, test = subset(6, "train"), subset(6, "test")
    rows = blend_table(train, test, MODELS)
    assert sum(1 for r in rows if r["is_pure"]) == 4
    for row in rows:
        tenths = [int(round(w * GRID_STEP_DENOM)) for w in row["weights"].values()]
        assert row["is_pure"] == (max(tenths) == GRID_STEP_DENOM)


def test_a_three_model_table_has_66_blends_and_a_two_model_table_has_11():
    train, test = subset(6, "train"), subset(6, "test")
    for n, expected in ((3, 66), (2, 11)):
        models = MODELS[:n]
        keep = train["model"].isin(models)
        rows = blend_table(train.loc[keep], test.loc[test["model"].isin(models)], models)
        assert len(rows) == expected
        assert sorted(rows[0]["weights"]) == sorted(models)


def test_design_matrix_raises_when_a_valid_time_is_missing_a_model():
    """An unpaired frame would silently score models on different samples (FR4)."""
    frame = subset(6, "test")
    thinned = frame.drop(index=frame.index[frame["model"] == "NAM"][:1])
    with pytest.raises(ValueError, match="pivot has holes"):
        design_matrix(thinned, MODELS)
