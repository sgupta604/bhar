"""Join one fetched cycle to the fitted weights and emit the FORECAST-SPEC §9 document.

This module is the seam between two conventions that must never be blurred together, and
getting that seam right is most of what it does.

The casing bridge
-----------------

Everything under ``forecast/`` and ``fetch/`` keys models in **lowercase** — ``MODELS`` is
``("hrrr", "gfs", "nam", "nbm")``, cache records live at ``records[("nam", 12)]``, and
``live.find_gaps`` reports ``missing_models=("nam",)``. ``data/results.json`` and the §9
payload key them in **UPPERCASE**. F3 owns that translation, and it is built here as one
explicit, total map derived from ``fitted.models_included``.

Total is the operative word. A ``.get()``-shaped lookup would drop a member whose casing did
not match and leave a page claiming a four-model blend over three members, with every number
on it internally consistent and quietly wrong. So:

* the map's lowercase key set must equal ``fetch.grib.MODELS``, or this module raises — a
  member set that is not the fitted one is a *different blend*, not a smaller one;
* members are indexed explicitly, never fetched with a default;
* gap model names travel through the same map, in ``models_included`` order.

What this module refuses to do
------------------------------

A step missing any member becomes a declared gap. The vector is published exactly as it was
fitted, and in particular the weights are never rescaled over a subset of models: rescaling
the survivors would publish a blend nobody ever fitted while looking entirely ordinary.

Design rules
------------

* **Pure.** ``generated_at`` is an argument. This module reads no wall clock; only
  ``forecast/refresh.py`` does.
* **No second implementation of anything.** ``_iso`` comes from ``forecast/live.py`` (F2's one
  real defect was two serializers disagreeing about sub-second precision), the §7 banding rule
  is reached through ``weights_for_lead`` (D-F3-A), and the step grid comes from the
  ``CycleResult`` the fetch produced — never from a constant written here (D-F3-D, TR6).
* **Validate before returning.** ``validate_forecast`` is the only gate, and it runs on the
  way out so a malformed document never reaches a caller (the ``score/run.py`` precedent).
* **No bare ``assert``**: ``python -O`` deletes assertions, so every guard raises.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import datetime

from fetch.grib import MODELS
from forecast.contract import UNITS, VARIABLE, ContractError, validate_forecast
from forecast.live import CycleResult, _iso, covered_leads
from forecast.weights import UNCHANGED_VECTOR_RULE, FittedWeights, weights_for_lead

__all__ = [
    "MEMBER_DECIMALS",
    "SOURCE",
    "build_forecast_document",
    "model_case_map",
]

#: FORECAST-SPEC §9 ``meta.source``. The only provenance this page has.
SOURCE = "noaa_s3_grib"

#: Decimal places each member value is stored at (D-F3-C). ``blend_f`` is then computed **from
#: the stored values** and serialized unrounded, which is what makes §9 rule 6 true by
#: construction rather than by luck. Display rounding belongs to the page, not to the payload.
MEMBER_DECIMALS = 4


# --------------------------------------------------------------------------- casing bridge


def model_case_map(models_included: Sequence[str]) -> dict[str, str]:
    """``{lowercase_key: PAYLOAD_NAME}`` for every fitted model — explicit and total.

    Built from ``fitted.models_included`` so the payload's names are the backtest's names, and
    checked against ``fetch.grib.MODELS`` so a fetched member set that is not the fitted one
    fails here rather than producing a document about a blend nobody fitted.
    """
    included = tuple(models_included)
    if not included:
        raise ContractError(
            "meta.models_included: is empty; a blend over no models is not a smaller blend, "
            "it is no blend at all"
        )

    mapping = {name.lower(): name for name in included}
    if len(mapping) != len(included):
        raise ContractError(
            f"meta.models_included: {list(included)} collides under lowercasing to "
            f"{sorted(mapping)}; the casing bridge must be one-to-one or a member is dropped "
            "in translation"
        )
    if set(mapping) != set(MODELS):
        raise ContractError(
            f"meta.models_included: the fitted member set {list(included)} lowercases to "
            f"{sorted(mapping)}, which is not the fetched member set {sorted(MODELS)}. A blend "
            f"over a different set of models is a different blend — {UNCHANGED_VECTOR_RULE}."
        )
    return mapping


def _check_record_models(records: dict[tuple[str, int], dict], case_map: dict[str, str]) -> None:
    """Every model key in the cache records must be one the payload knows how to name."""
    present = {model for (model, _lead) in records}
    unknown = sorted(present - set(case_map))
    if unknown:
        raise ContractError(
            f"cycle.records: carries model key(s) {unknown} that are not in "
            f"meta.models_included {sorted(case_map.values())}. An unrecognised key is never "
            "dropped silently — it would leave the payload describing a blend over a member "
            "set nobody chose."
        )


# --------------------------------------------------------------------------- one step


def _members_at(
    records: dict[tuple[str, int], dict], lead_h: int, case_map: dict[str, str]
) -> dict[str, float]:
    """Every member's value at one step, UPPERCASE-keyed, rounded to ``MEMBER_DECIMALS``.

    Indexed explicitly. A partial member set raises rather than yielding a shorter row: the
    step belongs in ``gaps``, because the weights are never rescaled over a subset of models.
    """
    absent = [
        payload_name
        for cache_key, payload_name in case_map.items()
        if (cache_key, lead_h) not in records
    ]
    if absent:
        raise ContractError(
            f"forecast: the step at lead {lead_h} h has no record for {absent}, so it is not a "
            f"complete member set. Such a step is declared in gaps, never blended: "
            f"{UNCHANGED_VECTOR_RULE}."
        )

    members: dict[str, float] = {}
    unusable: list[str] = []
    for cache_key, payload_name in case_map.items():
        record = records[(cache_key, lead_h)]
        value = record["temp_f"]
        if record["status"] != "success" or value is None:
            unusable.append(payload_name)
            continue
        members[payload_name] = round(float(value), MEMBER_DECIMALS)

    if unusable:
        raise ContractError(
            f"forecast: the step at lead {lead_h} h did not settle successfully for "
            f"{unusable}. Such a step is declared in gaps, never blended over the members "
            f"that happened to arrive: {UNCHANGED_VECTOR_RULE}."
        )
    return members


def _valid_time_at(
    records: dict[tuple[str, int], dict], lead_h: int, case_map: dict[str, str]
) -> str:
    """The step's valid time, **taken from the records** rather than recomputed from the init.

    Every member of a served cycle shares one init (F2 enforces it), so every member's
    ``valid_time`` at a step must agree. A disagreement means members from two different runs
    have been mixed, which no reader of the page could ever see, so it raises.
    """
    stamps = sorted({_iso(records[(cache_key, lead_h)]["valid_time"]) for cache_key in case_map})
    if len(stamps) != 1:
        raise ContractError(
            f"forecast: the members at lead {lead_h} h report different valid times {stamps}; "
            "every member of a served cycle comes from one init and must land on one instant"
        )
    return stamps[0]


# --------------------------------------------------------------------------- sections


def _build_rows(cycle: CycleResult, fitted: FittedWeights, case_map: dict[str, str]) -> list[dict]:
    """The §9 ``forecast`` array: fully covered steps of the served grid, ascending."""
    step_h = int(cycle.step_h)
    horizon_h = int(cycle.horizon_h)
    if step_h <= 0:
        raise ContractError(
            f"meta.step_h: must be a positive number of hours, got {step_h}; the step grid "
            "comes from the cycle that was fetched and is never assumed here"
        )
    if horizon_h <= 0:
        raise ContractError(
            f"meta.horizon_h: the cycle served no step at all (horizon_h={horizon_h}), so "
            "there is nothing to publish. An empty forecast renders an empty page and scores "
            "perfectly against nothing (SPEC §10)."
        )

    payload_names = list(case_map.values())
    covered = set(covered_leads(cycle.records))
    rows: list[dict] = []

    for lead_h in range(step_h, horizon_h + 1, step_h):
        if lead_h not in covered:
            continue

        members = _members_at(cycle.records, lead_h, case_map)
        weights, fitted_at_lead_h, extrapolated = weights_for_lead(lead_h, fitted)
        if set(weights) != set(payload_names):
            raise ContractError(
                f"forecast: the vector banded onto lead {lead_h} h carries {sorted(weights)} "
                f"but the payload publishes {sorted(payload_names)}; "
                f"{UNCHANGED_VECTOR_RULE}."
            )

        # Computed from the stored member values, in meta.models_included order, and left
        # unrounded — this is what makes §9 rule 6 an identity rather than a coincidence.
        blend_f = sum(weights[name] * members[name] for name in payload_names)

        rows.append(
            {
                "valid_time": _valid_time_at(cycle.records, lead_h, case_map),
                "lead_h": lead_h,
                "blend_f": blend_f,
                "weights": weights,
                "weights_fitted_at_lead_h": fitted_at_lead_h,
                "is_extrapolated_lead": extrapolated,
                "members": members,
                "member_spread_f": max(members.values()) - min(members.values()),
            }
        )

    return rows


def _build_gaps(cycle: CycleResult, case_map: dict[str, str]) -> list[dict]:
    """The §9 ``gaps`` array, translated from F2's lowercase report through the same map.

    ``cycle.gaps`` is already ``find_gaps(records, grid, horizon_h)``, so the grid is not
    re-derived here — one derivation, in the module that did the fetching.
    """
    gaps: list[dict] = []
    for gap in cycle.gaps:
        missing = set(gap["missing_models"])
        unknown = sorted(missing - set(case_map))
        if unknown:
            raise ContractError(
                f"gaps: the step at lead {gap['lead_h']} h names missing model(s) {unknown} "
                f"that are not in meta.models_included {sorted(case_map.values())}"
            )
        if not missing:
            raise ContractError(
                f"gaps: the step at lead {gap['lead_h']} h names no missing model; a step with "
                "every member present is a forecast row, not a gap"
            )
        gaps.append(
            {
                "valid_time": _iso(gap["valid_time"]),
                "lead_h": int(gap["lead_h"]),
                "missing_models": [
                    payload_name
                    for cache_key, payload_name in case_map.items()
                    if cache_key in missing
                ],
                "reason": gap["reason"],
            }
        )
    return gaps


def _build_meta(
    cycle: CycleResult,
    fitted: FittedWeights,
    generated_at: datetime,
    case_map: dict[str, str],
) -> dict:
    """The §9 ``meta`` block — the eight cycle keys and no more (D-F3-D)."""
    return {
        "site": copy.deepcopy(fitted.site),
        "variable": VARIABLE,
        "units": UNITS,
        "cycle": {
            "init_time": _iso(cycle.init_time),
            "run_label": cycle.run_label,
            "target_init_time": _iso(cycle.target_init_time),
            "fetched_at": _iso(cycle.fetched_at),
            "age_minutes": int(cycle.age_minutes),
            "is_stale": bool(cycle.is_stale),
            "stale_reason": cycle.stale_reason,
            "cycles_fallen_back": int(cycle.cycles_fallen_back),
        },
        "weights_source": copy.deepcopy(fitted.weights_source),
        "models_included": list(case_map.values()),
        "horizon_h": int(cycle.horizon_h),
        "step_h": int(cycle.step_h),
        "source": SOURCE,
        "generated_at": _iso(generated_at),
        "is_synthetic": False,
    }


# --------------------------------------------------------------------------- entry point


def build_forecast_document(
    cycle: CycleResult, fitted: FittedWeights, generated_at: datetime
) -> dict:
    """Assemble the FORECAST-SPEC §9 document and validate it before handing it back.

    Args:
        cycle: one fully resolved cycle from ``forecast.live`` — the served grid, the records
            and the gaps all come from here, never from a constant.
        fitted: the label-matched vectors and skill block from ``forecast.weights``.
        generated_at: an aware UTC instant, injected; this module reads no clock.

    Returns:
        The parsed document, already through :func:`forecast.contract.validate_forecast`.

    Raises:
        ContractError: the fetched member set is not the fitted one, a model key is
            unrecognised, a step reached the row builder with an incomplete member set, or the
            assembled document violates the §9 contract.
    """
    case_map = model_case_map(fitted.models_included)
    _check_record_models(cycle.records, case_map)

    document = {
        "meta": _build_meta(cycle, fitted, generated_at, case_map),
        "forecast": _build_rows(cycle, fitted, case_map),
        "gaps": _build_gaps(cycle, case_map),
        "skill": copy.deepcopy(fitted.skill),
    }

    validate_forecast(document)
    return document
