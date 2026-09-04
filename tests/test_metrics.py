"""PATH A metric tests — every expected value is a literal, hand-computed here.

If the expected numbers were produced by the code under test, the test would only prove
that the code agrees with itself. The four errors below are chosen so MAE, RMSE and bias
are all different from each other and the bias does not cancel.

Worked by hand:

    forecast  70  72  68  75
    observed  69  70  71  71
    error     +1  +2  -3  +4          (forecast - observation)

    mae  = (1 + 2 + 3 + 4) / 4          = 2.5
    rmse = sqrt((1 + 4 + 9 + 16) / 4)   = sqrt(7.5)  = 2.7386127875258306
    bias = (1 + 2 - 3 + 4) / 4          = 1.0
"""

from __future__ import annotations

import pandas as pd
import pytest

from score.metrics import bias, mae, model_metrics, rmse

PRED = [70.0, 72.0, 68.0, 75.0]
OBS = [69.0, 70.0, 71.0, 71.0]

EXPECTED_MAE = 2.5
EXPECTED_RMSE = 2.7386127875258306  # sqrt(7.5)
EXPECTED_BIAS = 1.0


def test_mae_is_the_hand_computed_value():
    assert mae(PRED, OBS) == EXPECTED_MAE


def test_rmse_is_the_hand_computed_value():
    assert abs(rmse(PRED, OBS) - EXPECTED_RMSE) < 1e-12


def test_bias_is_the_hand_computed_value():
    assert bias(PRED, OBS) == EXPECTED_BIAS


def test_bias_is_positive_for_a_uniformly_warm_forecast():
    """Sign convention is displayed on the page: warm forecast => POSITIVE bias."""
    obs = [50.0, 51.0, 52.0]
    warm = [53.0, 54.0, 55.0]
    cold = [47.0, 48.0, 49.0]
    assert bias(warm, obs) == 3.0
    assert bias(cold, obs) == -3.0


def test_rmse_is_never_below_mae():
    assert rmse(PRED, OBS) >= mae(PRED, OBS)


def test_rmse_equals_mae_exactly_when_every_absolute_error_is_equal():
    obs = [10.0, 20.0, 30.0, 40.0]
    pred = [12.0, 18.0, 32.0, 38.0]  # errors +2, -2, +2, -2
    assert mae(pred, obs) == 2.0
    assert rmse(pred, obs) == 2.0
    assert bias(pred, obs) == 0.0


def test_empty_input_raises_because_an_empty_sample_scores_perfectly():
    with pytest.raises(ValueError, match="empty"):
        mae([], [])
    with pytest.raises(ValueError, match="empty"):
        rmse([], [])
    with pytest.raises(ValueError, match="empty"):
        bias([], [])


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError, match="different lengths"):
        mae([1.0, 2.0], [1.0])


def test_non_finite_values_raise_because_observations_are_never_filled():
    with pytest.raises(ValueError, match="non-finite"):
        mae([1.0, float("nan")], [1.0, 2.0])


def _frame() -> pd.DataFrame:
    times = pd.to_datetime(
        ["2026-08-04T18:00Z", "2026-08-04T06:00Z", "2026-08-04T12:00Z", "2026-08-04T00:00Z"],
        utc=True,
    ).as_unit("us")
    # Deliberately unsorted, and interleaved with a second model, so the ordering and
    # filtering behaviour of model_metrics is what is under test.
    rows = []
    for time, pred, obs in zip(times, [75.0, 72.0, 68.0, 70.0], [71.0, 70.0, 71.0, 69.0]):
        rows.append({"model": "HRRR", "valid_time": time, "temp_f": pred, "obs_f": obs})
        rows.append({"model": "GFS", "valid_time": time, "temp_f": 100.0, "obs_f": obs})
    return pd.DataFrame(rows)


def test_model_metrics_selects_one_model_and_matches_the_hand_computed_values():
    got = model_metrics(_frame(), "HRRR")
    assert got[0] == EXPECTED_MAE
    assert abs(got[1] - EXPECTED_RMSE) < 1e-12
    assert got[2] == EXPECTED_BIAS


def test_model_metrics_raises_for_a_model_with_no_rows():
    with pytest.raises(ValueError, match="no rows for model"):
        model_metrics(_frame(), "NAM")


def test_model_metrics_raises_on_duplicate_valid_times():
    frame = pd.concat([_frame(), _frame().head(1)], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate valid_time"):
        model_metrics(frame, "HRRR")


def test_metrics_module_has_no_knowledge_of_blending():
    """PATH A's independence is the whole value of the SPEC §8 one-hot test.

    Checked on the parsed AST, not on the raw text: the module *docstring* is allowed to
    explain the relationship, but no executable line may import ``score.blend`` or touch
    a weight vector. Two paths that share code are one path wearing two hats.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "score" / "metrics.py"
    tree = ast.parse(source.read_text("utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [m for m in imported if "blend" in m], imported

    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    identifiers |= {
        arg.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for arg in node.args.args
    }
    offenders = sorted(n for n in identifiers if "blend" in n.lower() or "weight" in n.lower())
    assert offenders == [], f"score/metrics.py must not know about blending: {offenders}"
