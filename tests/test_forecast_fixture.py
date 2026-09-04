"""F3 Stream 3 — the synthetic forecast fixture must be complete, honest and loud.

Two things are being proved here, and they pull in opposite directions.

**It must be indistinguishable from a real payload to the *contract*.** The fixture goes
through the very same `forecast.contract.validate_forecast` the live document does, so
whatever F5 renders from it exercises the real shape — including the two branches F2's
64/64-clean live run never reached: a declared `gaps` entry, and rows beyond the longest
fitted lead.

**It must be unmistakable to a *human*.** FORECAST-SPEC §15: *a fixture that could be
mistaken for a real forecast is the worst possible failure of this page.* So the banner
flag is asserted as a real JSON boolean, the string `"true"` is proved to be rejected, and
the site name is proved to carry its marker.

Nothing here touches the repository's real `data/` directory, opens a socket, or depends on
`data/live/` or `data/results.json` — one test proves that on purpose, by taking all three
away and building the document anyway.
"""

from __future__ import annotations

import copy
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.contract import ContractError
from fetch import grib
from forecast import contract, live, make_fixture

GENERATED_AT = datetime(2026, 9, 4, 17, 4, 12, tzinfo=timezone.utc)
INIT_TIME = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


class HostileFetcherError(Exception):
    """Deliberately NOT a RuntimeError: a caller catching RuntimeError must not mask it."""


@pytest.fixture()
def doc() -> dict:
    return make_fixture.build_fixture_document(
        generated_at=GENERATED_AT, init_time=INIT_TIME
    )


# --------------------------------------------------------------------------- the contract


def test_the_fixture_passes_the_same_validator_as_the_real_payload(doc: dict) -> None:
    contract.validate_forecast(doc)


def test_the_fixture_is_not_secretly_empty(doc: dict) -> None:
    """An empty forecast validates against nothing and renders a blank page (SPEC §10)."""
    assert len(doc["forecast"]) >= 8, f"only {len(doc['forecast'])} rows"
    assert doc["meta"]["step_h"] == 3
    assert doc["meta"]["horizon_h"] == 48


# --------------------------------------------------------------------------- loudness


def test_is_synthetic_is_a_real_json_boolean(doc: dict) -> None:
    flag = doc["meta"]["is_synthetic"]
    assert flag is True
    assert isinstance(flag, bool), f"is_synthetic is {type(flag).__name__}, not bool"


def test_source_and_site_name_announce_the_fixture(doc: dict) -> None:
    assert doc["meta"]["source"] == "synthetic_fixture"
    name = doc["meta"]["site"]["name"]
    assert "SYNTHETIC FIXTURE" in name, f"site name {name!r} hides that this is fabricated"


def test_the_weights_source_does_not_claim_to_be_results_json(doc: dict) -> None:
    """These weights were typed by hand. Borrowing the real artifact's path would lie."""
    path = doc["meta"]["weights_source"]["path"]
    assert path != "data/results.json"
    assert "fabricated" in path.lower(), f"weights_source.path {path!r} does not say it is fake"


def test_the_numbers_are_obviously_fabricated(doc: dict) -> None:
    """Repdigits, and a 33 degF disagreement no real model set produces."""
    row = doc["forecast"][0]
    spread = row["member_spread_f"]
    assert spread > 20.0, (
        f"member spread {spread} degF is small enough to be mistaken for real disagreement"
    )
    maes = {entry["blend_mae"] for entry in doc["skill"]["by_lead"]}
    assert maes <= {5.55, 6.66, 7.77, 8.88, 9.99}, f"skill MAEs are not repdigits: {maes}"


def test_the_string_true_cannot_defeat_the_banner(doc: dict) -> None:
    """§9 rule 9. A fixture whose flag is the *string* "true" must be rejected outright."""
    mutated = copy.deepcopy(doc)
    mutated["meta"]["is_synthetic"] = "true"

    with pytest.raises(ContractError) as excinfo:
        contract.validate_forecast(mutated)

    assert "is_synthetic" in str(excinfo.value)


# --------------------------------------------------------------------------- zero dependencies


def test_it_builds_with_no_cache_no_results_json_and_a_hostile_fetcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unambiguous proof (D17): nothing on disk, nothing on the network is consulted.

    The working directory becomes an empty tree, `data/live/` points somewhere that does not
    exist, `data/results.json` is a *directory* so any read of it raises, every fetcher
    raises a non-`RuntimeError`, and `socket` is booby-trapped. The document still builds.
    The real `data/` files are never touched — only the process's idea of where to look.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "results.json").mkdir(parents=True)  # reading it raises IsADirectory
    monkeypatch.setattr(live, "LIVE_ROOT", tmp_path / "data" / "live-does-not-exist")

    def hostile(*args: object, **kwargs: object) -> object:
        raise HostileFetcherError("no fetch may happen while building a fixture")

    monkeypatch.setattr(grib, "fetch_point", hostile, raising=False)
    monkeypatch.setattr(grib, "decode_point", hostile, raising=False)
    monkeypatch.setattr(socket, "socket", hostile)
    monkeypatch.setattr(socket, "create_connection", hostile)

    built = make_fixture.build_fixture_document(
        generated_at=GENERATED_AT, init_time=INIT_TIME
    )

    contract.validate_forecast(built)
    assert not (tmp_path / "data" / "live-does-not-exist").exists()


def test_the_module_imports_no_weights_no_cache_and_no_network() -> None:
    """A source scan, because an import added later would still pass the test above."""
    source = Path(make_fixture.__file__).read_text(encoding="utf-8")
    code_lines = [
        line for line in source.splitlines() if line.startswith(("import ", "from "))
    ]
    joined = "\n".join(code_lines)
    for banned in ("forecast.weights", "forecast.live", "requests", "urllib", "boto3", "socket"):
        assert banned not in joined, f"make_fixture.py imports {banned}: {joined}"


# --------------------------------------------------------------------------- the two branches


def test_there_is_at_least_one_gap_and_its_models_are_uppercase(doc: dict) -> None:
    """D-F3-G: the live run was 64/64 clean, so this is the only place the gap branch runs."""
    gaps = doc["gaps"]
    assert gaps, "the fixture declares no gap, so F5 cannot render the gap treatment offline"

    included = set(doc["meta"]["models_included"])
    for gap in gaps:
        missing = gap["missing_models"]
        assert missing, f"gap at {gap['lead_h']}h names no missing model"
        for name in missing:
            assert name == name.upper(), f"missing_models carries {name!r}, not UPPERCASE"
        assert set(missing) <= included, f"{missing} is not a subset of {sorted(included)}"


def test_there_is_at_least_one_extrapolated_row(doc: dict) -> None:
    """The other never-exercised branch: a lead beyond the longest fitted lead."""
    fitted = doc["meta"]["weights_source"]["fitted_leads"]
    extrapolated = [row for row in doc["forecast"] if row["is_extrapolated_lead"]]
    assert extrapolated, f"no row beyond max(fitted_leads)={max(fitted)}h"
    for row in extrapolated:
        assert row["lead_h"] > max(fitted)
        assert row["weights_fitted_at_lead_h"] == contract.band_for_lead(row["lead_h"], fitted)


def test_forecast_and_gap_leads_are_disjoint_and_cover_the_grid_exactly(doc: dict) -> None:
    """§9 rule 8, asserted here directly rather than trusted to the validator alone."""
    step_h = doc["meta"]["step_h"]
    horizon_h = doc["meta"]["horizon_h"]
    grid = set(range(step_h, horizon_h + 1, step_h))

    rows = [row["lead_h"] for row in doc["forecast"]]
    gaps = [gap["lead_h"] for gap in doc["gaps"]]

    assert len(set(rows)) == len(rows), f"duplicate forecast lead(s) in {rows}"
    assert len(set(gaps)) == len(gaps), f"duplicate gap lead(s) in {gaps}"
    assert set(rows).isdisjoint(gaps), f"lead(s) {sorted(set(rows) & set(gaps))} are both"
    assert set(rows) | set(gaps) == grid, (
        f"union {sorted(set(rows) | set(gaps))} != grid {sorted(grid)}"
    )


# --------------------------------------------------------------------------- the identities


def test_blend_f_is_the_weighted_sum_of_its_members_on_every_row(doc: dict) -> None:
    """§9 rule 6, NON-NEGOTIABLE. Recomputed here from the row's own numbers."""
    models = doc["meta"]["models_included"]
    for index, row in enumerate(doc["forecast"]):
        expected = sum(row["weights"][m] * row["members"][m] for m in models)
        assert row["blend_f"] == pytest.approx(expected, abs=1e-6), (
            f"forecast[{index}] at {row['lead_h']}h: blend_f {row['blend_f']} != {expected}"
        )


def test_member_spread_is_exactly_max_minus_min(doc: dict) -> None:
    for index, row in enumerate(doc["forecast"]):
        values = list(row["members"].values())
        assert row["member_spread_f"] == pytest.approx(max(values) - min(values), abs=1e-6), (
            f"forecast[{index}]: spread {row['member_spread_f']} is not max - min of {values}"
        )


def test_members_are_stored_rounded_to_four_decimal_places(doc: dict) -> None:
    """D-F3-C: members are the stored values; the blend is computed from them, not vice versa."""
    for row in doc["forecast"]:
        for model, value in row["members"].items():
            assert value == round(value, 4), f"{model} at {row['lead_h']}h stores {value!r}"
            assert value is not None


def test_weights_sit_on_the_tenths_grid_and_sum_to_one(doc: dict) -> None:
    for row in doc["forecast"]:
        weights = row["weights"]
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)
        for model, weight in weights.items():
            assert weight * 10 == pytest.approx(round(weight * 10), abs=1e-8), (
                f"{model} weight {weight} is off the 0.1 grid"
            )


def test_every_row_lead_matches_its_valid_time(doc: dict) -> None:
    init = INIT_TIME
    for entry in list(doc["forecast"]) + list(doc["gaps"]):
        stamp = entry["valid_time"]
        assert stamp.endswith("Z"), stamp
        parsed = datetime.fromisoformat(stamp[:-1] + "+00:00")
        assert parsed == init + timedelta(hours=entry["lead_h"])


# --------------------------------------------------------------------------- skill and staleness


def test_skill_covers_exactly_the_fitted_leads_and_invents_nothing(doc: dict) -> None:
    """§9 rule 10 — no skill entry may be synthesized for a lead nobody fitted."""
    fitted = doc["meta"]["weights_source"]["fitted_leads"]
    measured = [entry["lead_h"] for entry in doc["skill"]["by_lead"]]
    assert sorted(measured) == sorted(fitted)


def test_the_fixture_renders_an_honest_loss_somewhere(doc: dict) -> None:
    """§15: a zero or negative improvement must render. A fixture that always wins hides it."""
    improvements = [entry["improvement_pct"] for entry in doc["skill"]["by_lead"]]
    assert any(value <= 0 for value in improvements), (
        f"every fitted lead shows a win ({improvements}); the honest-loss path is unexercised"
    )


def test_stale_flag_and_reason_agree(doc: dict) -> None:
    """§9 rule 11, both directions."""
    cycle = doc["meta"]["cycle"]
    expected = cycle["cycles_fallen_back"] > 0 or cycle["age_minutes"] > contract.STALE_AGE_MINUTES
    assert cycle["is_stale"] is expected
    assert (cycle["stale_reason"] is not None) is cycle["is_stale"]


def test_a_fallback_moves_to_an_earlier_cycle(doc: dict) -> None:
    cycle = doc["meta"]["cycle"]
    assert cycle["init_time"] <= cycle["target_init_time"]
    assert cycle["fetched_at"] <= doc["meta"]["generated_at"]


# --------------------------------------------------------------------------- writing


def test_write_fixture_round_trips_through_the_loader(tmp_path: Path) -> None:
    target = tmp_path / "forecast.fixture.json"

    written = make_fixture.write_fixture(target, GENERATED_AT, INIT_TIME)
    loaded = contract.load_and_validate_forecast(target)

    assert loaded == written
    assert loaded["meta"]["is_synthetic"] is True
    assert json.loads(target.read_text(encoding="utf-8"))["meta"]["source"] == "synthetic_fixture"


def test_an_invalid_document_is_not_written_and_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "forecast.fixture.json"
    monkeypatch.setattr(make_fixture, "build_fixture_document", lambda **kwargs: {"meta": {}})

    with pytest.raises(ContractError):
        make_fixture.write_fixture(target, GENERATED_AT, INIT_TIME)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == [], f"left behind {list(tmp_path.iterdir())}"


def test_main_writes_a_valid_fixture_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "forecast.fixture.json"

    code = make_fixture.main(["--out", str(target)])

    assert code == 0
    out = capsys.readouterr().out
    assert "is_synthetic=True" in out
    assert "SYNTHETIC FIXTURE" in out
    loaded = contract.load_and_validate_forecast(target)
    assert loaded["meta"]["is_synthetic"] is True


def test_main_refuses_to_write_a_document_that_violates_the_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "forecast.fixture.json"
    monkeypatch.setattr(make_fixture, "build_fixture_document", lambda **kwargs: {"meta": {}})

    code = make_fixture.main(["--out", str(target)])

    assert code == 1
    out = capsys.readouterr().out
    assert "REFUSING TO WRITE" in out
    assert str(target) in out
    assert not target.exists()


def test_the_default_output_is_not_the_served_forecast_json() -> None:
    """§11: the API must never silently serve the fixture. Overwriting the live file would."""
    assert make_fixture.DEFAULT_OUTPUT.name != "forecast.json"


# --------------------------------------------------------------------------- purity


def test_two_builds_with_the_same_arguments_are_identical() -> None:
    first = make_fixture.build_fixture_document(GENERATED_AT, INIT_TIME)
    second = make_fixture.build_fixture_document(GENERATED_AT, INIT_TIME)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_instants_are_injected_not_read_from_a_clock() -> None:
    """A different `init_time` must move every stamp — proof the argument is really used."""
    later = INIT_TIME + timedelta(hours=6)
    shifted = make_fixture.build_fixture_document(GENERATED_AT + timedelta(hours=6), later)

    assert shifted["meta"]["cycle"]["init_time"] == "2026-09-04T18:00:00Z"
    assert shifted["meta"]["cycle"]["run_label"] == "18z"
    assert shifted["forecast"][0]["valid_time"] == "2026-09-04T21:00:00Z"
    contract.validate_forecast(shifted)


def test_naive_datetimes_are_refused() -> None:
    """A naive instant means local time on somebody's laptop. UTC everywhere."""
    naive = datetime(2026, 9, 4, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        make_fixture.build_fixture_document(GENERATED_AT, naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        make_fixture.build_fixture_document(naive, INIT_TIME)


def test_default_init_time_is_the_last_six_hourly_cycle() -> None:
    moment = datetime(2026, 9, 4, 17, 4, 12, tzinfo=timezone.utc)
    assert make_fixture.default_init_time(moment) == datetime(
        2026, 9, 4, 12, tzinfo=timezone.utc
    )
