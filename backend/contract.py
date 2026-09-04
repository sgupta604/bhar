"""Executable lock on the SPEC §7 ``results.json`` contract.

This module is the single place that decides whether a results document is
servable.  ``backend/main.py`` calls it on every request, ``backend/make_fixture.py``
calls it before writing, and T5's real scoring run must satisfy exactly the same
checks.  The point is that a *silently wrong* document (a truncated blend grid, a
``"6"``/``6`` key mixup, a winner that is not the fitted choice) fails loudly here
rather than rendering a confident, fake chart at 16:00.

Design rules:

* Pure — no I/O beyond ``load_and_validate``, no dependencies outside the stdlib.
* Every failure raises :class:`ContractError` with a message that names the
  offending JSON path, e.g. ``results["6"].blends[12].weights``.
* **No bare ``assert``** — assertions vanish under ``python -O`` and this file is
  the only thing standing between the demo and a fabricated number.

Deliberately *not* checked: the sign of ``improvement_pct_vs_best_single``.
SPEC §10 requires the page to report what the data says; a zero or negative
improvement is a legitimate, expected result and the validator must never
demand a win.
"""

from __future__ import annotations

import json
from math import comb
from pathlib import Path

__all__ = ["ContractError", "validate_results", "load_and_validate"]

#: Weight grid step used by the blend search (SPEC §5, D5). Ten tenths per unit.
GRID_STEP_DENOM = 10

#: Absolute tolerance for float identities (weight sums, one-hot lookups).
FLOAT_TOL = 1e-9

#: Tolerance in percentage points for the derived improvement figure.
IMPROVEMENT_TOL_PP = 0.05

#: Verbatim message fragment required by the plan (Task 2.1) — the truncated-grid trap.
GRID_MESSAGE = (
    "blends must be the complete 0.1 grid; a truncated array silently breaks "
    "the weight slider (FR8/D5)."
)

_META_KEYS = {
    "site",
    "variable",
    "units",
    "window",
    "init_runs",
    "source",
    "generated_at",
    "is_synthetic",
    "models_included",
    "models_excluded",
    "split",
}
_SITE_KEYS = {"id", "iem_station", "name", "lat", "lon", "station_elev_m"}
_WINDOW_KEYS = {"start", "end", "days"}
_SPLIT_KEYS = {"method", "train_days", "test_days"}
_EXCLUDED_KEYS = {"model", "coverage_pct", "reason"}
_LEAD_KEYS = {"n_samples", "join_diagnostics", "models", "blends", "best_single_model", "winner"}
_MODEL_KEYS = {"model", "mae", "rmse", "bias", "coverage_pct"}
_BLEND_KEYS = {
    "rank",
    "weights",
    "label",
    "is_pure",
    "mae_in_sample",
    "mae_out_of_sample",
    "rmse_out_of_sample",
    "bias_out_of_sample",
}
_BEST_SINGLE_KEYS = {"model", "mae_out_of_sample"}
_WINNER_KEYS = {"label", "mae_out_of_sample", "improvement_pct_vs_best_single"}


class ContractError(ValueError):
    """Raised when a document violates the SPEC §7 contract.

    The message always begins with the JSON path of the offending value.
    """


def _fail(path: str, message: str) -> None:
    raise ContractError(f"{path}: {message}")


def _mapping(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        _fail(path, f"expected an object, got {type(value).__name__}")
    return value  # type: ignore[return-value]


def _exact_keys(value: object, path: str, expected: set[str]) -> dict:
    obj = _mapping(value, path)
    got = set(obj)
    missing = sorted(k for k in expected if k not in got)
    if missing:
        _fail(path, f"missing required key(s) {missing}")
    extra = sorted(k for k in got if k not in expected)
    if extra:
        _fail(path, f"unexpected key(s) {extra}; the SPEC §7 shape is locked")
    return obj


def _sequence(value: object, path: str) -> list:
    if not isinstance(value, list):
        _fail(path, f"expected an array, got {type(value).__name__}")
    return value  # type: ignore[return-value]


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, f"expected a number, got {type(value).__name__}")
    return float(value)  # type: ignore[arg-type]


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, f"expected an integer, got {type(value).__name__}")
    return value  # type: ignore[return-value]


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        _fail(path, f"expected a string, got {type(value).__name__}")
    if not value.strip():
        _fail(path, "must be a non-empty string")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(
            path,
            f"must be a JSON boolean (true/false), got {type(value).__name__} {value!r}; "
            'the string "true" is not a boolean and would defeat the synthetic banner (§10)',
        )
    return value  # type: ignore[return-value]


def _utc_stamp(value: object, path: str) -> str:
    text = _text(value, path)
    if not text.endswith("Z"):
        _fail(path, f"must be an ISO8601 UTC timestamp ending in 'Z', got {text!r}")
    return text


# --------------------------------------------------------------------------- meta


def _validate_meta(meta_value: object) -> tuple[list[str], bool]:
    meta = _exact_keys(meta_value, "meta", _META_KEYS)

    site = _exact_keys(meta["site"], "meta.site", _SITE_KEYS)
    _text(site["id"], "meta.site.id")
    _text(site["iem_station"], "meta.site.iem_station")
    _text(site["name"], "meta.site.name")
    lat = _number(site["lat"], "meta.site.lat")
    lon = _number(site["lon"], "meta.site.lon")
    _number(site["station_elev_m"], "meta.site.station_elev_m")
    if not -90.0 <= lat <= 90.0:
        _fail("meta.site.lat", f"latitude out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        _fail("meta.site.lon", f"longitude out of range: {lon}")

    _text(meta["variable"], "meta.variable")
    _text(meta["units"], "meta.units")

    window = _exact_keys(meta["window"], "meta.window", _WINDOW_KEYS)
    _utc_stamp(window["start"], "meta.window.start")
    _utc_stamp(window["end"], "meta.window.end")
    days = _integer(window["days"], "meta.window.days")
    if days <= 0:
        _fail("meta.window.days", f"must be a positive integer, got {days}")

    init_runs = _sequence(meta["init_runs"], "meta.init_runs")
    if not init_runs:
        _fail("meta.init_runs", "must list at least one init run")
    for i, run in enumerate(init_runs):
        _text(run, f"meta.init_runs[{i}]")

    _text(meta["source"], "meta.source")
    _utc_stamp(meta["generated_at"], "meta.generated_at")
    is_synthetic = _boolean(meta["is_synthetic"], "meta.is_synthetic")

    included = _sequence(meta["models_included"], "meta.models_included")
    if not included:
        _fail("meta.models_included", "must list at least one model")
    for i, name in enumerate(included):
        _text(name, f"meta.models_included[{i}]")
    if len(set(included)) != len(included):
        _fail("meta.models_included", f"model names must be unique, got {included}")

    excluded = _sequence(meta["models_excluded"], "meta.models_excluded")
    excluded_names: list[str] = []
    for i, entry in enumerate(excluded):
        path = f"meta.models_excluded[{i}]"
        item = _exact_keys(entry, path, _EXCLUDED_KEYS)
        excluded_names.append(_text(item["model"], f"{path}.model"))
        _number(item["coverage_pct"], f"{path}.coverage_pct")
        _text(item["reason"], f"{path}.reason")
    overlap = sorted(set(excluded_names) & set(included))
    if overlap:
        _fail(
            "meta.models_excluded",
            f"model name(s) {overlap} also appear in meta.models_included; the two lists "
            "must be disjoint (D14) — an excluded model cannot also be scored",
        )

    split = _exact_keys(meta["split"], "meta.split", _SPLIT_KEYS)
    _text(split["method"], "meta.split.method")
    for key in ("train_days", "test_days"):
        value = _integer(split[key], f"meta.split.{key}")
        if value <= 0:
            _fail(f"meta.split.{key}", f"must be a positive integer, got {value}")

    return list(included), is_synthetic


# --------------------------------------------------------------------------- blends


def _validate_blends(blends_value: object, included: list[str], lead_path: str) -> list[dict]:
    path = f"{lead_path}.blends"
    blends = _sequence(blends_value, path)

    n = len(included)
    expected = comb(GRID_STEP_DENOM + n - 1, n - 1)
    if len(blends) != expected:
        _fail(
            path,
            f"expected {expected} blends for {n} models at step "
            f"{1 / GRID_STEP_DENOM:.1f}, got {len(blends)}; {GRID_MESSAGE}",
        )

    included_set = set(included)
    seen_vectors: dict[tuple[int, ...], int] = {}
    duplicates: list[tuple[int, int, dict]] = []
    corners: dict[str, int] = {}

    for i, entry in enumerate(blends):
        bpath = f"{path}[{i}]"
        blend = _exact_keys(entry, bpath, _BLEND_KEYS)

        rank = _integer(blend["rank"], f"{bpath}.rank")
        if rank != i + 1:
            _fail(f"{bpath}.rank", f"must be its 1-based position in the sorted array ({i + 1})")

        weights = _mapping(blend["weights"], f"{bpath}.weights")
        if set(weights) != included_set:
            _fail(
                f"{bpath}.weights",
                f"keys must be exactly meta.models_included {sorted(included_set)}, "
                f"got {sorted(weights)}",
            )
        total = 0.0
        tenths: list[int] = []
        for model in included:
            wpath = f"{bpath}.weights.{model}"
            w = _number(weights[model], wpath)
            if w < -FLOAT_TOL or w > 1.0 + FLOAT_TOL:
                _fail(wpath, f"weight must lie in [0, 1], got {w}")
            scaled = w * GRID_STEP_DENOM
            nearest = round(scaled)
            if abs(scaled - nearest) > FLOAT_TOL * GRID_STEP_DENOM:
                _fail(wpath, f"weight must be a multiple of 0.1, got {w}")
            tenths.append(int(nearest))
            total += w
        if abs(total - 1.0) > FLOAT_TOL:
            _fail(f"{bpath}.weights", f"weights must sum to 1.0 within 1e-9, got {total!r}")

        _text(blend["label"], f"{bpath}.label")
        is_pure = _boolean(blend["is_pure"], f"{bpath}.is_pure")
        pure_models = [m for m, t in zip(included, tenths) if t == GRID_STEP_DENOM]
        if bool(pure_models) != is_pure:
            _fail(
                f"{bpath}.is_pure",
                f"is {is_pure} but the weight vector {dict(zip(included, tenths))} "
                f"{'is' if pure_models else 'is not'} a one-hot corner",
            )
        if pure_models:
            corners[pure_models[0]] = i

        for key in (
            "mae_in_sample",
            "mae_out_of_sample",
            "rmse_out_of_sample",
            "bias_out_of_sample",
        ):
            _number(blend[key], f"{bpath}.{key}")

        vector = tuple(tenths)
        if vector in seen_vectors:
            # Reported after the one-hot corner check below: a missing corner is the more
            # fundamental structural fault and is what a duplicated vector usually means.
            duplicates.append((i, seen_vectors[vector], dict(zip(included, tenths))))
        else:
            seen_vectors[vector] = i

    for i in range(1, len(blends)):
        prev = float(blends[i - 1]["mae_out_of_sample"])
        cur = float(blends[i]["mae_out_of_sample"])
        if cur < prev - FLOAT_TOL:
            _fail(
                f"{path}[{i}].mae_out_of_sample",
                f"blends must be sorted by mae_out_of_sample ascending, but {cur} follows {prev} "
                f"at {path}[{i - 1}].mae_out_of_sample",
            )

    missing_corners = [m for m in included if m not in corners]
    if missing_corners:
        _fail(
            path,
            f"one-hot corner(s) for {missing_corners} are missing; every pure model must appear "
            "in blends regardless of rank (SPEC §7)",
        )

    if duplicates:
        i, first, vector = duplicates[0]
        _fail(
            f"{path}[{i}].weights",
            f"duplicate weight vector {vector}; also at {path}[{first}].weights — "
            "every point of the grid must appear exactly once",
        )

    return [dict(b) for b in blends]


# --------------------------------------------------------------------------- per lead


def _validate_lead(lead_value: object, included: list[str], key: str) -> None:
    lead_path = f'results["{key}"]'
    lead = _exact_keys(lead_value, lead_path, _LEAD_KEYS)

    n_samples = _exact_keys(lead["n_samples"], f"{lead_path}.n_samples", {"train", "test"})
    for part in ("train", "test"):
        value = _integer(n_samples[part], f"{lead_path}.n_samples.{part}")
        if value <= 0:
            _fail(f"{lead_path}.n_samples.{part}", f"must be a positive integer, got {value}")

    join = _exact_keys(
        lead["join_diagnostics"],
        f"{lead_path}.join_diagnostics",
        {"matched_pct", "mean_abs_offset_min"},
    )
    matched = _number(join["matched_pct"], f"{lead_path}.join_diagnostics.matched_pct")
    if not 0.0 <= matched <= 100.0:
        _fail(f"{lead_path}.join_diagnostics.matched_pct", f"must be a percentage, got {matched}")
    _number(join["mean_abs_offset_min"], f"{lead_path}.join_diagnostics.mean_abs_offset_min")

    models = _sequence(lead["models"], f"{lead_path}.models")
    names: list[str] = []
    for i, entry in enumerate(models):
        mpath = f"{lead_path}.models[{i}]"
        item = _exact_keys(entry, mpath, _MODEL_KEYS)
        names.append(_text(item["model"], f"{mpath}.model"))
        for key_ in ("mae", "rmse", "bias", "coverage_pct"):
            _number(item[key_], f"{mpath}.{key_}")
    if names != included:
        _fail(
            f"{lead_path}.models",
            f"must hold exactly one entry per meta.models_included, in that order; "
            f"expected {included}, got {names}",
        )

    blends = _validate_blends(lead["blends"], included, lead_path)

    corner_mae = {}
    for blend in blends:
        weights = blend["weights"]
        pure = [m for m in included if round(float(weights[m]) * GRID_STEP_DENOM) == GRID_STEP_DENOM]
        if pure:
            corner_mae[pure[0]] = float(blend["mae_out_of_sample"])

    # models[].mae must agree with that model's own one-hot blend, or the leaderboard
    # and the slider disagree about the same number.
    for i, entry in enumerate(models):
        model = entry["model"]
        stated = float(entry["mae"])
        if abs(stated - corner_mae[model]) > FLOAT_TOL:
            _fail(
                f"{lead_path}.models[{i}].mae",
                f"is {stated} but {model}'s one-hot blend reports "
                f"mae_out_of_sample {corner_mae[model]}",
            )

    best_path = f"{lead_path}.best_single_model"
    best = _exact_keys(lead["best_single_model"], best_path, _BEST_SINGLE_KEYS)
    best_model = _text(best["model"], f"{best_path}.model")
    if best_model not in included:
        _fail(f"{best_path}.model", f"{best_model!r} is not in meta.models_included {included}")
    best_mae = _number(best["mae_out_of_sample"], f"{best_path}.mae_out_of_sample")
    if abs(best_mae - corner_mae[best_model]) > FLOAT_TOL:
        _fail(
            f"{best_path}.mae_out_of_sample",
            f"is {best_mae} but {best_model}'s one-hot blend reports {corner_mae[best_model]}",
        )
    lowest = min(corner_mae.values())
    if best_mae > lowest + FLOAT_TOL:
        cheaper = sorted(m for m, v in corner_mae.items() if v < best_mae - FLOAT_TOL)
        _fail(
            f"{best_path}.model",
            f"{best_model!r} at {best_mae} is not the best single model; {cheaper} score lower "
            f"out of sample (best is {lowest})",
        )

    winner_path = f"{lead_path}.winner"
    winner = _exact_keys(lead["winner"], winner_path, _WINNER_KEYS)
    winner_label = _text(winner["label"], f"{winner_path}.label")
    matches = [b for b in blends if b["label"] == winner_label]
    if len(matches) != 1:
        _fail(
            f"{winner_path}.label",
            f"{winner_label!r} matches {len(matches)} blends; a winner label must identify "
            f"exactly one blend so the UI can find its row without using index 0 (D13)",
        )
    winner_blend = matches[0]

    winner_mae = _number(winner["mae_out_of_sample"], f"{winner_path}.mae_out_of_sample")
    if abs(winner_mae - float(winner_blend["mae_out_of_sample"])) > FLOAT_TOL:
        _fail(
            f"{winner_path}.mae_out_of_sample",
            f"is {winner_mae} but blend {winner_label!r} reports "
            f"{winner_blend['mae_out_of_sample']}",
        )

    best_in_sample = min(float(b["mae_in_sample"]) for b in blends)
    if float(winner_blend["mae_in_sample"]) > best_in_sample + FLOAT_TOL:
        _fail(
            f"{winner_path}.label",
            f"{winner_label!r} has mae_in_sample {winner_blend['mae_in_sample']} but the "
            f"in-sample minimum is {best_in_sample}; the winner is the blend chosen on the "
            "training split, not the out-of-sample leader (D13)",
        )

    improvement = _number(
        winner["improvement_pct_vs_best_single"],
        f"{winner_path}.improvement_pct_vs_best_single",
    )
    if best_mae == 0:
        _fail(f"{best_path}.mae_out_of_sample", "must be non-zero to derive an improvement")
    expected_improvement = (best_mae - winner_mae) / best_mae * 100.0
    # NOTE: no sign constraint. Zero and negative improvements are legal and expected
    # results (SPEC §10) — the validator checks arithmetic, never the verdict.
    if abs(improvement - expected_improvement) > IMPROVEMENT_TOL_PP:
        _fail(
            f"{winner_path}.improvement_pct_vs_best_single",
            f"is {improvement} but (best_single {best_mae} - winner {winner_mae}) / "
            f"{best_mae} * 100 = {expected_improvement:.4f}",
        )


# --------------------------------------------------------------------------- entry points


def validate_results(doc: dict) -> None:
    """Validate a parsed ``results.json`` document against the SPEC §7 contract.

    Returns ``None`` on success; raises :class:`ContractError` naming the offending
    path on the first violation.
    """
    top = _exact_keys(doc, "$", {"meta", "lead_times", "results"})

    included, _ = _validate_meta(top["meta"])

    lead_times = _sequence(top["lead_times"], "lead_times")
    if not lead_times:
        _fail("lead_times", "must list at least one lead time")
    for i, lead in enumerate(lead_times):
        _integer(lead, f"lead_times[{i}]")
    if len(set(lead_times)) != len(lead_times):
        _fail("lead_times", f"lead times must be unique, got {lead_times}")

    results = _mapping(top["results"], "results")
    for key in results:
        if not isinstance(key, str):
            _fail(
                "results",
                f"key {key!r} must be a string; results keys are the string forms of "
                'lead_times ("6", not 6)',
            )
    expected_keys = [str(lead) for lead in lead_times]
    missing = [k for k in expected_keys if k not in results]
    if missing:
        _fail("results", f"missing entries for lead_times {missing}")
    extra = sorted(k for k in results if k not in expected_keys)
    if extra:
        _fail("results", f"has key(s) {extra} that are not in lead_times {lead_times}")

    for key in expected_keys:
        _validate_lead(results[key], included, key)


def load_and_validate(path: str | Path) -> dict:
    """Read, parse and validate a results document. The single entry point for callers."""
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"{target}: cannot be read ({exc})") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError(f"{target}: is not valid JSON ({exc})") from exc
    if not isinstance(doc, dict):
        raise ContractError(f"{target}: top level must be an object, got {type(doc).__name__}")
    validate_results(doc)
    return doc
