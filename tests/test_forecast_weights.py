"""Executable proof that `forecast.weights` reads the FITTED weights, not the leaderboard.

The load path is asserted against the **real** `data/results.json` — a committed,
read-only input. Every negative case is built from a `deepcopy` of that document and
written to `tmp_path`; nothing here writes to `data/`.

The centrepiece is `test_the_fitted_winner_is_never_blends_index_zero`. `blends[]` is
sorted by *out-of-sample* MAE, so `blends[0]` is the leaderboard leader while the fitted
winner is the blend that won on the *training* split. They differ at all three leads in
the real file, and a switch to `blends[0]` would publish a look-ahead-biased vector that
still renders a perfectly plausible page. That test exists to make the swap loud.

Hermetic: no network (proved by `test_the_load_path_opens_no_socket`), no server, and no
wall clock — `now` is injected at every call.
"""

from __future__ import annotations

import copy
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.contract import ContractError
from forecast import weights as fw
from forecast.weights import (
    FittedWeights,
    PRODUCED_BY,
    SKILL_BASIS,
    SKILL_NOTE,
    load_fitted_weights,
    select_winner_blend,
    skill_entry,
    weights_for_lead,
)

#: `data/results.json`'s own `meta.generated_at`. Every frozen instant below is an offset
#: from this, so the age assertions cannot drift with the calendar.
GENERATED_AT = datetime(2026, 9, 4, 12, 53, 1, tzinfo=timezone.utc)

#: A `now` comfortably inside the fresh window, used wherever the age is not under test.
NOW = GENERATED_AT + timedelta(days=3)

MODELS = ("HRRR", "GFS", "NAM", "NBM")
FITTED_LEADS = (6, 12, 24)

#: The three fitted vectors, transcribed from the real backtest. These are the numbers the
#: page ships; if the file is refitted they change, and this test is meant to notice.
EXPECTED_VECTORS: dict[int, dict[str, float]] = {
    6: {"HRRR": 0.5, "GFS": 0.0, "NAM": 0.1, "NBM": 0.4},
    12: {"HRRR": 0.6, "GFS": 0.0, "NAM": 0.1, "NBM": 0.3},
    24: {"HRRR": 0.5, "GFS": 0.0, "NAM": 0.1, "NBM": 0.4},
}

#: What `winner.label` says at each lead — the fitted choice.
EXPECTED_WINNER_LABELS = {
    6: "HRRR 50 / NAM 10 / NBM 40",
    12: "HRRR 60 / NAM 10 / NBM 30",
    24: "HRRR 50 / NAM 10 / NBM 40",
}

#: What `blends[0].label` says at each lead — the out-of-sample leader, and **the vector
#: that would have shipped silently** had anyone indexed instead of matching by label.
INDEX_ZERO_LABELS = {
    6: "HRRR 70 / NBM 30",
    12: "HRRR 30 / NAM 40 / NBM 30",
    24: "HRRR 40 / NAM 30 / NBM 30",
}

#: The label-matched blend's `mae_in_sample` per lead. `winner` has no such field, so a
#: regression that read it off `winner` would raise — and one that read it off `blends[0]`
#: would produce 1.8369 / 1.9083 / 1.9585 instead of these.
EXPECTED_IN_SAMPLE = {6: 1.7793, 12: 1.973, 24: 2.0141}


# ------------------------------------------------------------------------------ fixtures


@pytest.fixture(scope="session")
def real_results_path(REPO_ROOT: Path) -> Path:
    """The committed backtest output. READ-ONLY: no test writes to this path."""
    path = REPO_ROOT / "data" / "results.json"
    if not path.exists():
        pytest.skip(f"{path} is absent; it is produced by {PRODUCED_BY}")
    return path


@pytest.fixture(scope="session")
def real_doc(real_results_path: Path) -> dict:
    """The parsed real document, read once. Callers `deepcopy` before mutating."""
    return json.loads(real_results_path.read_text(encoding="utf-8"))


@pytest.fixture()
def fitted(real_results_path: Path) -> FittedWeights:
    return load_fitted_weights(real_results_path, NOW)


def write_doc(doc: dict, tmp_path: Path, name: str = "results.json") -> Path:
    """Write a mutated copy to `tmp_path`. Never `data/results.json`."""
    target = tmp_path / name
    target.write_text(json.dumps(doc), encoding="utf-8")
    return target


def synthetic_fitted(vectors: dict[int, dict[str, float]]) -> FittedWeights:
    """A `FittedWeights` with arbitrary fitted leads, for banding tests that must not be
    able to accidentally agree with the real 6/12/24 grid."""
    leads = tuple(sorted(vectors))
    return FittedWeights(
        vectors={lead: dict(vector) for lead, vector in vectors.items()},
        fitted_leads=leads,
        models_included=MODELS,
        site={"id": "KOMA"},
        weights_source={"fitted_leads": list(leads)},
        skill={"by_lead": []},
    )


# ------------------------------------------------------------- Task 2.1: the real vectors


def test_fitted_vectors_are_the_three_real_backtest_vectors(fitted: FittedWeights) -> None:
    """The acceptance criterion for Task 2.1, against the real file."""
    assert fitted.fitted_leads == FITTED_LEADS
    assert fitted.vectors == EXPECTED_VECTORS, (
        f"the fitted vectors read out of data/results.json are {fitted.vectors}, not the "
        f"backtest's {EXPECTED_VECTORS}"
    )
    for lead, vector in fitted.vectors.items():
        assert abs(sum(vector.values()) - 1.0) < 1e-9, f"{lead} h vector does not sum to 1"


def test_models_site_and_source_come_from_meta(fitted: FittedWeights, real_doc: dict) -> None:
    meta = real_doc["meta"]
    assert fitted.models_included == tuple(meta["models_included"])
    assert all(name == name.upper() for name in fitted.models_included)
    assert fitted.site == meta["site"]


def test_weights_source_carries_exactly_the_six_spec_keys(
    fitted: FittedWeights, real_doc: dict, real_results_path: Path
) -> None:
    """FORECAST-SPEC §7.1: the staleness block is a fixed six-key shape."""
    source = fitted.weights_source
    assert set(source) == {
        "path",
        "generated_at",
        "weights_age_days",
        "window",
        "split",
        "fitted_leads",
    }
    assert source["path"] == str(real_results_path)
    assert source["generated_at"] == real_doc["meta"]["generated_at"]
    assert source["window"] == real_doc["meta"]["window"]
    assert source["split"] == real_doc["meta"]["split"]
    assert source["fitted_leads"] == list(FITTED_LEADS)


def test_returned_values_are_copies_not_aliases_into_the_document(
    real_results_path: Path,
) -> None:
    """A caller that mutates what it got back must not reach into the loaded document."""
    first = load_fitted_weights(real_results_path, NOW)
    first.site["name"] = "TAMPERED"
    first.vectors[6]["HRRR"] = 99.0
    first.weights_source["window"]["days"] = 999
    first.skill["by_lead"][0]["blend_mae"] = -1.0

    second = load_fitted_weights(real_results_path, NOW)
    assert second.site["name"] == "Omaha Eppley Airfield"
    assert second.vectors[6] == EXPECTED_VECTORS[6]
    assert second.weights_source["window"]["days"] == 30
    assert second.skill["by_lead"][0]["blend_mae"] > 0


# --------------------------------------------------- Task 2.3: the look-ahead-bias guard


def test_the_fitted_winner_is_never_blends_index_zero(
    fitted: FittedWeights, real_doc: dict
) -> None:
    """THE regression test. It must FAIL the moment anyone switches to `blends[0]`.

    `blends[]` is ranked by out-of-sample MAE. The fitted winner sits at rank 5 / 23 / 5,
    and index 0 is a different weight vector at every lead. Taking it would select weights
    using the test set — look-ahead bias — and the resulting document would look fine.
    """
    for lead in FITTED_LEADS:
        lead_result = real_doc["results"][str(lead)]
        winner_label = lead_result["winner"]["label"]
        index_zero = lead_result["blends"][0]

        assert winner_label == EXPECTED_WINNER_LABELS[lead], (
            f"{lead} h: winner.label is {winner_label!r}, not the recorded "
            f"{EXPECTED_WINNER_LABELS[lead]!r} — data/results.json was refitted and the "
            f"constants in this test are stale"
        )
        assert index_zero["label"] == INDEX_ZERO_LABELS[lead], (
            f"{lead} h: blends[0].label is {index_zero['label']!r}, not the recorded "
            f"{INDEX_ZERO_LABELS[lead]!r} — this test has gone blind and no longer proves "
            f"that index 0 differs from the fitted winner"
        )
        assert index_zero["label"] != winner_label, (
            f"{lead} h: blends[0] and the fitted winner now share a label, so this test can "
            f"no longer detect an index-0 regression"
        )
        assert fitted.vectors[lead] != index_zero["weights"], (
            f"{lead} h: forecast/weights.py returned the OUT-OF-SAMPLE leader "
            f"{index_zero['weights']} ({INDEX_ZERO_LABELS[lead]!r}) instead of the fitted "
            f"winner {EXPECTED_VECTORS[lead]} ({EXPECTED_WINNER_LABELS[lead]!r}). blends[] is "
            f"sorted by out-of-sample error; index 0 is chosen with knowledge of the test set. "
            f"Had this shipped, the page would have published "
            f"{INDEX_ZERO_LABELS[6]!r} / {INDEX_ZERO_LABELS[12]!r} / {INDEX_ZERO_LABELS[24]!r} "
            f"at 6 / 12 / 24 h — a look-ahead-biased blend, silently."
        )
        assert fitted.vectors[lead] == EXPECTED_VECTORS[lead]


def test_the_fitted_winner_is_not_even_near_the_top_of_the_leaderboard(
    real_doc: dict,
) -> None:
    """Rank 5 / 23 / 5: an off-by-one on the index would not have saved anyone either."""
    ranks = {}
    for lead in FITTED_LEADS:
        lead_result = real_doc["results"][str(lead)]
        label = lead_result["winner"]["label"]
        ranks[lead] = next(
            blend["rank"] for blend in lead_result["blends"] if blend["label"] == label
        )
    assert ranks == {6: 5, 12: 23, 24: 5}, (
        f"the fitted winner's leaderboard ranks are {ranks}; if any of these becomes 1 the "
        f"look-ahead test above is no longer able to distinguish the two selections"
    )


def test_winner_label_matching_zero_blends_raises(real_doc: dict) -> None:
    """No match is a hard failure, never a fall back to index 0."""
    lead_result = copy.deepcopy(real_doc["results"]["6"])
    lead_result["winner"]["label"] = "NOT A BLEND IN THIS FILE"

    with pytest.raises(ContractError) as excinfo:
        select_winner_blend(6, lead_result)

    text = str(excinfo.value)
    assert "NOT A BLEND IN THIS FILE" in text, text
    assert "matches 0 entries" in text, text
    assert '"6"' in text, f"the raise must name the lead: {text}"


def test_winner_label_matching_two_blends_raises(real_doc: dict) -> None:
    """An ambiguous label is a hard failure too — picking either one would be a guess."""
    lead_result = copy.deepcopy(real_doc["results"]["12"])
    label = lead_result["winner"]["label"]
    other = next(blend for blend in lead_result["blends"] if blend["label"] != label)
    other["label"] = label

    with pytest.raises(ContractError) as excinfo:
        select_winner_blend(12, lead_result)

    text = str(excinfo.value)
    assert "matches 2 entries" in text, text
    assert '"12"' in text, f"the raise must name the lead: {text}"
    assert label in text, f"the raise must name the label: {text}"


def test_a_tampered_winner_label_fails_the_whole_load_and_returns_nothing(
    real_doc: dict, tmp_path: Path
) -> None:
    """End to end: the document is rejected and no `FittedWeights` escapes."""
    doc = copy.deepcopy(real_doc)
    doc["results"]["6"]["winner"]["label"] = "HRRR 99 / NBM 1"
    path = write_doc(doc, tmp_path)

    returned = None
    with pytest.raises(ContractError):
        returned = load_fitted_weights(path, NOW)
    assert returned is None, "a vector escaped from a document with an unmatchable winner label"


def test_the_module_exposes_no_default_or_equal_weight_vector() -> None:
    """§16 R3: there is no fallback vector anywhere in this module to fall back *to*."""
    offenders = []
    for name, value in vars(fw).items():
        if isinstance(value, dict) and value and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value.values()
        ):
            offenders.append(name)
    assert offenders == [], (
        f"module-level numeric vector(s) {offenders} look like a default weight vector; F3 "
        f"substitutes nothing when data/results.json is unusable (FORECAST-SPEC §16 R3)"
    )


# --------------------------------------------------------- Task 2.2: the §7 banding table


@pytest.mark.parametrize(
    ("lead_h", "expected_band"),
    [(3, 6), (9, 6), (12, 12), (18, 12), (21, 24), (24, 24), (27, 24), (48, 24)],
)
def test_weights_for_lead_follows_the_spec_7_banding_table(
    fitted: FittedWeights, lead_h: int, expected_band: int
) -> None:
    vector, band, extrapolated = weights_for_lead(lead_h, fitted)

    assert band == expected_band, f"{lead_h} h banded onto {band} h, expected {expected_band} h"
    assert vector == EXPECTED_VECTORS[expected_band], (
        f"{lead_h} h must use the {expected_band} h fitted vector unchanged"
    )
    assert extrapolated is (lead_h > 24)


def test_the_returned_vector_is_the_fitted_one_unchanged(fitted: FittedWeights) -> None:
    """Nothing rescales a vector over a subset of models, and nothing mutates the source."""
    vector, _, _ = weights_for_lead(30, fitted)
    assert vector == EXPECTED_VECTORS[24]

    vector["HRRR"] = 0.0
    again, _, _ = weights_for_lead(30, fitted)
    assert again == EXPECTED_VECTORS[24], "the caller's mutation reached the loaded vectors"


def test_a_tie_bands_to_the_shorter_lead() -> None:
    """9 h is exactly 3 h from both 6 and 12; §7 says the shorter lead wins."""
    two_leads = synthetic_fitted({6: EXPECTED_VECTORS[6], 12: EXPECTED_VECTORS[12]})

    _, band, _ = weights_for_lead(9, two_leads)

    assert band == 6, f"a 9 h lead with fitted_leads [6, 12] must band onto 6 h, got {band}"


def test_is_extrapolated_boundary_is_derived_not_hardcoded(fitted: FittedWeights) -> None:
    """24 is not a magic number: refit at [6, 12] and the boundary moves to 12."""
    assert weights_for_lead(24, fitted)[2] is False
    assert weights_for_lead(27, fitted)[2] is True

    two_leads = synthetic_fitted({6: EXPECTED_VECTORS[6], 12: EXPECTED_VECTORS[12]})
    assert weights_for_lead(12, two_leads)[2] is False
    assert weights_for_lead(18, two_leads)[2] is True, (
        "with fitted_leads [6, 12] an 18 h lead is beyond every fitted lead; a `True` only at "
        "leads above 24 would mean 24 is hardcoded somewhere"
    )
    assert weights_for_lead(24, two_leads)[2] is True


def test_weights_for_lead_raises_rather_than_inventing_a_missing_band() -> None:
    """A band with no loaded vector is a raise, not a synthesized vector."""
    broken = synthetic_fitted({6: EXPECTED_VECTORS[6], 24: EXPECTED_VECTORS[24]})
    object.__setattr__(broken, "vectors", {6: EXPECTED_VECTORS[6]})

    with pytest.raises(ContractError) as excinfo:
        weights_for_lead(24, broken)

    assert "weights are never rescaled over a subset of models" in str(excinfo.value)


# ------------------------------------------------------ Task 2.1: no fallback, ever (R3)


def test_a_missing_results_file_names_the_path_and_what_produces_it(tmp_path: Path) -> None:
    absent = tmp_path / "data" / "results.json"

    returned = None
    with pytest.raises(ContractError) as excinfo:
        returned = load_fitted_weights(absent, NOW)

    text = str(excinfo.value)
    assert returned is None, "a vector escaped even though the input file does not exist"
    assert str(absent) in text, f"the raise must name the missing path: {text}"
    assert PRODUCED_BY in text, f"the raise must name what produces it: {text}"
    assert "fallback" in text.lower(), f"the raise must say there is no fallback: {text}"


def test_malformed_json_raises_and_returns_nothing(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text('{"meta": {"site":', encoding="utf-8")

    returned = None
    with pytest.raises(ContractError) as excinfo:
        returned = load_fitted_weights(path, NOW)

    assert returned is None, "a vector escaped from a file that is not valid JSON"
    assert "not valid JSON" in str(excinfo.value)


def test_a_contract_failing_document_raises_and_returns_nothing(
    real_doc: dict, tmp_path: Path
) -> None:
    """The `results.json` contract is not re-implemented here — it is propagated."""
    doc = copy.deepcopy(real_doc)
    doc["results"]["6"]["blends"][3]["rank"] = 99
    path = write_doc(doc, tmp_path)

    returned = None
    with pytest.raises(ContractError) as excinfo:
        returned = load_fitted_weights(path, NOW)

    assert returned is None, "a vector escaped from a contract-violating document"
    assert "rank" in str(excinfo.value), (
        f"the contract's own reason must propagate, not be swallowed: {excinfo.value}"
    )


# ------------------------------------------------------------- Task 2.1: weight staleness


@pytest.mark.parametrize("elapsed_days", [0, 44, 45, 46])
def test_weights_age_days_is_whole_days_from_generated_at(
    real_results_path: Path, elapsed_days: int
) -> None:
    """FORECAST-SPEC §7.1. 45 is the threshold the page warns above, so it is pinned here."""
    now = GENERATED_AT + timedelta(days=elapsed_days)

    fitted = load_fitted_weights(real_results_path, now)

    assert fitted.weights_source["weights_age_days"] == elapsed_days
    assert fitted.weights_source["generated_at"] == "2026-09-04T12:53:01Z"


def test_weights_age_days_floors_rather_than_rounds(real_results_path: Path) -> None:
    now = GENERATED_AT + timedelta(days=45, hours=23, minutes=59)

    fitted = load_fitted_weights(real_results_path, now)

    assert fitted.weights_source["weights_age_days"] == 45


def test_a_now_before_generated_at_raises(real_results_path: Path) -> None:
    """A negative age means the clock or the file is wrong. It is never clamped to zero."""
    returned = None
    with pytest.raises(ContractError) as excinfo:
        returned = load_fitted_weights(real_results_path, GENERATED_AT - timedelta(seconds=1))

    assert returned is None
    assert "negative weight age" in str(excinfo.value).lower()


def test_a_naive_now_raises(real_results_path: Path) -> None:
    """UTC everywhere: a naive instant would make the age depend on the reader's zone."""
    with pytest.raises(ContractError) as excinfo:
        load_fitted_weights(real_results_path, datetime(2026, 10, 1, 0, 0, 0))

    assert "naive" in str(excinfo.value).lower()


# ------------------------------------------------------------------- Task 2.1: the skill block


def test_skill_block_shape_and_verbatim_note(fitted: FittedWeights, real_doc: dict) -> None:
    skill = fitted.skill
    assert set(skill) == {"basis", "window", "note", "by_lead"}
    assert skill["basis"] == SKILL_BASIS == "historical_out_of_sample"
    assert skill["window"] == real_doc["meta"]["window"]
    assert skill["note"] == (
        "Measured over the 30-day backtest window. "
        "History, not a prediction about this forecast."
    ), f"skill.note must be the FORECAST-SPEC §9 sentence verbatim, got {skill['note']!r}"
    assert skill["note"] == SKILL_NOTE


def test_skill_by_lead_covers_exactly_the_fitted_leads(fitted: FittedWeights) -> None:
    by_lead = fitted.skill["by_lead"]
    assert [entry["lead_h"] for entry in by_lead] == list(FITTED_LEADS), (
        "skill.by_lead must cover exactly the fitted leads; no entry may be synthesized for a "
        "lead the backtest never measured"
    )
    for entry in by_lead:
        assert set(entry) == {
            "lead_h",
            "blend_mae",
            "blend_mae_in_sample",
            "best_single_model",
            "best_single_mae",
            "improvement_pct",
            "n_test",
            "independent_days_approx",
        }


def test_blend_mae_in_sample_comes_from_the_label_matched_blend(
    fitted: FittedWeights, real_doc: dict
) -> None:
    """`winner` has no `mae_in_sample`; reading it off `blends[0]` gives different numbers."""
    by_lead = {entry["lead_h"]: entry for entry in fitted.skill["by_lead"]}
    for lead in FITTED_LEADS:
        assert "mae_in_sample" not in real_doc["results"][str(lead)]["winner"], (
            f"{lead} h: winner now carries mae_in_sample, so this test no longer proves the "
            f"value is taken from the label-matched blend"
        )
        index_zero_in_sample = real_doc["results"][str(lead)]["blends"][0]["mae_in_sample"]
        got = by_lead[lead]["blend_mae_in_sample"]
        assert got == EXPECTED_IN_SAMPLE[lead], (
            f"{lead} h: blend_mae_in_sample is {got}, expected {EXPECTED_IN_SAMPLE[lead]} from "
            f"the label-matched blend (blends[0] would have given {index_zero_in_sample})"
        )


def test_skill_by_lead_values_track_the_document(fitted: FittedWeights, real_doc: dict) -> None:
    by_lead = {entry["lead_h"]: entry for entry in fitted.skill["by_lead"]}
    for lead in FITTED_LEADS:
        lead_result = real_doc["results"][str(lead)]
        entry = by_lead[lead]
        assert entry["blend_mae"] == lead_result["winner"]["mae_out_of_sample"]
        assert entry["best_single_model"] == lead_result["best_single_model"]["model"]
        assert entry["best_single_mae"] == lead_result["best_single_model"]["mae_out_of_sample"]
        assert entry["improvement_pct"] == lead_result["winner"]["improvement_pct_vs_best_single"]
        assert entry["n_test"] == lead_result["n_samples"]["test"]


def test_independent_days_approx_is_window_days_not_the_sample_count(
    fitted: FittedWeights, real_doc: dict
) -> None:
    """README C2: ~30 independent-ish days, not 120. A named derivation, not a coincidence."""
    window_days = real_doc["meta"]["window"]["days"]
    for entry in fitted.skill["by_lead"]:
        assert entry["independent_days_approx"] == window_days == 30
        assert entry["independent_days_approx"] != entry["n_test"] * 3, (
            "independent_days_approx must be meta.window.days, never a count derived from the "
            "joined samples — four init runs a day do not give four independent days"
        )


# ------------------------------------------- Task 2.3: improvement_pct passes through honestly


def _doc_with_winner_out_of_sample_mae(doc: dict, lead: int, new_mae: float) -> dict:
    """Restate the winner blend's out-of-sample MAE, keeping the document self-consistent.

    The blends array stays sorted by `mae_out_of_sample` with 1-based ranks, and
    `improvement_pct_vs_best_single` is recomputed from the definition, so the result still
    passes `backend.contract`. Only the *sign* of the improvement changes — which is the
    thing under test.
    """
    doc = copy.deepcopy(doc)
    lead_result = doc["results"][str(lead)]
    label = lead_result["winner"]["label"]
    for blend in lead_result["blends"]:
        if blend["label"] == label:
            blend["mae_out_of_sample"] = new_mae
    lead_result["blends"].sort(key=lambda blend: blend["mae_out_of_sample"])
    for position, blend in enumerate(lead_result["blends"]):
        blend["rank"] = position + 1
    best_mae = lead_result["best_single_model"]["mae_out_of_sample"]
    lead_result["winner"]["mae_out_of_sample"] = new_mae
    lead_result["winner"]["improvement_pct_vs_best_single"] = round(
        (best_mae - new_mae) / best_mae * 100.0, 4
    )
    return doc


def test_a_zero_improvement_passes_through_unchanged(real_doc: dict, tmp_path: Path) -> None:
    """SPEC §10: the page reports what the data says. A tie is not rounded into a win."""
    best_mae = real_doc["results"]["6"]["best_single_model"]["mae_out_of_sample"]
    doc = _doc_with_winner_out_of_sample_mae(real_doc, 6, best_mae)
    assert doc["results"]["6"]["winner"]["improvement_pct_vs_best_single"] == 0.0

    fitted = load_fitted_weights(write_doc(doc, tmp_path), NOW)

    entry = next(item for item in fitted.skill["by_lead"] if item["lead_h"] == 6)
    assert entry["improvement_pct"] == 0.0
    assert entry["blend_mae"] == best_mae


def test_a_negative_improvement_passes_through_unchanged(real_doc: dict, tmp_path: Path) -> None:
    """The blend losing to the best single model is a legitimate, publishable result."""
    doc = _doc_with_winner_out_of_sample_mae(real_doc, 24, 3.0)
    recorded = doc["results"]["24"]["winner"]["improvement_pct_vs_best_single"]
    assert recorded < 0, "the fixture must actually encode a loss for this test to mean anything"

    fitted = load_fitted_weights(write_doc(doc, tmp_path), NOW)

    entry = next(item for item in fitted.skill["by_lead"] if item["lead_h"] == 24)
    assert entry["improvement_pct"] == recorded < 0, (
        f"a negative improvement must reach the payload unchanged, got {entry['improvement_pct']}"
    )
    assert fitted.vectors[24] == EXPECTED_VECTORS[24], (
        "a losing blend does not change which vector was fitted"
    )


def test_skill_entry_passes_a_negative_improvement_through_directly(real_doc: dict) -> None:
    """The same guarantee at the unit level, with no arithmetic to keep consistent."""
    lead_result = copy.deepcopy(real_doc["results"]["12"])
    lead_result["winner"]["improvement_pct_vs_best_single"] = -4.25

    entry = skill_entry(12, lead_result, 30)

    assert entry["improvement_pct"] == -4.25
    assert entry["blend_mae_in_sample"] == EXPECTED_IN_SAMPLE[12]


# --------------------------------------------------------------------------- hermeticity


def test_the_load_path_opens_no_socket(
    real_results_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC §13: the weights come off disk. A socket here would be a live-network test."""

    def forbidden(*args, **kwargs):
        raise AssertionError("forecast/weights.py opened a socket; it must read only the file")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    fitted = load_fitted_weights(real_results_path, NOW)

    assert fitted.vectors == EXPECTED_VECTORS
