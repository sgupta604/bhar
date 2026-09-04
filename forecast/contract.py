"""Executable lock on the FORECAST-SPEC §9 ``forecast.json`` and §10
``forecast_history.json`` contracts.

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
* **That ``len(days)`` equals ``meta.window.days``** in a §10 history document. It does
  not, and it must not be made to: see :func:`_validate_history_days`.

The §10 half of this module (:func:`validate_history`,
:func:`load_and_validate_history`) is the same idea applied to the *past* view: the
scored day-by-day record behind the page's back-arrow. It shares every primitive, the
§6.2 banned-name sweep and the ``site`` / ``weights_source`` shapes with the §9 half,
and differs only where the two documents genuinely differ — most visibly in its
tolerance, :data:`HISTORY_TOL`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from backend.contract import ContractError

__all__ = [
    "BANNED_FIELD_NAMES",
    "BLEND_TOL",
    "ContractError",
    "FLOAT_TOL",
    "HISTORY_TOL",
    "STALE_AGE_MINUTES",
    "UNITS",
    "VARIABLE",
    "WEIGHT_GRID_DENOM",
    "band_for_lead",
    "is_extrapolated_lead",
    "load_and_validate_forecast",
    "load_and_validate_history",
    "validate_forecast",
    "validate_history",
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

#: Tolerance for the FORECAST-SPEC §10 history identities (``blend_f``, ``error_f``,
#: ``best_single_model_f``, ``mae_f``). **Derived, not chosen.** design-target §6
#: publishes both ``members[*]`` and ``blend_f`` at *two decimal places*. The validator
#: recomputes ``Σ w·m`` from the **rounded** members and compares it against the
#: **rounded** ``blend_f``, so the two sides can honestly disagree by up to half a unit
#: in the last published place — 0.005 °F — before any error at all has been made. The
#: trailing :data:`FLOAT_TOL` covers the binary representation of that decimal bound.
#:
#: :data:`BLEND_TOL` (1e-6) is **not** reusable here and would reject correct data: the
#: §9 forward document carries full-precision members alongside its blend, so 1e-6 is
#: right there and wrong here. Nor is 0.005 °F a rubber stamp — it is a real guard,
#: because the fault it exists to catch is a *wrong weight vector*, and a wrong vector
#: moves ``blend_f`` by tenths of a degree, two orders of magnitude clear of this bound.
HISTORY_TOL = 0.005 + FLOAT_TOL

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

#: Spec clause quoted by :func:`_exact_keys` when it rejects an unenumerated key. Two
#: documents share one message shape, so the message has to name which shape it means —
#: a §10 fault reported against §9 sends the reader to the wrong section of the spec.
_CLAUSE_FORWARD = "FORECAST-SPEC §9"
_CLAUSE_HISTORY = "FORECAST-SPEC §10"

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


# ------------------------------------------------------------------ §10 history key sets
#
# `_exact_keys` rejects anything not enumerated, so the six frozensets below **are** the
# §10 contract. FORECAST-SPEC §10 is written as a sketch rather than a locked table; these
# sets are the decided form of it (plan D-F6-2), and the builder and the page both encode
# them. Changing one is a contract change, not a tidy-up.

#: §10 top level: provenance and the scored days, nothing else. There is no `gaps` twin —
#: a day that could not be scored is recorded in `meta.omitted_days`, never as an empty day.
_HISTORY_TOP_KEYS = frozenset({"meta", "days"})

#: §10 `meta`. The sketch's eight keys plus the six additions adopted in D-F6-2, each
#: load-bearing: `weights_by_lead` is the *only* way a reader can check the `blend_f`
#: identity from the document alone; `best_single_model_by_lead` keeps the back-arrow off
#: the gitignored `forecast.json`; `omitted_days` is the only place §10's "reason recorded"
#: can live; `models_included`, `join` and `source` mirror §9's provenance.
_HISTORY_META_KEYS = frozenset(
    {
        "site",
        "variable",
        "units",
        "window",
        "leads_available",
        "weights_source",
        "generated_at",
        "is_synthetic",
        "models_included",
        "weights_by_lead",
        "best_single_model_by_lead",
        "join",
        "omitted_days",
        "source",
    }
)

#: §10 `meta.join` — the observation match, stated rather than assumed. `n_matched_rows`
#: beside `n_forecast_rows` is what makes "an empty join scores perfectly" (SPEC §10)
#: visible in the payload instead of hidden behind a flattering MAE.
_HISTORY_JOIN_KEYS = frozenset(
    {
        "tolerance_min",
        "n_forecast_rows",
        "n_matched_rows",
        "matched_pct",
        "mean_abs_offset_min",
    }
)

#: §10 `meta.omitted_days[]` — a date the join could not score, with its stated reason and
#: the counts that justify it. SPEC §10: never interpolate an observation; drop it and say so.
_HISTORY_OMITTED_KEYS = frozenset({"date", "reason", "n_forecast_rows", "n_matched_rows"})

#: §10 `days[]`. `mae_f` and `n_by_lead` are per-day summaries whose key sets are the leads
#: *present that day* — see :func:`_validate_history_day_summaries`.
_HISTORY_DAY_KEYS = frozenset({"date", "entries", "mae_f", "n_by_lead"})

#: §10 `days[].entries[]` — one scored forecast step. `obs_offset_min` is mandatory on every
#: entry: it is how far the matched observation sat from the valid time, and without it the
#: reader cannot tell a clean match from one at the edge of the window.
_HISTORY_ENTRY_KEYS = frozenset(
    {
        "valid_time",
        "init_time",
        "lead_h",
        "blend_f",
        "observed_f",
        "error_f",
        "obs_offset_min",
        "members",
        "best_single_model_f",
    }
)

#: The observation match window, in minutes, that §10 pins (`meta.join.tolerance_min`).
#: Every `obs_offset_min` is bounded by it, so the two can never drift apart.
_HISTORY_TOLERANCE_MIN = 30


# --------------------------------------------------------------------------- primitives


def _fail(path: str, message: str) -> None:
    raise ContractError(f"{path}: {message}")


def _mapping(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        _fail(path, f"expected an object, got {type(value).__name__}")
    return value  # type: ignore[return-value]


def _exact_keys(
    value: object,
    path: str,
    expected: frozenset[str],
    clause: str = _CLAUSE_FORWARD,
) -> dict:
    """Demand exactly ``expected``. ``clause`` names the spec section in the message.

    It defaults to §9 so every forward-forecast call site reads unchanged; the §10 history
    path passes :data:`_CLAUSE_HISTORY`, so a locked-shape failure sends the reader to the
    section that actually locks the shape.
    """
    obj = _mapping(value, path)
    got = set(obj)
    missing = sorted(k for k in expected if k not in got)
    if missing:
        _fail(path, f"missing required key(s) {missing}")
    extra = sorted(k for k in got if k not in expected)
    if extra:
        _fail(path, f"unexpected key(s) {extra}; the {clause} shape is locked")
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


def _window(value: object, path: str, clause: str = _CLAUSE_FORWARD) -> dict:
    window = _exact_keys(value, path, _WINDOW_KEYS, clause)
    _utc_stamp(window["start"], f"{path}.start")
    _utc_stamp(window["end"], f"{path}.end")
    _positive_integer(window["days"], f"{path}.days")
    return window


def _site(value: object, path: str, clause: str = _CLAUSE_FORWARD) -> dict:
    """The station block. One shape, shared by the §9 forward and §10 history documents.

    Both name the same station in the same way, so they validate it through the same code:
    two copies would let one document drift into accepting a site the other rejects.
    """
    site = _exact_keys(value, path, _SITE_KEYS, clause)
    _text(site["id"], f"{path}.id")
    _text(site["iem_station"], f"{path}.iem_station")
    _text(site["name"], f"{path}.name")
    lat = _number(site["lat"], f"{path}.lat")
    lon = _number(site["lon"], f"{path}.lon")
    _number(site["station_elev_m"], f"{path}.station_elev_m")
    if not -90.0 <= lat <= 90.0:
        _fail(f"{path}.lat", f"latitude out of range: {lat}")
    if not -180.0 <= lon <= 180.0:
        _fail(f"{path}.lon", f"longitude out of range: {lon}")
    return site


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

    _site(meta["site"], "meta.site")

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


def _lead_from_valid_time(
    valid_time: datetime,
    init_time: datetime,
    path: str,
    origin: str = "meta.cycle.init_time",
    clause: str = "FORECAST-SPEC §9 rule 3",
) -> int:
    """Whole hours from ``init_time`` to ``valid_time``, or a failure naming ``path``.

    ``origin`` and ``clause`` are parameters because the §9 forward document carries one
    init time for the whole file (``meta.cycle.init_time``) while a §10 history entry
    carries its own; the arithmetic and the whole-hour rule are identical, so they are
    written once.
    """
    offset_hours = (valid_time - init_time).total_seconds() / 3600.0
    whole = round(offset_hours)
    if abs(offset_hours - whole) > FLOAT_TOL:
        _fail(
            path,
            f"valid_time is {offset_hours} h after {origin}, which is not a "
            f"whole number of hours ({clause})",
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


# --------------------------------------------------------------------------- §10 history
#
# The past view. Everything below validates ``forecast_history.json`` — the scored,
# day-by-day record behind the page's back-arrow — against FORECAST-SPEC §10. It reuses
# every primitive above, the §6.2 banned-name sweep, and the ``site`` / ``weights_source``
# shapes; it does not reuse :data:`BLEND_TOL` (see :data:`HISTORY_TOL`).


#: The calendar-date form §10 uses for a day. UTC everywhere, so no offset is carried.
_HISTORY_DATE_FORMAT = "%Y-%m-%d"


def _lead_key(lead_h: int) -> str:
    """The JSON object key for a lead hour. Decided **once**, here.

    JSON has no integer keys, so ``meta.weights_by_lead``, ``meta.best_single_model_by_lead``,
    ``days[].mae_f`` and ``days[].n_by_lead`` are all objects keyed by the *decimal hour
    count as text*: ``"6"``, ``"12"``, ``"24"``. No zero padding, no ``h`` suffix, no sign.

    The builder writes these keys and the page reads them, so the form has to be one
    decision in one place rather than two guesses that agree until they do not. A document
    keyed ``"06"`` or ``"6h"`` is rejected here, loudly, instead of rendering a page whose
    lookups all silently miss and whose table is quietly empty.
    """
    return str(lead_h)


def _lead_keyed(value: object, path: str, leads: Sequence[int], source: str) -> dict:
    """A JSON object whose keys are exactly ``leads``, in the :func:`_lead_key` form."""
    obj = _mapping(value, path)
    expected = {_lead_key(lead) for lead in leads}
    got = set(obj)
    if got != expected:
        _fail(
            path,
            f"keys must be exactly {sorted(expected)} — {source} — each written as its "
            f"decimal hour count, because JSON has no integer keys. Missing "
            f"{sorted(expected - got)}, unexpected {sorted(got - expected)}",
        )
    return obj


def _history_date(value: object, path: str) -> date:
    """A ``YYYY-MM-DD`` UTC calendar date, parsed strictly."""
    text = _text(value, path)
    try:
        parsed = datetime.strptime(text, _HISTORY_DATE_FORMAT).date()
    except ValueError as exc:
        raise ContractError(
            f"{path}: must be a UTC calendar date written YYYY-MM-DD, got {text!r} ({exc})"
        ) from exc
    if parsed.isoformat() != text:
        _fail(
            path,
            f"must be a zero-padded UTC calendar date written YYYY-MM-DD, got {text!r}; "
            f"{parsed.isoformat()!r} is the same day spelled the one way the page sorts on",
        )
    return parsed


# ------------------------------------------------------------------------ §10 meta


def _validate_history_leads(value: object) -> list[int]:
    path = "meta.leads_available"
    raw = _sequence(value, path)
    if not raw:
        _fail(
            path,
            "must list at least one lead hour; with none, no entry in the document could "
            "name a lead the page is allowed to show",
        )
    leads = [_non_negative_integer(entry, f"{path}[{index}]") for index, entry in enumerate(raw)]
    for index in range(1, len(leads)):
        if leads[index] <= leads[index - 1]:
            _fail(
                path,
                f"must be strictly ascending and free of duplicates, but {leads[index]} "
                f"follows {leads[index - 1]} at index {index}",
            )
    return leads


def _validate_history_models(value: object) -> list[str]:
    path = "meta.models_included"
    raw = _sequence(value, path)
    if not raw:
        _fail(path, "must list at least one model")
    included: list[str] = []
    for index, entry in enumerate(raw):
        name = _text(entry, f"{path}[{index}]")
        if name != name.upper():
            _fail(
                f"{path}[{index}]",
                f"model names are UPPERCASE throughout the payload, got {name!r}",
            )
        included.append(name)
    if len(set(included)) != len(included):
        _fail(path, f"model names must be unique, got {included}")
    return included


def _validate_weights_by_lead(
    value: object, leads: Sequence[int], included: Sequence[str]
) -> dict[str, dict[str, float]]:
    """The fitted vector published at every lead, so the blend identity is checkable.

    Without this block a reader has ``blend_f`` and its members and no way to tell whether
    the one is the weighted sum of the others. With it, :func:`_validate_history_entries`
    recomputes every published number from the document alone.
    """
    path = "meta.weights_by_lead"
    obj = _lead_keyed(value, path, leads, "the leads in meta.leads_available")
    included_set = set(included)

    vectors: dict[str, dict[str, float]] = {}
    for lead in leads:
        key = _lead_key(lead)
        vector_path = f"{path}.{key}"
        vector = _mapping(obj[key], vector_path)
        if set(vector) != included_set:
            _fail(
                vector_path,
                f"keys must be exactly meta.models_included {sorted(included_set)}, got "
                f"{sorted(vector)}",
            )
        # Range, then the sum, then the 0.1 grid — the §9 order, for the same reason: a
        # vector that does not sum to 1 is the more fundamental fault and the one to name.
        # Note also what is absent: no weight here is ever rescaled over the subset of
        # models that happened to arrive. A missing member makes the entry inadmissible,
        # not an occasion to redistribute somebody else's share.
        values: dict[str, float] = {}
        for model in included:
            weight_path = f"{vector_path}.{model}"
            weight = _number(vector[model], weight_path)
            if weight < -FLOAT_TOL or weight > 1.0 + FLOAT_TOL:
                _fail(weight_path, f"weight must lie in [0, 1], got {weight}")
            values[model] = weight
        total = sum(values.values())
        if abs(total - 1.0) > FLOAT_TOL:
            _fail(vector_path, f"weights must sum to 1.0 within 1e-9, got {total!r}")
        for model in included:
            scaled = values[model] * WEIGHT_GRID_DENOM
            if abs(scaled - round(scaled)) > FLOAT_TOL * WEIGHT_GRID_DENOM:
                _fail(
                    f"{vector_path}.{model}",
                    f"weight must be a multiple of 0.1 — the fitted grid step (SPEC §5) — "
                    f"got {values[model]}",
                )
        vectors[key] = values
    return vectors


def _validate_best_single_by_lead(
    value: object, leads: Sequence[int], included: Sequence[str]
) -> dict[str, str]:
    path = "meta.best_single_model_by_lead"
    obj = _lead_keyed(value, path, leads, "the leads in meta.leads_available")
    included_set = set(included)

    names: dict[str, str] = {}
    for lead in leads:
        key = _lead_key(lead)
        name = _text(obj[key], f"{path}.{key}")
        if name not in included_set:
            _fail(
                f"{path}.{key}",
                f"names {name!r}, which is not in meta.models_included "
                f"{sorted(included_set)}; the comparison model is one of the members, "
                "named once by the backtest",
            )
        names[key] = name
    return names


def _validate_history_join(value: object) -> None:
    path = "meta.join"
    join = _exact_keys(value, path, _HISTORY_JOIN_KEYS, _CLAUSE_HISTORY)

    tolerance = _integer(join["tolerance_min"], f"{path}.tolerance_min")
    if tolerance != _HISTORY_TOLERANCE_MIN:
        _fail(
            f"{path}.tolerance_min",
            f"must be {_HISTORY_TOLERANCE_MIN}, got {tolerance}; the nearest-observation "
            "match window is fixed, and a document that widens it is reporting a different "
            "experiment under the same name",
        )

    n_forecast = _non_negative_integer(join["n_forecast_rows"], f"{path}.n_forecast_rows")
    n_matched = _non_negative_integer(join["n_matched_rows"], f"{path}.n_matched_rows")
    if n_matched > n_forecast:
        _fail(
            f"{path}.n_matched_rows",
            f"is {n_matched}, more than n_forecast_rows ({n_forecast}); the join can only "
            "match rows that were offered to it",
        )

    for key in ("matched_pct", "mean_abs_offset_min"):
        measure = _number(join[key], f"{path}.{key}")
        if measure < 0:
            _fail(f"{path}.{key}", f"must not be negative, got {measure}")


def _validate_omitted_days(value: object) -> list[date]:
    """Dates the join could not score, each with its stated reason. Possibly empty.

    SPEC §10: an observation outside the match window is dropped, never interpolated. This
    array is where that drop is *declared*, so a missing day is a recorded fact rather than
    a gap the reader has to notice.
    """
    path = "meta.omitted_days"
    raw = _sequence(value, path)

    dates: list[date] = []
    for index, entry in enumerate(raw):
        item_path = f"{path}[{index}]"
        item = _exact_keys(entry, item_path, _HISTORY_OMITTED_KEYS, _CLAUSE_HISTORY)

        dates.append(_history_date(item["date"], f"{item_path}.date"))
        _text(item["reason"], f"{item_path}.reason")
        _non_negative_integer(item["n_forecast_rows"], f"{item_path}.n_forecast_rows")
        n_matched = _non_negative_integer(item["n_matched_rows"], f"{item_path}.n_matched_rows")
        if n_matched != 0:
            _fail(
                f"{item_path}.n_matched_rows",
                f"is {n_matched}, but an omitted day is by definition one on which nothing "
                "matched; a date with matched rows belongs in days, scored",
            )

    if len(set(dates)) != len(dates):
        repeated = sorted({day for day in dates if dates.count(day) > 1})
        _fail(path, f"date(s) {[day.isoformat() for day in repeated]} are listed more than once")
    return dates


def _validate_history_meta(value: object) -> dict:
    meta = _exact_keys(value, "meta", _HISTORY_META_KEYS, _CLAUSE_HISTORY)

    _site(meta["site"], "meta.site", _CLAUSE_HISTORY)

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

    window = _window(meta["window"], "meta.window", _CLAUSE_HISTORY)
    window_start = _instant(window["start"], "meta.window.start")
    window_end = _instant(window["end"], "meta.window.end")
    if window_end < window_start:
        _fail(
            "meta.window.end",
            f"{window['end']!r} is earlier than meta.window.start {window['start']!r}",
        )

    _text(meta["source"], "meta.source")
    _instant(meta["generated_at"], "meta.generated_at")
    _boolean(meta["is_synthetic"], "meta.is_synthetic")

    # The §9 shape, validated by the §9 code at the same JSON path. The history document
    # and the forward document are fitted from the same weights file, so they had better
    # describe it identically.
    _validate_weights_source(meta["weights_source"])

    leads = _validate_history_leads(meta["leads_available"])
    included = _validate_history_models(meta["models_included"])

    return {
        "leads_available": leads,
        "models_included": included,
        "weights_by_lead": _validate_weights_by_lead(meta["weights_by_lead"], leads, included),
        "best_single_model_by_lead": _validate_best_single_by_lead(
            meta["best_single_model_by_lead"], leads, included
        ),
        "join": _validate_history_join(meta["join"]),
        "omitted_days": _validate_omitted_days(meta["omitted_days"]),
        "window_start": window_start.date(),
        "window_end": window_end.date(),
    }


# ------------------------------------------------------------------------ §10 days


def _validate_history_entries(value: object, day_path: str, context: dict) -> dict[int, list[float]]:
    """Validate one day's entries; return that day's signed errors, grouped by lead."""
    path = f"{day_path}.entries"
    entries = _sequence(value, path)
    if not entries:
        _fail(
            path,
            "must contain at least one scored entry; an empty entries array scores "
            "perfectly against nothing and publishes a fake zero error (SPEC §10). A date "
            "the join could not match belongs in meta.omitted_days with its recorded "
            "reason, never in days as an empty day",
        )

    included = context["models_included"]
    included_set = set(included)
    leads = context["leads_available"]
    leads_set = set(leads)
    weights = context["weights_by_lead"]
    best_by_lead = context["best_single_model_by_lead"]

    errors_by_lead: dict[int, list[float]] = {}

    for index, raw_entry in enumerate(entries):
        entry_path = f"{path}[{index}]"
        entry = _exact_keys(raw_entry, entry_path, _HISTORY_ENTRY_KEYS, _CLAUSE_HISTORY)

        valid_time = _instant(entry["valid_time"], f"{entry_path}.valid_time")
        init_time = _instant(entry["init_time"], f"{entry_path}.init_time")

        lead_h = _integer(entry["lead_h"], f"{entry_path}.lead_h")
        offset = _lead_from_valid_time(
            valid_time,
            init_time,
            f"{entry_path}.lead_h",
            origin=f"{entry_path}.init_time",
            clause=_CLAUSE_HISTORY,
        )
        if lead_h != offset:
            _fail(
                f"{entry_path}.lead_h",
                f"is {lead_h} but valid_time is {offset} h after init_time "
                f"({entry['init_time']!r}); the lead is the distance between those two "
                f"instants, not a label attached to the row ({_CLAUSE_HISTORY})",
            )
        if lead_h not in leads_set:
            _fail(
                f"{entry_path}.lead_h",
                f"is {lead_h}, which is not one of meta.leads_available {list(leads)}; the "
                "archive was fetched at those leads and the page may show no other",
            )

        members = _mapping(entry["members"], f"{entry_path}.members")
        if set(members) != included_set:
            _fail(
                f"{entry_path}.members",
                f"keys must be exactly meta.models_included {sorted(included_set)}, got "
                f"{sorted(members)}; an entry short of a member was never blended and "
                "belongs nowhere in this document",
            )
        member_values: dict[str, float] = {}
        for model in included:
            member_path = f"{entry_path}.members.{model}"
            if members[model] is None:
                _fail(
                    member_path,
                    "is null; an entry short of a member was never blended, and a partial "
                    "blend is a number with no provenance",
                )
            member_values[model] = _number(members[model], member_path)

        lead_key = _lead_key(lead_h)

        blend_f = _number(entry["blend_f"], f"{entry_path}.blend_f")
        expected_blend = sum(weights[lead_key][model] * member_values[model] for model in included)
        if abs(blend_f - expected_blend) > HISTORY_TOL:
            _fail(
                f"{entry_path}.blend_f",
                f"is {blend_f} but sum(meta.weights_by_lead[{lead_key!r}][m] * members[m]) "
                f"= {expected_blend!r}; the displayed number must be the weighted sum of "
                f"its members within {HISTORY_TOL} (FORECAST-SPEC §10, NON-NEGOTIABLE). An "
                "entry that fails this is rejected, never repaired",
            )

        observed_f = _number(entry["observed_f"], f"{entry_path}.observed_f")
        error_f = _number(entry["error_f"], f"{entry_path}.error_f")
        expected_error = blend_f - observed_f
        if abs(error_f - expected_error) > HISTORY_TOL:
            _fail(
                f"{entry_path}.error_f",
                f"is {error_f} but blend_f - observed_f = {expected_error!r}. The error is "
                "SIGNED: positive means the blend ran warm that hour, negative means it ran "
                "cold. An absolute value here would erase the bias the page exists to show",
            )

        best_name = best_by_lead[lead_key]
        best_value = _number(entry["best_single_model_f"], f"{entry_path}.best_single_model_f")
        if abs(best_value - member_values[best_name]) > HISTORY_TOL:
            _fail(
                f"{entry_path}.best_single_model_f",
                f"is {best_value} but members[{best_name!r}] = {member_values[best_name]!r}, "
                f"and {best_name!r} is what meta.best_single_model_by_lead names at "
                f"{lead_h} h. The comparison is against the model the backtest picked in "
                "advance, never against whichever member happened to land closest on the "
                "day — picking after the fact reads the observation before choosing",
            )

        obs_offset_min = _integer(entry["obs_offset_min"], f"{entry_path}.obs_offset_min")
        if abs(obs_offset_min) > _HISTORY_TOLERANCE_MIN:
            _fail(
                f"{entry_path}.obs_offset_min",
                f"is {obs_offset_min} min from the valid time, outside the "
                f"{_HISTORY_TOLERANCE_MIN}-minute match window declared at "
                "meta.join.tolerance_min; an observation further out than that is dropped, "
                "never shifted, carried forward or filled in",
            )

        errors_by_lead.setdefault(lead_h, []).append(error_f)

    return errors_by_lead


def _validate_history_day_summaries(
    day: dict, day_path: str, errors_by_lead: dict[int, list[float]]
) -> None:
    """``mae_f`` and ``n_by_lead``, recomputed from the entries they claim to summarize.

    Both are keyed by **the leads present that day**, not by ``meta.leads_available``. The
    two partial days at the edges of the window match at only some leads, and a summary
    padded out to the full lead list would have to invent an MAE for a lead with no
    entries — a zero that reads like a perfect forecast.
    """
    present = sorted(errors_by_lead)
    source = f"the lead hours actually present in {day_path}.entries"

    mae = _lead_keyed(day["mae_f"], f"{day_path}.mae_f", present, source)
    counts = _lead_keyed(day["n_by_lead"], f"{day_path}.n_by_lead", present, source)

    for lead in present:
        key = _lead_key(lead)
        errors = errors_by_lead[lead]

        mae_path = f"{day_path}.mae_f.{key}"
        published = _number(mae[key], mae_path)
        if published < 0:
            _fail(mae_path, f"a mean absolute error cannot be negative, got {published}")
        expected = sum(abs(error) for error in errors) / len(errors)
        if abs(published - expected) > HISTORY_TOL:
            _fail(
                mae_path,
                f"is {published} but the mean of abs(error_f) over this day's {len(errors)} "
                f"entries at {lead} h is {expected!r}; the summary is recomputed from the "
                f"entries, within {HISTORY_TOL}, so it can never drift from what it "
                "summarizes",
            )

        count_path = f"{day_path}.n_by_lead.{key}"
        published_count = _non_negative_integer(counts[key], count_path)
        if published_count != len(errors):
            _fail(
                count_path,
                f"is {published_count} but this day carries {len(errors)} entries at "
                f"{lead} h; the count is what tells a reader a one-sample daily MAE apart "
                "from a four-sample one",
            )


def _validate_history_days(value: object, context: dict) -> list[date]:
    days = _sequence(value, "days")
    if not days:
        _fail(
            "days",
            "must contain at least one scored day; an empty history renders an empty "
            "back-arrow and scores perfectly against nothing (SPEC §10)",
        )

    # NOTHING HERE CHECKS len(days) AGAINST meta.window.days, AND NOTHING EVER SHOULD.
    # `days` is 32 against a `meta.window.days` of 30: the fitted window is 30 whole days,
    # copied verbatim from results.json, while the archive's UTC calendar dates include two
    # partial days at the edges. They are two different facts. Trimming the edges so the
    # count "reads right" is tuning the experiment to produce a tidier result — exactly what
    # SPEC §10 forbids. If you came here to make these numbers agree, do not.
    start = context["window_start"]
    end = context["window_end"]

    dates: list[date] = []
    previous: date | None = None

    for index, entry in enumerate(days):
        path = f"days[{index}]"
        day = _exact_keys(entry, path, _HISTORY_DAY_KEYS, _CLAUSE_HISTORY)

        day_date = _history_date(day["date"], f"{path}.date")
        if previous is not None and day_date <= previous:
            _fail(
                f"{path}.date",
                f"{day_date.isoformat()} does not follow days[{index - 1}].date "
                f"({previous.isoformat()}); days are sorted by date, strictly ascending, "
                "each date appearing exactly once",
            )
        if not start <= day_date <= end:
            _fail(
                f"{path}.date",
                f"{day_date.isoformat()} lies outside meta.window "
                f"[{start.isoformat()}, {end.isoformat()}]; a scored day outside the window "
                "the weights were fitted on was scored against something this document does "
                "not describe",
            )
        previous = day_date
        dates.append(day_date)

        errors_by_lead = _validate_history_entries(day["entries"], path, context)
        _validate_history_day_summaries(day, path, errors_by_lead)

    return dates


def _validate_history_omission_is_disjoint(omitted: Sequence[date], scored: Sequence[date]) -> None:
    """A date is scored or omitted, never both."""
    scored_set = set(scored)
    for index, day_date in enumerate(omitted):
        if day_date in scored_set:
            _fail(
                f"meta.omitted_days[{index}].date",
                f"{day_date.isoformat()} also appears in days; a date is either scored or "
                "omitted, never both. A day declared unmatched while also carrying entries "
                "is the fake-perfect-score bug wearing a reason string",
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



def validate_history(doc: dict) -> None:
    """Validate a parsed ``forecast_history.json`` document against FORECAST-SPEC §10.

    The past-view twin of :func:`validate_forecast`. Returns ``None`` on success; raises
    :class:`ContractError` naming the offending JSON path on the first violation, e.g.
    ``days[3].entries[7].obs_offset_min``.

    The order is the same as the §9 path and for the same reason: the §6.2 banned-name
    sweep runs **first**, so a ``confidence_pct`` buried inside an entry is reported as the
    field that may never exist rather than as a stray key someone mistyped.
    """
    _sweep_banned_names(doc, "")

    top = _exact_keys(doc, "$", _HISTORY_TOP_KEYS, _CLAUSE_HISTORY)
    context = _validate_history_meta(top["meta"])
    scored_dates = _validate_history_days(top["days"], context)
    _validate_history_omission_is_disjoint(context["omitted_days"], scored_dates)


def load_and_validate_history(path: str | Path) -> dict:
    """Read, parse and validate a history document. The single entry point for callers.

    This name is a **seam**: ``backend/forecast_api.py`` resolves it by ``getattr`` on this
    module, on every request, so ``GET /api/forecast/history`` starts serving the moment
    this function exists — with no edit to that file. The endpoint's contract is exactly
    this signature: a path in, the validated document out, ``ContractError`` on any failure.
    """
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
    validate_history(doc)
    return doc


def write_atomic(
    document: dict,
    path: Path,
    tmp: Path | None = None,
    *,
    validator=validate_forecast,
) -> None:
    """Validate, then write via a temp file and ``os.replace``. Nothing lands on failure.

    The write-side twin of :func:`load_and_validate_forecast`. It lives here, rather than
    in ``make_fixture.py`` or ``refresh.py``, because both need it and neither can import
    the other without a cycle (D-F3-I).

    ``tmp`` defaults to a dotfile beside the target: ``os.replace`` is only atomic within
    one filesystem, so the temp file must share the target's directory.

    ``validator`` exists because this tree has **one** atomic-write implementation and
    **two** contracts: the §9 forward forecast (:func:`validate_forecast`, the default,
    so every existing caller is unchanged) and the §10 scored history
    (:func:`validate_history`). Copying the validate-write-replace dance into a second
    function to swap one call would mean two places where "nothing lands on failure" has
    to stay true, and the second copy is the one that quietly drifts. It is keyword-only
    so that ``tmp`` can never be passed into it by a caller that miscounts positions —
    a document validated against the wrong contract is exactly the silent fault this
    module exists to prevent.
    """
    validator(document)

    target = Path(path)
    scratch = Path(tmp) if tmp is not None else target.parent / f".{target.name}.tmp"
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.replace(scratch, target)
