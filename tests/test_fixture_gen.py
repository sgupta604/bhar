"""Tests for the synthetic fixture generator.

Hermetic: everything is generated into `tmp_path` or built in memory. Nothing here
reads or writes `tests/fixtures/` (T2 owns it) or `data/` (the repo's served copy).
"""

from __future__ import annotations

import json
import math

import pytest

from backend.make_fixture import (
    LEAD_TIMES,
    MODELS,
    blend_label,
    build_document,
    simplex_grid,
    write_fixture,
)

PINNED_STAMP = "2026-09-04T04:00:00Z"


@pytest.fixture(scope="module")
def doc() -> dict:
    return build_document(generated_at=PINNED_STAMP)


def test_simplex_grid_is_the_full_286_point_grid() -> None:
    grid = simplex_grid()
    assert len(grid) == 286 == math.comb(13, 3)
    assert len(set(grid)) == 286
    assert all(abs(sum(w) - 1.0) < 1e-9 for w in grid)


def test_every_lead_carries_the_complete_grid(doc: dict) -> None:
    for lead in LEAD_TIMES:
        assert len(doc["results"][str(lead)]["blends"]) == 286


def test_output_is_byte_identical_across_runs(tmp_path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    write_fixture(first, generated_at=PINNED_STAMP)
    write_fixture(second, generated_at=PINNED_STAMP)
    for name in ("results.json", "results.synthetic.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_both_files_are_written_pretty_printed_with_a_trailing_newline(tmp_path) -> None:
    write_fixture(tmp_path, generated_at=PINNED_STAMP)
    served = (tmp_path / "results.json").read_text(encoding="utf-8")
    insurance = (tmp_path / "results.synthetic.json").read_text(encoding="utf-8")
    assert served == insurance
    assert served.endswith("}\n")
    assert '\n  "meta": {' in served
    assert json.loads(served)["meta"]["generated_at"] == PINNED_STAMP


def test_fixture_is_unmistakably_synthetic(doc: dict) -> None:
    meta = doc["meta"]
    assert meta["is_synthetic"] is True
    assert meta["source"] == "synthetic_fixture"
    assert "SYNTHETIC FIXTURE" in meta["site"]["name"]
    assert meta["site"]["id"] == "KOMA"
    assert meta["site"]["iem_station"] == "OMA"
    assert (meta["site"]["lat"], meta["site"]["lon"]) == (41.3032, -95.8941)


def test_excluded_model_is_not_one_of_the_scored_models(doc: dict) -> None:
    meta = doc["meta"]
    excluded = [entry["model"] for entry in meta["models_excluded"]]
    assert excluded == ["RAP"]
    assert set(excluded).isdisjoint(meta["models_included"])
    assert meta["models_included"] == list(MODELS)


def test_six_hour_pure_maes_are_the_repdigits(doc: dict) -> None:
    models = {entry["model"]: entry["mae"] for entry in doc["results"]["6"]["models"]}
    assert models == {"HRRR": 5.55, "NBM": 6.66, "GFS": 7.77, "NAM": 8.88}


def test_pure_mae_equals_that_models_one_hot_blend(doc: dict) -> None:
    for lead in LEAD_TIMES:
        block = doc["results"][str(lead)]
        corners = {
            next(m for m, w in b["weights"].items() if w == 1.0): b["mae_out_of_sample"]
            for b in block["blends"]
            if b["is_pure"]
        }
        for entry in block["models"]:
            assert entry["mae"] == corners[entry["model"]]


def test_join_diagnostics_and_sample_counts(doc: dict) -> None:
    for lead in LEAD_TIMES:
        block = doc["results"][str(lead)]
        assert block["join_diagnostics"]["matched_pct"] == 88.88
        assert block["join_diagnostics"]["mean_abs_offset_min"] == 8.88
        assert block["n_samples"] == {"train": 88, "test": 44}


def test_improvement_sign_per_lead(doc: dict) -> None:
    improvements = {
        lead: doc["results"][str(lead)]["winner"]["improvement_pct_vs_best_single"]
        for lead in LEAD_TIMES
    }
    assert improvements[6] > 0.05, improvements
    assert abs(improvements[12]) <= 0.05, improvements
    assert improvements[24] < -0.05, improvements


def test_winner_is_the_in_sample_argmin_not_the_leaderboard_leader(doc: dict) -> None:
    for lead in LEAD_TIMES:
        block = doc["results"][str(lead)]
        blends = block["blends"]
        winner = next(b for b in blends if b["label"] == block["winner"]["label"])
        assert winner["mae_in_sample"] == min(b["mae_in_sample"] for b in blends)
        assert block["winner"]["mae_out_of_sample"] == winner["mae_out_of_sample"]
        # D13: a frontend reading blends[0] would show the wrong row.
        assert winner["rank"] != 1


def test_blend_labels_are_unique_and_follow_the_documented_rule(doc: dict) -> None:
    for lead in LEAD_TIMES:
        labels = [b["label"] for b in doc["results"][str(lead)]["blends"]]
        assert len(set(labels)) == len(labels) == 286
    assert blend_label((1.0, 0.0, 0.0, 0.0)) == "HRRR only"
    assert blend_label((0.7, 0.3, 0.0, 0.0)) == "HRRR 70 / GFS 30"
    assert blend_label((0.5, 0.3, 0.0, 0.2)) == "HRRR 50 / GFS 30 / NBM 20"


def test_best_single_model_is_the_lowest_scoring_pure_model(doc: dict) -> None:
    for lead in LEAD_TIMES:
        block = doc["results"][str(lead)]
        best = min(block["models"], key=lambda entry: entry["mae"])
        assert block["best_single_model"]["model"] == best["model"]
        assert block["best_single_model"]["mae_out_of_sample"] == best["mae"]
