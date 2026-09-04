"""Executable lock on the FORECAST-SPEC §9 ``forecast.json`` contract.

This module is the single place that decides whether a forward-forecast document is
servable. ``forecast/make_fixture.py`` and ``forecast/build.py`` validate before they
write, ``forecast/refresh.py`` writes through :func:`write_atomic`, and the API
validates on load. The point is that a *silently wrong* document — a ``blend_f`` that
is not the weighted sum of its members, a ``confidence_pct`` smuggled in beside it, a
step grid with a hole nobody declared — fails loudly here rather than rendering a
confident, fake line on the page.

Design rules:

* Pure. Every instant the validator needs arrives inside the document; this module
  never reads a wall clock, never touches the network and never reads ``data/``
  except through :func:`load_and_validate_forecast`, which is handed its path.
* Standard library only. The single import from the rest of the tree is
  :class:`backend.contract.ContractError`, re-exported here so a caller that handles
  both ``results.json`` and ``forecast.json`` needs exactly one ``except`` clause.
* Every failure raises :class:`ContractError` with a message naming the offending
  JSON path, e.g. ``forecast[7].members``.
* **No bare ``assert``** anywhere in this package. ``python -O`` deletes assertions,
  and this file is the only thing standing between the page and a fabricated number,
  so every guard raises instead.

Deliberately *not* checked:

* **The sign of ``skill.by_lead[].improvement_pct``.** SPEC §10 requires the page to
  report what the data says. A zero or negative improvement is a legitimate, expected
  result and the validator must never demand a win.
* **The literal text of a gap ``reason``.** It is free text. The live fetch path emits
  ``"absent from archive"``; FORECAST-SPEC §9's worked example says
  ``"beyond model horizon"``. Both are legitimate, so the validator requires a
  non-empty string and nothing more.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from backend.contract import ContractError

__all__ = [
    "BANNED_FIELD_NAMES",
    "BLEND_TOL",
    "ContractError",
    "FLOAT_TOL",
    "STALE_AGE_MINUTES",
    "UNITS",
    "VARIABLE",
    "WEIGHT_GRID_DENOM",
    "band_for_lead",
    "is_extrapolated_lead",
    "load_and_validate_forecast",
    "validate_forecast",
    "write_atomic",
]

#: The one variable this page publishes (FORECAST-SPEC §9).
VARIABLE = "2m_temperature"

#: Degrees F at the boundary — SPEC's key convention.
UNITS = "degF"

#: Weight grid step used by the backtest (SPEC §5, D5). Ten tenths per unit.
WEIGHT_GRID_DENOM = 10

#: Absolute tolerance for exact float identities (weight sums, grid membership).
FLOAT_TOL = 1e-9

#: Tolerance for the §9 rule 6 blend identity and the rule 6b spread identity.
#: Deliberately looser than :data:`FLOAT_TOL`: those two identities are recomputed from
#: values that made a round trip through JSON text at two decimal places, so the sum of
#: four ``weight * member`` products accumulates real representation error that a 1e-9
#: bound would reject on a perfectly honest document. 1e-6 °F is still far below any
#: temperature the page can display, so a genuinely wrong number cannot hide under it.
BLEND_TOL = 1e-6

#: A cycle older than this many minutes is stale (FORECAST-SPEC §9 rule 11).
STALE_AGE_MINUTES = 540

#: Field names banned outright by FORECAST-SPEC §6.2 — anywhere, at any depth.
BANNED_FIELD_NAMES = frozenset(
    {
        "confidence",
        "confidence_pct",
        "probability",
        "p10",
        "p50",
        "p90",
        "percentile",
        "ci_low",
        "ci_high",
        "error_bar",
        "uncertainty",
    }
)

_BANNED_NAME_MESSAGE = (
    "is a field name banned outright by FORECAST-SPEC §6.2; the payload states "
    "historical skill in the past tense and never carries a probability, a percentile "
    "or an interval around a future value"
)

_TOP_KEYS = frozenset({"meta", "forecast", "gaps", "skill"})
_META_KEYS = frozenset(
    {
        "site",
        "variable",
        "units",
        "cycle",
        "weights_source",
        "models_included",
        "horizon_h",
        "step_h",
        "source",
        "generated_at",
        "is_synthetic",
    }
)
_SITE_KEYS = frozenset({"id", "iem_station", "name", "lat", "lon", "station_elev_m"})
_CYCLE_KEYS = frozenset(
    {
        "init_time",
        "run_label",
        "target_init_time",
        "fetched_at",
        "age_minutes",
        "is_stale",
        "stale_reason",
        "cycles_fallen_back",
    }
)
_WEIGHTS_SOURCE_KEYS = frozenset(
    {"path", "generated_at", "weights_age_days", "window", "split", "fitted_leads"}
)
_WINDOW_KEYS = frozenset({"start", "end", "days"})
_SPLIT_KEYS = frozenset({"method", "train_days", "test_days"})
_ROW_KEYS = frozenset(
    {
        "valid_time",
        "lead_h",
        "blend_f",
        "weights",
        "weights_fitted_at_lead_h",
        "is_extrapolated_lead",
        "members",
        "member_spread_f",
    }
)
_GAP_KEYS = frozenset({"valid_time", "lead_h", "missing_models", "reason"})
_SKILL_KEYS = frozenset({"basis", "window", "note", "by_lead"})
_BY_LEAD_KEYS = frozenset(
    {
        "lead_h",
        "blend_mae",
        "blend_mae_in_sample",
        "best_single_model",
        "best_single_mae",
        "improvement_pct",
        "n_test",
        "independent_days_approx",
    }
)


# --------------------------------------------------------------------------- primitives


def _fail(path: str, message: str) -> None:
    raise ContractError(f"{path}: {message}")


def _mapping(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        _fail(path, f"expected an object, got {type(value).__name__}")
    return value  # type: ignore[return-value]


def _exact_keys(value: object, path: str, expected: frozenset[str]) -> dict:
    obj = _mapping(value, path)
    got = set(obj)
    missing = sorted(k for k in expected if k not in got)
    if missing:
        _fail(path, f"missing required key(s) {missing}")
    extra = sorted(k for k in got if k not in expected)
    if extra:
        _fail(path, f"unexpected key(s) {extra}; the FORECAST-SPEC §9 shape is locked")
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
    return value  # type: ignore[return-value]


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(
            path,
            f"must be a JSON boolean (true/false), got {type(value).__name__} {value!r}; "
            'the string "true" is not a boolean and would defeat the synthetic banner '
            "(FORECAST-SPEC §9 rule 9)",
        )
    return value  # type: ignore[return-value]


def _utc_stamp(value: object, path: str) -> str:
    text = _text(value, path)
    if not text.endswith("Z"):
        _fail(path, f"must be an ISO8601 UTC timestamp ending in 'Z', got {text!r}")
    return text


def _instant(value: object, path: str) -> datetime:
    """Parse a UTC stamp into an aware datetime. UTC everywhere; no local clock."""
    text = _utc_stamp(value, path)
    try:
        return datetime.fromisoformat(f"{text[:-1]}+00:00")
    except ValueError as exc:
        raise ContractError(
            f"{path}: is not a parseable ISO8601 timestamp, got {text!r} ({exc})"
        ) from exc


def _positive_integer(value: object, path: str) -> int:
    number = _integer(value, path)
    if number <= 0:
        _fail(path, f"must be a positive integer, got {number}")
    return number


def _non_negative_integer(value: object, path: str) -> int:
    number = _integer(value, path)
    if number < 0:
        _fail(path, f"must be a non-negative integer, got {number}")
    return number


def _window(value: object, path: str) -> dict:
    window = _exact_keys(value, path, _WINDOW_KEYS)
    _utc_stamp(window["start"], f"{path}.start")
    _utc_stamp(window["end"], f"{path}.end")
    _positive_integer(window["days"], f"{path}.days")
    return window


def _split(value: object, path: str) -> dict:
    split = _exact_keys(value, path, _SPLIT_KEYS)
    _text(split["method"], f"{path}.method")
    for key in ("train_days", "test_days"):
        _positive_integer(split[key], f"{path}.{key}")
    return split


# --------------------------------------------------------------------------- §6.2 sweep


def _sweep_banned_names(value: object, path: str) -> None:
    """Reject a FORECAST-SPEC §6.2 name at any depth, with the *right* message.

    The exact key sets already reject every one of these, but they reject them as
    "unexpected key(s)", which reads like a typo. This sweep runs first so the message
    that reaches the developer names §6.2 and says why the field may never exist.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(key, str) and key.strip().lower() in BANNED_FIELD_NAMES:
                _fail(child_path, _BANNED_NAME_MESSAGE)
            _sweep_banned_names(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _sweep_banned_names(child, f"{path}[{index}]")


# --------------------------------------------------------------------------- §7 banding


def band_for_lead(lead_h: int, fitted_leads: Sequence[int]) -> int:
    """Return the fitted lead whose weight vector a ``lead_h`` forecast step must use.

    FORECAST-SPEC §7: nearest fitted lead by absolute difference, **ties to the shorter
    lead**. This is the only implementation in the tree — ``weights.py`` and ``build.py``
    import it rather than repeating the rule, because two copies would let the builder
    and the validator agree on a shared mistake in silence.
    """
    leads = list(fitted_leads)
    if not leads:
        raise ValueError(
            "fitted_leads is empty; there is no fitted weight vector to band a lead onto, "
            "and inventing one would publish weights that were never fitted"
        )
    return min(leads, key=lambda fitted: (abs(lead_h - fitted), fitted))


def is_extrapolated_lead(lead_h: int, fitted_leads: Sequence[int]) -> bool:
    """True when ``lead_h`` lies beyond every lead the backtest ever fitted.

    Derived from ``fitted_leads``, never from the literal 24: if the backtest is refitted
    at different leads the boundary moves with it, automatically.
    """
    leads = list(fitted_leads)
    if not leads:
        raise ValueError(
            "fitted_leads is empty; without a fitted range every lead is extrapolated and "
            "the question is meaningless"
        )
    return lead_h > max(leads)


# --------------------------------------------------------------------------- meta


def _validate_cycle(value: object, generated_at: datetime) -> datetime:
    cycle = _exact_keys(value, "meta.cycle", _CYCLE_KEYS)

    init_time = _instant(cycle["init_time"], "meta.cycle.init_time")
    _text(cycle["run_label"], "meta.cycle.run_label")
    target = _instant(cycle["target_init_time"], "meta.cycle.target_init_time")
    if init_time > target:
        _fail(
            "meta.cycle.init_time",
            f"is later than meta.cycle.target_init_time ({cycle['target_init_time']!r}); a "
            "fallback moves to an earlier cycle, never a later one",
        )

    fetched_at = _instant(cycle["fetched_at"], "meta.cycle.fetched_at")
    if fetched_at > generated_at:
        _fail(
            "meta.cycle.fetched_at",
            f"is after meta.generated_at; the data cannot have been fetched after the "
            f"document that reports it was written ({cycle['fetched_at']!r})",
        )

    age_minutes = _number(cycle["age_minutes"], "meta.cycle.age_minutes")
    if age_minutes < 0:
        _fail("meta.cycle.age_minutes", f"must not be negative, got {age_minutes}")

    fallen_back = _non_negative_integer(
        cycle["cycles_fallen_back"], "meta.cycle.cycles_fallen_back"
    )

    stale = _boolean(cycle["is_stale"], "meta.cycle.is_stale")
    expected_stale = fallen_back > 0 or age_minutes > STALE_AGE_MINUTES
    if stale != expected_stale:
        _fail(
            "meta.cycle.is_stale",
            f"is {stale} but cycles_fallen_back={fallen_back} and "
            f"age_minutes={age_minutes} require {expected_stale}; a cycle is stale if and "
            f"only if a fallback fired or it is more than {STALE_AGE_MINUTES} minutes old "
            "(FORECAST-SPEC §9 rule 11)",
        )

    reason = cycle["stale_reason"]
    if stale:
        if reason is None:
            _fail(
                "meta.cycle.stale_reason",
                "must name the reason whenever is_stale is true; a stale banner with no "
                "reason tells the reader nothing (FORECAST-SPEC §9 rule 11)",
            )
        _text(reason, "meta.cycle.stale_reason")
    elif reason is not None:
        _fail(
            "meta.cycle.stale_reason",
            f"must be null when is_stale is false, got {reason!r} (FORECAST-SPEC §9 rule 11)",
        )

    return init_time


def _validate_weights_source(value: object) -> list[int]:
    source = _exact_keys(value, "meta.weights_source", _WEIGHTS_SOURCE_KEYS)

    _text(source["path"], "meta.weights_source.path")
    _utc_stamp(source["generated_at"], "meta.weights_source.generated_at")
    _non_negative_integer(source["weights_age_days"], "meta.weights_source.weights_age_days")
    _window(source["window"], "meta.weights_source.window")
    _split(source["split"], "meta.weights_source.split")

    path = "meta.weights_source.fitted_leads"
    fitted_raw = _sequence(source["fitted_leads"], path)
    if not fitted_raw:
        _fail(
            path,
            "must list at least one fitted lead; with none, every published weight vector "
            "would be one nobody ever fitted",
        )
    fitted: list[int] = []
    for index, entry in enumerate(fitted_raw):
        fitted.append(_positive_integer(entry, f"{path}[{index}]"))
    for index in range(1, len(fitted)):
        if fitted[index] <= fitted[index - 1]:
            _fail(
                path,
                f"must be strictly ascending, but {fitted[index]} follows "
                f"{fitted[index - 1]} at index {index}",
            )
    return fitted


def _validate_meta(value: object) -> dict:
    meta = _exact_keys(value, "meta", _META_KEYS)

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

    variable = _text(meta["variable"], "meta.variable")
    if variable != VARIABLE:
        _fail("meta.variable", f"must be {VARIABLE!r}, got {variable!r}")
    units = _text(meta["units"], "meta.units")
    if units != UNITS:
        _fail(
            "meta.units",
            f"must be {UNITS!r}, got {units!r}; temperatures cross into the payload in "
            "degrees F at the boundary",
        )

    included_raw = _sequence(meta["models_included"], "meta.models_included")
    if not included_raw:
        _fail("meta.models_included", "must list at least one model")
    included: list[str] = []
    for index, entry in enumerate(included_raw):
        name = _text(entry, f"meta.models_included[{index}]")
        if name != name.upper():
            _fail(
                f"meta.models_included[{index}]",
                f"model names are UPPERCASE throughout the payload, got {name!r}",
            )
        included.append(name)
    if len(set(included)) != len(included):
        _fail("meta.models_included", f"model names must be unique, got {included}")

    horizon_h = _positive_integer(meta["horizon_h"], "meta.horizon_h")
    step_h = _positive_integer(meta["step_h"], "meta.step_h")
    if horizon_h % step_h != 0:
        _fail(
            "meta.step_h",
            f"{step_h} h does not divide meta.horizon_h ({horizon_h} h); the step grid "
            "would not reach the published horizon",
        )

    _text(meta["source"], "meta.source")
    generated_at = _instant(meta["generated_at"], "meta.generated_at")
    _boolean(meta["is_synthetic"], "meta.is_synthetic")

    init_time = _validate_cycle(meta["cycle"], generated_at)
    fitted_leads = _validate_weights_source(meta["weights_source"])

    return {
        "models_included": included,
        "init_time": init_time,
        "horizon_h": horizon_h,
        "step_h": step_h,
        "fitted_leads": fitted_leads,
    }


# --------------------------------------------------------------------------- step grid


def _lead_from_valid_time(valid_time: datetime, init_time: datetime, path: str) -> int:
    offset_hours = (valid_time - init_time).total_seconds() / 3600.0
    whole = round(offset_hours)
    if abs(offset_hours - whole) > FLOAT_TOL:
        _fail(
            path,
            f"valid_time is {offset_hours} h after meta.cycle.init_time, which is not a "
            "whole number of hours (FORECAST-SPEC §9 rule 3)",
        )
    return whole


def _check_on_grid(lead_h: int, context: dict, path: str, kind: str) -> None:
    horizon_h = context["horizon_h"]
    step_h = context["step_h"]
    if lead_h > horizon_h:
        _fail(
            path,
            f"is {lead_h} h, beyond meta.horizon_h ({horizon_h} h); a {kind} outside the "
            "published step grid is not part of it (FORECAST-SPEC §9 rule 8)",
        )
    if lead_h < step_h or lead_h % step_h != 0:
        _fail(
            path,
            f"is {lead_h} h, which is not on the meta.step_h grid (multiples of {step_h} h "
            f"from {step_h} h to {horizon_h} h — FORECAST-SPEC §9 rule 8)",
        )


# --------------------------------------------------------------------------- forecast


def _validate_rows(value: object, context: dict) -> list[int]:
    rows = _sequence(value, "forecast")
    if not rows:
        _fail(
            "forecast",
            "must contain at least one row; an empty forecast renders an empty page and "
            "scores perfectly against nothing (SPEC §10)",
        )

    included = context["models_included"]
    included_set = set(included)
    init_time = context["init_time"]
    fitted_leads = context["fitted_leads"]

    leads: list[int] = []
    previous: datetime | None = None
    previous_text = ""

    for index, entry in enumerate(rows):
        path = f"forecast[{index}]"
        row = _exact_keys(entry, path, _ROW_KEYS)

        valid_time = _instant(row["valid_time"], f"{path}.valid_time")
        if previous is not None:
            if valid_time == previous:
                _fail(
                    f"{path}.valid_time",
                    f"duplicates {previous_text!r} at forecast[{index - 1}].valid_time; each "
                    "step appears exactly once (FORECAST-SPEC §9 rule 2)",
                )
            if valid_time < previous:
                _fail(
                    f"{path}.valid_time",
                    f"{row['valid_time']!r} is earlier than {previous_text!r} at "
                    f"forecast[{index - 1}].valid_time; forecast must be sorted by "
                    "valid_time strictly ascending (FORECAST-SPEC §9 rule 2)",
                )
        previous = valid_time
        previous_text = row["valid_time"]

        lead_h = _integer(row["lead_h"], f"{path}.lead_h")
        offset = _lead_from_valid_time(valid_time, init_time, f"{path}.lead_h")
        if lead_h != offset:
            _fail(
                f"{path}.lead_h",
                f"is {lead_h} but valid_time is {offset} h after meta.cycle.init_time "
                "(FORECAST-SPEC §9 rule 3)",
            )
        _check_on_grid(lead_h, context, f"{path}.lead_h", "forecast row")
        leads.append(lead_h)

        weights = _mapping(row["weights"], f"{path}.weights")
        if set(weights) != included_set:
            _fail(
                f"{path}.weights",
                f"keys must be exactly meta.models_included {sorted(included_set)}, got "
                f"{sorted(weights)}",
            )
        # Range first, then the sum, then the 0.1 grid: a vector that does not sum to 1
        # is a more fundamental fault than one that is merely off-grid, and it is the
        # fault a reader needs named. Note also what is absent here — when a model is
        # missing the step becomes a gap; weights are never rescaled over a subset of
        # models, because that would silently publish a blend nobody ever fitted.
        values: dict[str, float] = {}
        for model in included:
            weight_path = f"{path}.weights.{model}"
            weight = _number(weights[model], weight_path)
            if weight < -FLOAT_TOL or weight > 1.0 + FLOAT_TOL:
                _fail(weight_path, f"weight must lie in [0, 1], got {weight}")
            values[model] = weight
        total = sum(values.values())
        if abs(total - 1.0) > FLOAT_TOL:
            _fail(f"{path}.weights", f"weights must sum to 1.0 within 1e-9, got {total!r}")
        for model in included:
            scaled = values[model] * WEIGHT_GRID_DENOM
            if abs(scaled - round(scaled)) > FLOAT_TOL * WEIGHT_GRID_DENOM:
                _fail(
                    f"{path}.weights.{model}",
                    f"weight must be a multiple of 0.1 — the fitted grid step (SPEC §5) — "
                    f"got {values[model]}",
                )

        fitted_at = _integer(
            row["weights_fitted_at_lead_h"], f"{path}.weights_fitted_at_lead_h"
        )
        if fitted_at not in fitted_leads:
            _fail(
                f"{path}.weights_fitted_at_lead_h",
                f"is {fitted_at}, which is not one of meta.weights_source.fitted_leads "
                f"{fitted_leads}; no weight vector was ever fitted there",
            )
        expected_band = band_for_lead(lead_h, fitted_leads)
        if fitted_at != expected_band:
            _fail(
                f"{path}.weights_fitted_at_lead_h",
                f"is {fitted_at} but the FORECAST-SPEC §7 banding table maps a {lead_h} h "
                f"lead to the {expected_band} h fitted vector (nearest fitted lead, ties to "
                "the shorter)",
            )
        extrapolated = _boolean(row["is_extrapolated_lead"], f"{path}.is_extrapolated_lead")
        expected_extrapolated = is_extrapolated_lead(lead_h, fitted_leads)
        if extrapolated != expected_extrapolated:
            _fail(
                f"{path}.is_extrapolated_lead",
                f"is {extrapolated} but a {lead_h} h lead "
                f"{'is' if expected_extrapolated else 'is not'} beyond the longest fitted "
                f"lead ({max(fitted_leads)} h); the page marks the unverified region from "
                "this flag",
            )

        members = _mapping(row["members"], f"{path}.members")
        if set(members) != included_set:
            _fail(
                f"{path}.members",
                f"keys must be exactly meta.models_included {sorted(included_set)}, got "
                f"{sorted(members)}; a step missing any member belongs in gaps, not in "
                "forecast (FORECAST-SPEC §9 rule 7)",
            )
        member_values: dict[str, float] = {}
        for model in included:
            member_path = f"{path}.members.{model}"
            if members[model] is None:
                _fail(
                    member_path,
                    "is null; a step missing any member belongs in gaps, not in forecast "
                    "(FORECAST-SPEC §9 rule 7)",
                )
            member_values[model] = _number(members[model], member_path)

        blend_f = _number(row["blend_f"], f"{path}.blend_f")
        expected_blend = sum(values[model] * member_values[model] for model in included)
        if abs(blend_f - expected_blend) > BLEND_TOL:
            _fail(
                f"{path}.blend_f",
                f"is {blend_f} but sum(weights[m] * members[m]) = {expected_blend!r}; the "
                f"displayed number must be the weighted sum of its members within "
                f"{BLEND_TOL} (FORECAST-SPEC §9 rule 6, NON-NEGOTIABLE). A row that fails "
                "this is rejected, never repaired — a repaired row is a number with no "
                "provenance",
            )

        spread = _number(row["member_spread_f"], f"{path}.member_spread_f")
        expected_spread = max(member_values.values()) - min(member_values.values())
        if abs(spread - expected_spread) > BLEND_TOL:
            _fail(
                f"{path}.member_spread_f",
                f"is {spread} but max(members) - min(members) = {expected_spread!r}; spread "
                "is a fact about the models (FORECAST-SPEC §6.3), so it must be exactly "
                "that subtraction",
            )

    return leads


# --------------------------------------------------------------------------- gaps


def _validate_gaps(value: object, context: dict) -> list[int]:
    gaps = _sequence(value, "gaps")
    included_set = set(context["models_included"])
    init_time = context["init_time"]

    leads: list[int] = []
    for index, entry in enumerate(gaps):
        path = f"gaps[{index}]"
        gap = _exact_keys(entry, path, _GAP_KEYS)

        valid_time = _instant(gap["valid_time"], f"{path}.valid_time")
        lead_h = _integer(gap["lead_h"], f"{path}.lead_h")
        offset = _lead_from_valid_time(valid_time, init_time, f"{path}.lead_h")
        if lead_h != offset:
            _fail(
                f"{path}.lead_h",
                f"is {lead_h} but valid_time is {offset} h after meta.cycle.init_time "
                "(FORECAST-SPEC §9 rule 3)",
            )
        _check_on_grid(lead_h, context, f"{path}.lead_h", "gap")
        leads.append(lead_h)

        missing_path = f"{path}.missing_models"
        missing_raw = _sequence(gap["missing_models"], missing_path)
        if not missing_raw:
            _fail(
                missing_path,
                "must name at least one model; a step with every member present is a "
                "forecast row, not a gap",
            )
        missing: list[str] = []
        for position, name_value in enumerate(missing_raw):
            name = _text(name_value, f"{missing_path}[{position}]")
            if name != name.upper():
                _fail(
                    f"{missing_path}[{position}]",
                    f"model names are UPPERCASE throughout the payload, got {name!r}",
                )
            missing.append(name)
        if len(set(missing)) != len(missing):
            _fail(missing_path, f"model names must be unique, got {missing}")
        unknown = sorted(set(missing) - included_set)
        if unknown:
            _fail(
                missing_path,
                f"names model(s) {unknown} that are not in meta.models_included "
                f"{sorted(included_set)}",
            )

        # Free text by design: the live path says "absent from archive", §9's example says
        # "beyond model horizon". Both are true; neither is pinned here.
        _text(gap["reason"], f"{path}.reason")

    if len(set(leads)) != len(leads):
        repeated = sorted({lead for lead in leads if leads.count(lead) > 1})
        _fail("gaps", f"lead(s) {repeated} h are listed more than once")

    return leads


def _validate_coverage(row_leads: list[int], gap_leads: list[int], context: dict) -> None:
    """FORECAST-SPEC §9 rule 8, built from ``meta`` alone (D-F3-B).

    The step grid is derived from ``horizon_h`` and ``step_h``, never from whatever the
    document happens to contain, so a document cannot define its own idea of complete.
    """
    horizon_h = context["horizon_h"]
    step_h = context["step_h"]
    universe = list(range(step_h, horizon_h + 1, step_h))

    both = sorted(set(row_leads) & set(gap_leads))
    if both:
        _fail(
            "gaps",
            f"lead(s) {both} h appear in both forecast and gaps; a step is forecast or it "
            "is missing, never both (FORECAST-SPEC §9 rule 8)",
        )

    covered = set(row_leads) | set(gap_leads)
    uncovered = [lead for lead in universe if lead not in covered]
    if uncovered:
        _fail(
            "forecast",
            f"lead(s) {uncovered} h appear in neither forecast nor gaps; the union must "
            f"cover the whole {step_h} h grid out to {horizon_h} h, so that a hole is "
            "declared rather than silently dropped (FORECAST-SPEC §9 rule 8)",
        )


# --------------------------------------------------------------------------- skill


def _validate_skill(value: object, context: dict) -> None:
    skill = _exact_keys(value, "skill", _SKILL_KEYS)
    _text(skill["basis"], "skill.basis")
    _window(skill["window"], "skill.window")
    _text(skill["note"], "skill.note")

    fitted_leads = context["fitted_leads"]
    by_lead = _sequence(skill["by_lead"], "skill.by_lead")

    leads: list[int] = []
    for index, entry in enumerate(by_lead):
        path = f"skill.by_lead[{index}]"
        item = _exact_keys(entry, path, _BY_LEAD_KEYS)

        leads.append(_positive_integer(item["lead_h"], f"{path}.lead_h"))
        for key in ("blend_mae", "blend_mae_in_sample", "best_single_mae"):
            error = _number(item[key], f"{path}.{key}")
            if error < 0:
                _fail(f"{path}.{key}", f"a mean absolute error cannot be negative, got {error}")
        _text(item["best_single_model"], f"{path}.best_single_model")
        # No sign constraint on improvement_pct. SPEC §10: a zero or negative improvement
        # is a legitimate result and this validator never demands a win.
        _number(item["improvement_pct"], f"{path}.improvement_pct")
        _positive_integer(item["n_test"], f"{path}.n_test")
        _positive_integer(item["independent_days_approx"], f"{path}.independent_days_approx")

    if len(set(leads)) != len(leads):
        repeated = sorted({lead for lead in leads if leads.count(lead) > 1})
        _fail("skill.by_lead", f"lead(s) {repeated} h appear more than once")

    if set(leads) != set(fitted_leads):
        extra = sorted(set(leads) - set(fitted_leads))
        absent = sorted(set(fitted_leads) - set(leads))
        _fail(
            "skill.by_lead",
            f"must cover exactly meta.weights_source.fitted_leads {fitted_leads}; extra "
            f"lead(s) {extra}, missing lead(s) {absent}. No skill entry may be synthesized "
            "for a lead the backtest never measured (FORECAST-SPEC §9 rule 10)",
        )


# --------------------------------------------------------------------------- entry points


def validate_forecast(doc: dict) -> None:
    """Validate a parsed ``forecast.json`` document against the FORECAST-SPEC §9 contract.

    Returns ``None`` on success; raises :class:`ContractError` naming the offending JSON
    path on the first violation.
    """
    _sweep_banned_names(doc, "")

    top = _exact_keys(doc, "$", _TOP_KEYS)
    context = _validate_meta(top["meta"])
    row_leads = _validate_rows(top["forecast"], context)
    gap_leads = _validate_gaps(top["gaps"], context)
    _validate_coverage(row_leads, gap_leads, context)
    _validate_skill(top["skill"], context)


def load_and_validate_forecast(path: str | Path) -> dict:
    """Read, parse and validate a forecast document. The single entry point for callers."""
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
    validate_forecast(doc)
    return doc


def write_atomic(document: dict, path: Path, tmp: Path | None = None) -> None:
    """Validate, then write via a temp file and ``os.replace``. Nothing lands on failure.

    The write-side twin of :func:`load_and_validate_forecast`. It lives here, rather than
    in ``make_fixture.py`` or ``refresh.py``, because both need it and neither can import
    the other without a cycle (D-F3-I).

    ``tmp`` defaults to a dotfile beside the target: ``os.replace`` is only atomic within
    one filesystem, so the temp file must share the target's directory.
    """
    validate_forecast(document)

    target = Path(path)
    scratch = Path(tmp) if tmp is not None else target.parent / f".{target.name}.tmp"
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.replace(scratch, target)
