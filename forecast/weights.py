"""Read the fitted blend weights out of ``data/results.json`` — **by label, never by index**.

``data/results.json`` is the backtest's output and this module's only input. It is
read-only here: nothing in ``forecast/`` ever rewrites it, and nothing here refits.

The one thing this module exists to get right
---------------------------------------------

``results["<lead>"].blends`` is sorted by **out-of-sample** MAE. The blend the backtest
actually chose is the one that minimised error on the **training** split, and it is named
by ``results["<lead>"].winner.label``. Those are different rows. In the real file the
fitted winner sits at leaderboard rank 5 / 23 / 5 at 6 / 12 / 24 h, and ``blends[0]`` is a
different weight vector at **every** lead. Taking ``blends[0]`` would therefore publish a
vector selected with knowledge of the test set — look-ahead bias — and it would do so
silently, because the resulting document is perfectly well formed.

So the fitted vector is found by matching ``winner.label`` against ``blends[].label``, the
match count must be exactly one, and a count of anything else **raises**. There is no
fallback to index 0, here or anywhere downstream.

The label is matched, never parsed: labels omit zero-weight models (``"HRRR 50 / NAM 10 /
NBM 40"`` never mentions GFS) and a pure corner reads ``"HRRR only"``, so the weights come
from the matched blend's ``weights`` object and from nowhere else.

Nesting, verified against the real file: the top level is ``{"meta", "lead_times",
"results"}``; the per-lead objects live at ``doc["results"]["6"]`` under **string** keys
while ``doc["lead_times"]`` holds **integers**. ``winner`` carries exactly ``{label,
mae_out_of_sample, improvement_pct_vs_best_single}`` and has **no** ``mae_in_sample``,
which is why ``blend_mae_in_sample`` is read off the label-matched blend instead.

Design rules
------------

* **No fallback, by design** (FORECAST-SPEC §16 R3). A missing file, invalid JSON or a
  contract violation propagates with its reason. This module catches nothing and
  substitutes nothing: no default vector, no equal-weight stand-in, ever.
* **Pure.** ``now`` is injected. This module never reads a wall clock, never opens a
  socket, and reads exactly the one path it is handed.
* **Standard library**, plus ``backend.contract`` (the ``results.json`` validator) and
  ``forecast.contract`` (the §7 banding rule, whose single implementation lives there —
  D-F3-A; two copies would let the builder and the validator agree on a shared mistake).
* **No bare ``assert``**: ``python -O`` deletes assertions, so every guard raises.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from backend.contract import ContractError, load_and_validate
from forecast.contract import band_for_lead, is_extrapolated_lead

__all__ = [
    "FittedWeights",
    "PRODUCED_BY",
    "SKILL_BASIS",
    "SKILL_NOTE",
    "UNCHANGED_VECTOR_RULE",
    "load_fitted_weights",
    "select_winner_blend",
    "skill_entry",
    "weights_for_lead",
]

#: FORECAST-SPEC §9 ``skill.basis``. The numbers are historical, out-of-sample, past tense.
SKILL_BASIS = "historical_out_of_sample"

#: FORECAST-SPEC §9 ``skill.note``, verbatim. It is the sentence that stops a reader from
#: mistaking a backtest MAE for an error bar on tomorrow's temperature.
SKILL_NOTE = (
    "Measured over the 30-day backtest window. History, not a prediction about this forecast."
)

#: What produces ``data/results.json``. Named in the "missing input" raise, in the style of
#: ``score/run.py:_require``, so a fresh clone gets an instruction rather than a traceback.
PRODUCED_BY = "uv run --no-sync python -m score.run"

#: The invariant :func:`weights_for_lead` upholds, quoted in its guard message.
UNCHANGED_VECTOR_RULE = "weights are never rescaled over a subset of models"


@dataclass(frozen=True)
class FittedWeights:
    """Everything the payload needs from ``results.json``, detached from the loaded document.

    Every field is a copy, so a caller that mutates what it gets back cannot reach into the
    parsed ``results.json`` and change what a later reader sees.

    Attributes:
        vectors: ``{fitted_lead: {UPPERCASE_MODEL: weight}}`` — the label-matched vectors.
        fitted_leads: the leads the backtest actually fitted, ascending.
        models_included: ``meta.models_included``, UPPERCASE, in file order.
        site: ``meta.site``, copied verbatim into ``meta.site`` of the payload.
        weights_source: the FORECAST-SPEC §7.1 block — exactly ``path``, ``generated_at``,
            ``weights_age_days``, ``window``, ``split``, ``fitted_leads``.
        skill: the §9 block — exactly ``basis``, ``window``, ``note``, ``by_lead``.
    """

    vectors: dict[int, dict[str, float]]
    fitted_leads: tuple[int, ...]
    models_included: tuple[str, ...]
    site: dict
    weights_source: dict
    skill: dict


# --------------------------------------------------------------------------- primitives


def _require_results_file(target: Path) -> None:
    """A fresh clone has no backtest output. Say so, and say what makes it."""
    if not target.exists():
        raise ContractError(
            f"missing input {target}\n"
            f"  It is produced by: {PRODUCED_BY}\n"
            "  The fitted weights come from the backtest and from nowhere else. There is no "
            "fallback by design (FORECAST-SPEC §16 R3): this module never substitutes a "
            "default vector, never falls back to equal weights, and never publishes a blend "
            "that nobody ever fitted."
        )


def _instant(text: object, path: str) -> datetime:
    """Parse an ISO8601 UTC stamp into an aware datetime. UTC everywhere; no local clock."""
    if not isinstance(text, str):
        raise ContractError(f"{path}: expected an ISO8601 string, got {type(text).__name__}")
    body = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(body)
    except ValueError as exc:
        raise ContractError(f"{path}: is not a parseable ISO8601 timestamp ({exc}): {text!r}") from exc
    if parsed.tzinfo is None:
        raise ContractError(
            f"{path}: {text!r} has no UTC offset; every instant in this pipeline is aware and "
            "in UTC, and a naive stamp would make the weight age depend on the reader's zone"
        )
    return parsed


def _weights_age_days(generated_at: datetime, now: datetime, target: Path) -> int:
    """Whole days (floor) from the backtest's ``generated_at`` to the injected ``now``.

    FORECAST-SPEC §7.1: the page names this number and warns above 45 days, because weights
    fitted on 30 days of August have no claim on December. A **negative** age is not a young
    file — it means the clock or the document is wrong, and quietly clamping it to zero would
    hide exactly that, so it raises.
    """
    if not isinstance(now, datetime):
        raise ContractError(f"now: expected a datetime, got {type(now).__name__}")
    if now.tzinfo is None:
        raise ContractError(
            "now: is a naive datetime; this module never reads a wall clock and requires an "
            "aware UTC instant from its caller (UTC everywhere)"
        )
    elapsed = now - generated_at
    if elapsed < timedelta(0):
        raise ContractError(
            f"meta.generated_at: {target} was generated at {generated_at.isoformat()}, which is "
            f"after the supplied now ({now.isoformat()}). A negative weight age means the clock "
            "or the file is wrong; it is never treated as zero."
        )
    return elapsed.days


# --------------------------------------------------------------------------- label match


def select_winner_blend(lead_h: int, lead_result: Mapping) -> dict:
    """Return the single ``blends[]`` entry whose ``label`` equals ``winner.label``.

    **This is the anti-look-ahead guard.** ``blends[]`` is ranked by out-of-sample error, so
    ``blends[0]`` is the leaderboard leader — in the real file a different weight vector from
    the fitted winner at all three leads. A count other than one raises rather than falling
    back to a position, because a fallback here would ship a look-ahead-biased blend that
    looks entirely well formed on the page.
    """
    winner = lead_result["winner"]
    label = winner["label"]
    blends = lead_result["blends"]
    matched = [entry for entry in blends if entry.get("label") == label]
    if len(matched) != 1:
        raise ContractError(
            f'results["{lead_h}"].winner.label: {label!r} matches {len(matched)} entries of '
            f'results["{lead_h}"].blends, expected exactly 1. The fitted vector is located by '
            "label and never by position — blends[] is sorted by OUT-OF-SAMPLE error, so "
            "blends[0] is the leaderboard leader rather than the blend the training split "
            "chose. There is no fall back to index 0 (FORECAST-SPEC §7, §16 R3)."
        )
    return dict(matched[0])


def skill_entry(lead_h: int, lead_result: Mapping, independent_days_approx: int) -> dict:
    """Build one FORECAST-SPEC §9 ``skill.by_lead[]`` entry — exactly eight keys.

    Two of these are easy to get wrong:

    * ``blend_mae_in_sample`` comes from the **label-matched blend**. The ``winner`` object
      carries only ``{label, mae_out_of_sample, improvement_pct_vs_best_single}`` and has no
      in-sample field at all.
    * ``improvement_pct`` is passed through **exactly as the backtest recorded it**, sign and
      all. Zero and negative are legitimate results and are published as such (SPEC §10); the
      page reports what the data says and never demands a win.

    ``independent_days_approx`` is a **named derivation, not a coincidence**: it is
    ``meta.window.days``, the number of *days* the backtest window spans, not the number of
    joined samples. README caveat C2 is the reason — four init runs a day at one site give
    roughly 30 independent-ish days, not 120 independent observations, and quoting the sample
    count here would overstate the evidence behind every MAE on the page.
    """
    winner = lead_result["winner"]
    blend = select_winner_blend(lead_h, lead_result)
    best_single = lead_result["best_single_model"]
    return {
        "lead_h": int(lead_h),
        "blend_mae": float(winner["mae_out_of_sample"]),
        "blend_mae_in_sample": float(blend["mae_in_sample"]),
        "best_single_model": str(best_single["model"]),
        "best_single_mae": float(best_single["mae_out_of_sample"]),
        "improvement_pct": float(winner["improvement_pct_vs_best_single"]),
        "n_test": int(lead_result["n_samples"]["test"]),
        "independent_days_approx": int(independent_days_approx),
    }


# --------------------------------------------------------------------------- entry points


def load_fitted_weights(results_path: str | Path, now: datetime) -> FittedWeights:
    """Load ``results.json`` and extract the fitted weight vector for every fitted lead.

    The document is validated by :func:`backend.contract.load_and_validate` first, so a
    malformed or contract-violating file fails here with its own reason attached. Nothing is
    caught and nothing is substituted: on any failure this function raises and **no vector is
    returned at all** (FORECAST-SPEC §16 R3).

    Args:
        results_path: the backtest output to read. Never written.
        now: an aware UTC instant, injected — this module reads no clock.

    Raises:
        ContractError: the file is absent (the raise names what produces it), is not valid
            JSON, violates the ``results.json`` contract, has a ``winner.label`` that does not
            identify exactly one blend, or reports a ``generated_at`` later than ``now``.
    """
    target = Path(results_path)
    _require_results_file(target)
    doc = load_and_validate(target)

    meta = doc["meta"]
    generated_at = _instant(meta["generated_at"], "meta.generated_at")
    age_days = _weights_age_days(generated_at, now, target)

    models = tuple(str(name) for name in meta["models_included"])
    window_days = int(meta["window"]["days"])
    fitted_leads = tuple(sorted(int(lead) for lead in doc["lead_times"]))
    results = doc["results"]

    vectors: dict[int, dict[str, float]] = {}
    by_lead: list[dict] = []
    for lead in fitted_leads:
        lead_result = results[str(lead)]
        blend = select_winner_blend(lead, lead_result)
        weights = blend["weights"]
        if set(weights) != set(models):
            raise ContractError(
                f'results["{lead}"].blends[].weights: keys are {sorted(weights)} but '
                f"meta.models_included is {sorted(models)}; the fitted vector must carry a "
                f"weight for every model, and {UNCHANGED_VECTOR_RULE}"
            )
        vectors[lead] = {model: float(weights[model]) for model in models}
        by_lead.append(skill_entry(lead, lead_result, window_days))

    weights_source = {
        "path": str(target),
        "generated_at": str(meta["generated_at"]),
        "weights_age_days": age_days,
        "window": copy.deepcopy(meta["window"]),
        "split": copy.deepcopy(meta["split"]),
        "fitted_leads": list(fitted_leads),
    }
    skill = {
        "basis": SKILL_BASIS,
        "window": copy.deepcopy(meta["window"]),
        "note": SKILL_NOTE,
        "by_lead": by_lead,
    }

    return FittedWeights(
        vectors=vectors,
        fitted_leads=fitted_leads,
        models_included=models,
        site=copy.deepcopy(meta["site"]),
        weights_source=weights_source,
        skill=skill,
    )


def weights_for_lead(lead_h: int, fitted: FittedWeights) -> tuple[dict[str, float], int, bool]:
    """Map a forecast lead onto the fitted vector it must use.

    Returns ``(vector, weights_fitted_at_lead_h, is_extrapolated_lead)``.

    The banding rule — nearest fitted lead by absolute difference, **ties to the shorter
    lead** — lives once, in :func:`forecast.contract.band_for_lead`, and is imported rather
    than repeated (D-F3-A). ``is_extrapolated_lead`` likewise derives its boundary from
    ``fitted_leads``, never from the literal 24, so refitting at different leads moves the
    unverified region automatically.

    The vector comes back **exactly as it was fitted**: nothing here reweights, redistributes
    or otherwise adjusts it, and in particular the weights are never rescaled over a subset of models. When a member is missing at a step the
    step becomes a declared gap, because rescaling the survivors would publish a blend that
    was never fitted while looking entirely ordinary on the page.
    """
    band = band_for_lead(lead_h, fitted.fitted_leads)
    vector = fitted.vectors.get(band)
    if vector is None:
        raise ContractError(
            f"weights_for_lead: a {lead_h} h lead bands onto the {band} h fitted vector, but "
            f"no vector was loaded for {band} h (loaded: {sorted(fitted.vectors)}). No vector "
            f"is synthesized to cover the hole, and {UNCHANGED_VECTOR_RULE}."
        )
    return dict(vector), band, is_extrapolated_lead(lead_h, fitted.fitted_leads)
