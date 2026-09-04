"""Executable proof that `backend.contract.validate_results` locks the SPEC §7 shape.

Every negative case asserts on the *message text*, not merely that something raised —
a validator that rejects everything for the wrong reason is worse than no validator.

Hermetic: no network, no server, no reads or writes under `tests/fixtures/` (T2 owns
that directory). The document under test is built in memory by `backend.make_fixture`.
"""

from __future__ import annotations

import copy

import pytest

from backend.contract import GRID_MESSAGE, ContractError, load_and_validate, validate_results
from backend.make_fixture import build_document, write_fixture

PINNED_STAMP = "2026-09-04T04:00:00Z"


@pytest.fixture(scope="module")
def valid_doc() -> dict:
    return build_document(generated_at=PINNED_STAMP)


@pytest.fixture()
def doc(valid_doc: dict) -> dict:
    return copy.deepcopy(valid_doc)


def _message(doc: dict) -> str:
    with pytest.raises(ContractError) as excinfo:
        validate_results(doc)
    return str(excinfo.value)


# --------------------------------------------------------------------------- happy path


def test_generated_fixture_passes(valid_doc: dict) -> None:
    assert validate_results(copy.deepcopy(valid_doc)) is None


def test_load_and_validate_round_trips(tmp_path) -> None:
    write_fixture(tmp_path, generated_at=PINNED_STAMP)
    loaded = load_and_validate(tmp_path / "results.json")
    assert loaded["meta"]["source"] == "synthetic_fixture"


def test_load_and_validate_names_a_missing_file(tmp_path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(ContractError) as excinfo:
        load_and_validate(missing)
    assert "nope.json" in str(excinfo.value)


# --------------------------------------------------------------------------- one case per rule


def test_results_key_must_be_a_string_not_an_int(doc: dict) -> None:
    doc["results"][6] = doc["results"].pop("6")
    message = _message(doc)
    assert message.startswith("results:")
    assert "must be a string" in message


def test_truncated_blend_grid_is_rejected_with_the_slider_warning(doc: dict) -> None:
    doc["results"]["6"]["blends"] = doc["results"]["6"]["blends"][:285]
    message = _message(doc)
    assert message.startswith('results["6"].blends:')
    assert "285" in message
    assert GRID_MESSAGE in message


def test_blends_must_be_sorted_by_out_of_sample_mae(doc: dict) -> None:
    blends = doc["results"]["6"]["blends"]
    blends[0]["mae_out_of_sample"] = blends[-1]["mae_out_of_sample"] + 1.0
    message = _message(doc)
    assert message.startswith('results["6"].blends[1].mae_out_of_sample:')
    assert "sorted by mae_out_of_sample ascending" in message


def test_weights_must_sum_to_one(doc: dict) -> None:
    blends = doc["results"]["6"]["blends"]
    index, model = next(
        (i, m)
        for i, b in enumerate(blends)
        for m, w in b["weights"].items()
        if round(w * 10) == 1
    )
    blends[index]["weights"][model] = 0.0
    message = _message(doc)
    assert message.startswith(f'results["6"].blends[{index}].weights:')
    assert "must sum to 1.0" in message


def test_every_one_hot_corner_must_be_present(doc: dict) -> None:
    blends = doc["results"]["6"]["blends"]
    nam_corner = next(i for i, b in enumerate(blends) if b["weights"]["NAM"] == 1.0)
    blends[nam_corner]["weights"] = {"HRRR": 1.0, "GFS": 0.0, "NAM": 0.0, "NBM": 0.0}
    message = _message(doc)
    assert message.startswith('results["6"].blends:')
    assert "one-hot corner(s) for ['NAM'] are missing" in message


def test_is_synthetic_must_be_a_real_boolean(doc: dict) -> None:
    doc["meta"]["is_synthetic"] = "true"
    message = _message(doc)
    assert message.startswith("meta.is_synthetic:")
    assert "must be a JSON boolean" in message


def test_excluded_models_must_be_disjoint_from_included(doc: dict) -> None:
    doc["meta"]["models_excluded"].append(
        {"model": "NBM", "coverage_pct": 71.2, "reason": "below 90% coverage floor"}
    )
    message = _message(doc)
    assert message.startswith("meta.models_excluded:")
    assert "disjoint" in message
    assert "'NBM'" in message


def test_winner_label_must_identify_exactly_one_blend(doc: dict) -> None:
    doc["results"]["12"]["winner"]["label"] = "HRRR 99 / GFS 1"
    message = _message(doc)
    assert message.startswith('results["12"].winner.label:')
    assert "matches 0 blends" in message


def test_winner_must_be_the_in_sample_argmin(doc: dict) -> None:
    lead = doc["results"]["6"]
    blends = lead["blends"]
    other = next(b for b in blends if b["label"] != lead["winner"]["label"])
    lead["winner"]["label"] = other["label"]
    lead["winner"]["mae_out_of_sample"] = other["mae_out_of_sample"]
    best = lead["best_single_model"]["mae_out_of_sample"]
    lead["winner"]["improvement_pct_vs_best_single"] = round(
        (best - other["mae_out_of_sample"]) / best * 100.0, 2
    )
    message = _message(doc)
    assert message.startswith('results["6"].winner.label:')
    assert "in-sample minimum" in message


def test_improvement_must_match_the_signed_formula(doc: dict) -> None:
    doc["results"]["6"]["winner"]["improvement_pct_vs_best_single"] = 42.0
    message = _message(doc)
    assert message.startswith('results["6"].winner.improvement_pct_vs_best_single:')
    assert "42.0" in message


def test_best_single_model_must_match_its_own_corner(doc: dict) -> None:
    doc["results"]["6"]["best_single_model"]["mae_out_of_sample"] = 1.23
    message = _message(doc)
    assert message.startswith('results["6"].best_single_model.mae_out_of_sample:')


def test_lead_times_and_results_keys_must_agree(doc: dict) -> None:
    doc["lead_times"] = [6, 12, 24, 48]
    message = _message(doc)
    assert message.startswith("results:")
    assert "48" in message


# --------------------------------------------------------------------------- SPEC §10


def test_negative_improvement_is_accepted_as_generated(valid_doc: dict) -> None:
    """The 24 h lead genuinely loses to the best single model. That must validate."""
    improvement = valid_doc["results"]["24"]["winner"]["improvement_pct_vs_best_single"]
    assert improvement < -0.05
    assert validate_results(copy.deepcopy(valid_doc)) is None


def test_validator_never_requires_a_positive_result(doc: dict) -> None:
    """SPEC §10 in executable form: force a badly losing winner; it must still validate.

    The blend the training split picks is made the *worst* out-of-sample blend on the
    grid. `improvement_pct_vs_best_single` goes sharply negative. A validator that
    demanded a win would reject this — and the demo would then only ever be able to
    report good news, which is the failure §10 exists to prevent.
    """
    lead = doc["results"]["6"]
    blends = lead["blends"]
    for blend in blends:
        blend["mae_in_sample"] = 9.0
    worst = blends[-1]
    worst["mae_in_sample"] = 0.01
    best = lead["best_single_model"]["mae_out_of_sample"]
    lead["winner"] = {
        "label": worst["label"],
        "mae_out_of_sample": worst["mae_out_of_sample"],
        "improvement_pct_vs_best_single": round(
            (best - worst["mae_out_of_sample"]) / best * 100.0, 2
        ),
    }
    assert lead["winner"]["improvement_pct_vs_best_single"] < -20.0
    assert validate_results(doc) is None
