"""Build ``data/forecast_history.json`` — the FORECAST-SPEC §10 scored past view (F6, Stream 2).

``uv run --no-sync python -m forecast.history`` walks the whole path end to end::

    read parquets -> score.join.join_forecasts_to_obs -> pivot -> blend -> validate -> write

What this module publishes is the *record*: for every UTC date in the backtest archive, every
forecast step that found an observation within the match window, the fitted blend at that step,
what was actually observed, and the signed error between them.

**The two input parquets are symlinks into another checkout.** ``data/forecasts.parquet`` and
``data/obs.parquet`` point at another working copy's data directory, which another session owns
and is live in. They are therefore read with ``pandas.read_parquet`` and **nothing else**: no
write path in this module may ever target a ``.parquet``, and :func:`_refuse_parquet_target`
enforces that on the output path rather than trusting a reviewer to notice. A write through
those links would corrupt data this repository does not own.

Properties this module is required to hold
------------------------------------------

* **The join is imported, never mirrored.** :func:`score.join.join_forecasts_to_obs` already
  carries the +/-30 minute rule, the ``offset_min`` recorded on every matched row, the
  never-interpolate rule and the 80% per-group floor, all pinned by ``tests/test_join.py``. A
  local ``sort_values(["model", "valid_time"])`` before ``merge_asof`` looks right and is wrong
  (``score/join.py:111``) — one more reason a second copy of that logic must not exist here.
* **A date the join could not score is omitted, never scored.** ``score.join`` groups by
  ``(model, lead_h)`` and so can never see a calendar date at all. The omission is therefore
  computed here, from the **input** frame's dates minus the **matched** frame's dates, and each
  missing date lands in ``meta.omitted_days`` with :data:`OMITTED_DAY_REASON` and its counts.
  It is never emitted as a day carrying no entries and an MAE of zero: an empty join scores
  perfectly and is fake.
* **The fitted vector is label-matched.** It comes from
  :func:`forecast.weights.load_fitted_weights`, which locates the winner by
  ``winner.label`` — never ``blends[0]``, which is the out-of-sample leaderboard leader and a
  different vector at all three leads.
* **The comparison model is named in advance.** ``best_single_model_f`` is the member the
  backtest chose for that lead, read from ``results.json``. Picking whichever member landed
  closest on the day would read the observation before choosing.
* **Purity.** :func:`build_history_document` takes ``generated_at`` as an argument and reads no
  clock; :func:`now_utc` is called once, in :func:`main`.
* **No bare ``assert``** — ``python -O`` deletes assertions, so every guard raises.
"""

from __future__ import annotations

import argparse
import copy
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from forecast.build import SOURCE, model_case_map, repo_relative_source_path
from forecast.contract import UNITS, VARIABLE, ContractError, validate_history, write_atomic
from forecast.live import _iso
from forecast.weights import PRODUCED_BY, FittedWeights, load_fitted_weights
from score.join import TOLERANCE, join_forecasts_to_obs

__all__ = [
    "DEFAULT_FORECASTS_PATH",
    "DEFAULT_OBS_PATH",
    "DEFAULT_OUTPUT",
    "JOIN_TOLERANCE_MIN",
    "OMITTED_DAY_REASON",
    "RESULTS_PATH",
    "TEMPERATURE_DECIMALS",
    "build_history_document",
    "main",
    "match_forecasts",
    "now_utc",
    "read_forecasts",
    "read_observations",
    "temp_path_for",
]

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The backtest archive. A symlink into another checkout — read only, never written.
DEFAULT_FORECASTS_PATH = REPO_ROOT / "data" / "forecasts.parquet"

#: The observed truth. A symlink into another checkout — read only, never written.
DEFAULT_OBS_PATH = REPO_ROOT / "data" / "obs.parquet"

#: The backtest output the fitted weights come from, and the only source of them.
RESULTS_PATH = REPO_ROOT / "data" / "results.json"

#: Where the scored history lands. Committed, unlike ``data/forecast.json``.
DEFAULT_OUTPUT = REPO_ROOT / "data" / "forecast_history.json"

#: ``meta.join.tolerance_min``, derived from the join's own tolerance rather than typed here,
#: so the published window and the enforced window cannot drift apart.
JOIN_TOLERANCE_MIN = int(TOLERANCE.total_seconds() // 60)

#: Decimal places for every temperature the payload carries — members, blend, observed, the
#: comparison member, the signed error and the daily MAE. ``blend_f`` is computed from the
#: **stored, rounded** members, so the §10 blend identity holds by construction rather than by
#: luck (the ``forecast/build.py`` pattern, at the 2 dp §10 asks for).
TEMPERATURE_DECIMALS = 2

#: Decimal places for a published weight. The fitted grid step is 0.1 (SPEC §5).
WEIGHT_DECIMALS = 1

#: Decimal places for the join diagnostics, which are counts-derived rather than measured.
DIAGNOSTIC_DECIMALS = 4

#: The single sentence ``meta.omitted_days[].reason`` carries. Written **once**, here: the page
#: renders it verbatim in mono under the day card, so two spellings of it would be two different
#: explanations of the same fact.
OMITTED_DAY_REASON = (
    f"No observation fell within the +/-{JOIN_TOLERANCE_MIN} minute match window anywhere on "
    "this UTC date, so not one forecast step could be scored. Observations are never "
    "interpolated, resampled or carried forward: the date is dropped from the record and "
    "declared here instead."
)

#: The sentence every count guard in this module quotes. SPEC §10, and the reason the counts
#: are checked at all rather than trusted.
_FAKE_ZERO = "An empty join scores perfectly and is fake"

_FORECAST_COLUMNS = ("model", "init_time", "lead_h", "valid_time", "temp_f")
_OBS_COLUMNS = ("valid_time", "temp_f")


# --------------------------------------------------------------------------- clock and paths


def now_utc() -> datetime:
    """The single wall-clock reading in this module: an aware UTC instant.

    A named function, not an inline call, so a test can freeze the instant without touching
    ``datetime`` itself and without this module growing a ``--now`` flag.
    """
    return datetime.now(timezone.utc)


def temp_path_for(target: Path) -> Path:
    """The scratch file :func:`forecast.contract.write_atomic` writes through.

    A dotfile **beside** the target: ``os.replace`` is atomic only within one filesystem, so a
    scratch file elsewhere would turn the rename into a copy and reopen the torn-file window.
    """
    target = Path(target)
    return target.parent / f".{target.name}.tmp"


def _refuse_parquet_target(target: Path) -> None:
    """Refuse to write anything at a ``.parquet`` path.

    The two input parquets are symlinks into a working copy this repository does not own. A
    write through one of them would corrupt another session's data, so the output path is
    checked rather than assumed to be sane.
    """
    if Path(target).suffix.lower() == ".parquet":
        raise ContractError(
            f"refusing to write {target}: this module reads parquet and never writes it. The "
            "archive files are symlinks into another checkout, and a write through one of them "
            "would destroy data this repository does not own."
        )


# --------------------------------------------------------------------------- reading inputs


def _read_frame(path: str | Path, columns: tuple[str, ...], label: str) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        raise ContractError(
            f"missing input {target} ({label}). It is produced by: "
            "uv run --no-sync python -m fetch.backfill"
        )
    frame = pd.read_parquet(target)
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ContractError(
            f"{target} ({label}) is missing required column(s) {missing}; got "
            f"{list(frame.columns)}"
        )
    if frame.empty:
        raise ContractError(f"{target} ({label}) holds no rows. {_FAKE_ZERO} (SPEC §10)")
    return frame


def read_forecasts(path: str | Path = DEFAULT_FORECASTS_PATH) -> pd.DataFrame:
    """Read the backtest forecast archive. ``pandas.read_parquet``, read-only, no fallback."""
    return _read_frame(path, _FORECAST_COLUMNS, "the forecast archive")


def read_observations(path: str | Path = DEFAULT_OBS_PATH) -> pd.DataFrame:
    """Read the observed series. ``pandas.read_parquet``, read-only, no fallback."""
    return _read_frame(path, _OBS_COLUMNS, "the observed series")


# --------------------------------------------------------------------------- input guards


def _check_input_models(forecasts: pd.DataFrame, case_map: dict[str, str]) -> None:
    """Every ``model`` value in the archive must be one the payload knows how to name.

    ``case_map`` is explicit and total (``forecast/build.py:model_case_map``). There is no
    ``.get()`` with a default anywhere on this path: an unrecognised id would otherwise become
    a member the document never mentions, or a silently dropped one.
    """
    present = {str(value).strip().lower() for value in forecasts["model"]}
    unknown = sorted(present - set(case_map))
    if unknown:
        raise ContractError(
            f"forecasts.model: carries id(s) {unknown} that the fitted member set "
            f"{sorted(case_map.values())} cannot name. An unmapped id is never dropped and "
            "never guessed at — it would leave the document describing a blend over a "
            "different set of models."
        )
    absent = sorted(set(case_map) - present)
    if absent:
        raise ContractError(
            f"forecasts.model: the archive has no rows for {absent}, but the fitted vector "
            f"weights all of {sorted(case_map.values())}. A blend is never computed over the "
            "members that happened to be present."
        )


def _check_input_leads(forecasts: pd.DataFrame, fitted_leads: tuple[int, ...]) -> list[int]:
    """Every ``lead_h`` in the archive must be a lead the backtest actually fitted.

    The allowed set is :attr:`FittedWeights.fitted_leads` — derived from ``results.json``, never
    typed here. An archive lead with no fitted vector is a hard failure rather than a step
    quietly banded onto a neighbouring lead: the history is a record of what was fitted.
    """
    present = sorted({int(value) for value in forecasts["lead_h"]})
    unexpected = [lead for lead in present if lead not in set(fitted_leads)]
    if unexpected:
        raise ContractError(
            f"forecasts.lead_h: carries lead(s) {unexpected} that the backtest never fitted "
            f"(fitted leads: {list(fitted_leads)}). Such a step is never banded onto another "
            "lead's vector and never blended — a scored history entry uses the vector fitted "
            "at its own lead or it does not exist."
        )
    return present


def _check_offsets_are_whole_minutes(matched: pd.DataFrame) -> None:
    """``obs_offset_min`` is published as an integer, so a fractional offset must fail loudly.

    Rounding one would publish a match that sat somewhere other than where it is said to sit.
    Every offset in the real archive is a whole number of minutes.
    """
    offsets = matched["offset_min"].to_numpy(dtype=float)
    fractional = offsets[offsets != offsets.round()]
    if fractional.size:
        raise ContractError(
            f"{fractional.size} matched row(s) sit a fractional number of minutes from their "
            f"valid time (e.g. {float(fractional[0])!r}); obs_offset_min is published as an "
            "integer and is never rounded to make it fit — a rounded offset states a match "
            "that did not happen."
        )


# --------------------------------------------------------------------------- the join


def match_forecasts(
    forecasts: pd.DataFrame, obs: pd.DataFrame, fitted: FittedWeights
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Guard the inputs, then run the **imported** join. Returns ``(matched, stats)``.

    Nothing about the +/-30 minute rule, the never-interpolate rule or the 80% floor is
    re-implemented here; :func:`score.join.join_forecasts_to_obs` owns all three and is pinned
    by its own tests.
    """
    case_map = model_case_map(fitted.models_included)
    _check_input_models(forecasts, case_map)
    _check_input_leads(forecasts, fitted.fitted_leads)

    matched, stats = join_forecasts_to_obs(forecasts, obs)
    _check_offsets_are_whole_minutes(matched)

    payload_names = set(fitted.models_included)
    got = {str(name) for name in matched["model"]}
    if got != payload_names:
        raise ContractError(
            f"the join returned model names {sorted(got)} but the payload publishes "
            f"{sorted(payload_names)}; the casing bridge and the join must agree on one set "
            "of names or a member goes missing in translation"
        )
    return matched, stats


# --------------------------------------------------------------------------- the pivot


def _utc_date(moment) -> date:
    """The UTC calendar date a matched instant belongs to. UTC everywhere; no local zone."""
    return pd.Timestamp(moment).to_pydatetime().astimezone(timezone.utc).date()


def _collect_steps(matched: pd.DataFrame, payload_names: list[str]) -> dict:
    """Group matched rows into one step per ``(valid_time, lead_h, init_time)``.

    Returns ``{(valid_time, lead_h, init_time): {"members": {...}, "observed_f": float,
    "obs_offset_min": int}}``. Every model row for one step matched the same observation,
    because the join has no ``by=`` argument and the observations are one global series; that
    is checked here rather than assumed.
    """
    steps: dict[tuple[pd.Timestamp, int, pd.Timestamp], dict] = {}

    for row in matched.itertuples(index=False):
        key = (pd.Timestamp(row.valid_time), int(row.lead_h), pd.Timestamp(row.init_time))
        step = steps.setdefault(
            key,
            {"members": {}, "observed_f": float(row.obs_f), "obs_offset_min": int(row.offset_min)},
        )
        name = str(row.model)
        if name in step["members"]:
            raise ContractError(
                f"the archive carries two rows for {name} at {_iso(key[0])} / {key[1]} h; a "
                "duplicated member would let one model be counted twice inside the blend"
            )
        if float(row.obs_f) != step["observed_f"] or int(row.offset_min) != step["obs_offset_min"]:
            raise ContractError(
                f"the members of the step valid at {_iso(key[0])} / {key[1]} h matched "
                "different observations; the observed series is one global series and every "
                "member of a step is scored against the same reading"
            )
        step["members"][name] = float(row.temp_f)

    expected = set(payload_names)
    for key, step in steps.items():
        if set(step["members"]) != expected:
            missing = sorted(expected - set(step["members"]))
            raise ContractError(
                f"the step valid at {_iso(key[0])} / {key[1]} h is missing member(s) {missing}; "
                "it is never partially blended and the weights are never rescaled over a "
                "subset of models. An entry short of a member was never blended and belongs "
                "nowhere in this document."
            )
    return steps


def _build_entry(
    key: tuple[pd.Timestamp, int, pd.Timestamp],
    step: dict,
    payload_names: list[str],
    weights_by_lead: dict[str, dict[str, float]],
    best_by_lead: dict[str, str],
) -> dict:
    """One §10 ``days[].entries[]`` record — nine keys, three identities true by construction."""
    valid_time, lead_h, init_time = key
    lead_key = str(lead_h)

    members = {
        name: round(step["members"][name], TEMPERATURE_DECIMALS) for name in payload_names
    }
    weights = weights_by_lead[lead_key]

    # Computed from the STORED, rounded member values and in meta.models_included order — the
    # same values and the same order the validator recomputes from, which is what makes the
    # blend identity hold by construction instead of by luck.
    blend_f = round(
        sum(weights[name] * members[name] for name in payload_names), TEMPERATURE_DECIMALS
    )
    observed_f = round(step["observed_f"], TEMPERATURE_DECIMALS)

    # SIGNED. Positive means the blend ran warm that hour, negative means it ran cold. An
    # absolute value here would erase the bias the page exists to show.
    error_f = round(blend_f - observed_f, TEMPERATURE_DECIMALS)

    # The comparison member the backtest named in advance for this lead, never whichever member
    # happened to land closest on the day: picking after the fact reads the observation first.
    best_name = best_by_lead[lead_key]
    if best_name not in members:
        raise ContractError(
            f"meta.best_single_model_by_lead[{lead_key!r}] names {best_name!r}, which is not a "
            f"member of the step valid at {_iso(valid_time)} ({sorted(members)})"
        )

    return {
        "valid_time": _iso(valid_time),
        "init_time": _iso(init_time),
        "lead_h": int(lead_h),
        "blend_f": blend_f,
        "observed_f": observed_f,
        "error_f": error_f,
        "obs_offset_min": int(step["obs_offset_min"]),
        "members": members,
        "best_single_model_f": members[best_name],
    }


def _summarize_day(entries: list[dict]) -> tuple[dict[str, float], dict[str, int]]:
    """``mae_f`` and ``n_by_lead`` over **this day's** entries only.

    Both are keyed by the leads present that day, never by ``meta.leads_available``: the two
    partial days at the edges of the window match at only some leads, and padding the summary
    out to the full lead list would invent an MAE for a lead with no entries — a zero that
    reads like a perfect forecast.
    """
    errors: dict[int, list[float]] = {}
    for entry in entries:
        errors.setdefault(int(entry["lead_h"]), []).append(float(entry["error_f"]))

    mae_f: dict[str, float] = {}
    n_by_lead: dict[str, int] = {}
    for lead in sorted(errors):
        values = errors[lead]
        if not values:
            raise ContractError(
                f"lead {lead} h was recorded for a day with no entries at that lead. "
                f"{_FAKE_ZERO} (SPEC §10)"
            )
        mae_f[str(lead)] = round(
            sum(abs(value) for value in values) / len(values), TEMPERATURE_DECIMALS
        )
        n_by_lead[str(lead)] = len(values)
    return mae_f, n_by_lead


# --------------------------------------------------------------------------- the omission


def _omitted_days(forecasts: pd.DataFrame, matched: pd.DataFrame) -> list[dict]:
    """The §10 ``meta.omitted_days`` array: dates offered to the join that it could not score.

    **This is the mechanism the ticket exists for.** ``score.join`` groups by
    ``(model, lead_h)`` and can never see a calendar date, so a date on which every observation
    sat outside the match window survives its 80% floor untouched and simply vanishes from the
    matched frame. Computing ``dates_in - dates_out`` — the **input** frame against the
    **matched** frame — is the only place that disappearance can be noticed and declared.

    A date listed here is absent from ``days``. It is never emitted as a day with no entries and
    an MAE of zero.
    """
    dates_in = sorted({_utc_date(value) for value in forecasts["valid_time"]})
    dates_out = {_utc_date(value) for value in matched["valid_time"]}

    omitted: list[dict] = []
    for day in dates_in:
        if day in dates_out:
            continue
        n_forecast_rows = int(
            sum(1 for value in forecasts["valid_time"] if _utc_date(value) == day)
        )
        n_matched_rows = int(sum(1 for value in matched["valid_time"] if _utc_date(value) == day))
        if n_matched_rows != 0:
            raise ContractError(
                f"{day.isoformat()} is absent from the matched dates yet carries "
                f"{n_matched_rows} matched row(s); a date is scored or omitted, never both"
            )
        if n_forecast_rows == 0:
            raise ContractError(
                f"{day.isoformat()} was derived from the forecast archive yet carries no "
                f"forecast rows in it. {_FAKE_ZERO} (SPEC §10)"
            )
        omitted.append(
            {
                "date": day.isoformat(),
                "reason": OMITTED_DAY_REASON,
                "n_forecast_rows": n_forecast_rows,
                "n_matched_rows": n_matched_rows,
            }
        )
    return omitted


# --------------------------------------------------------------------------- provenance


def _join_block(
    forecasts: pd.DataFrame, matched: pd.DataFrame, stats: pd.DataFrame
) -> dict:
    """``meta.join`` — the match stated in the payload rather than left to be trusted."""
    n_forecast_rows = int(stats["n_forecast"].sum())
    n_matched_rows = int(stats["n_matched"].sum())
    if n_forecast_rows != len(forecasts) or n_matched_rows != len(matched):
        raise ContractError(
            f"the join diagnostics report {n_matched_rows} of {n_forecast_rows} rows, but the "
            f"frames hold {len(matched)} of {len(forecasts)}; the published counts are the "
            f"join's own or they are decoration. {_FAKE_ZERO} (SPEC §10)"
        )

    offsets = matched["offset_min"].abs().to_numpy(dtype=float)
    mean_abs_offset_min = float(offsets.mean())

    # The same number the other way round: the per-group means from `score.join`, weighted by
    # the rows behind each. Two derivations that disagree mean one of them is not measuring the
    # join that produced these entries.
    weighted = float(
        (stats["mean_abs_offset_min"] * stats["n_matched"]).sum() / stats["n_matched"].sum()
    )
    if abs(weighted - mean_abs_offset_min) > 1e-6:
        raise ContractError(
            f"mean absolute observation offset is {mean_abs_offset_min!r} over the matched rows "
            f"but {weighted!r} across the join's per-group diagnostics; the payload never "
            "publishes a figure the join itself does not report"
        )

    return {
        "tolerance_min": JOIN_TOLERANCE_MIN,
        "n_forecast_rows": n_forecast_rows,
        "n_matched_rows": n_matched_rows,
        "matched_pct": round(100.0 * n_matched_rows / n_forecast_rows, DIAGNOSTIC_DECIMALS),
        "mean_abs_offset_min": round(mean_abs_offset_min, DIAGNOSTIC_DECIMALS),
    }


def _weights_by_lead(fitted: FittedWeights, leads: list[int], names: list[str]) -> dict:
    """The fitted vector published at every lead, keyed ``"6"`` / ``"12"`` / ``"24"``.

    It is the only way a reader can check the ``blend_f`` identity from the document alone, so
    it is the vector as fitted — nothing here adjusts, redistributes or rescales it.
    """
    published: dict[str, dict[str, float]] = {}
    for lead in leads:
        vector = fitted.vectors.get(lead)
        if vector is None:
            raise ContractError(
                f"no fitted vector was loaded for {lead} h (loaded: {sorted(fitted.vectors)}); "
                "no vector is synthesized to cover the hole, and the weights are never rescaled "
                "over a subset of models"
            )
        if set(vector) != set(names):
            raise ContractError(
                f"the vector fitted at {lead} h carries {sorted(vector)} but the payload "
                f"publishes {sorted(names)}; a blend over a different set of models is a "
                "different blend"
            )
        published[str(lead)] = {name: round(float(vector[name]), WEIGHT_DECIMALS) for name in names}
    return published


def _best_single_by_lead(fitted: FittedWeights, leads: list[int], names: list[str]) -> dict:
    """``meta.best_single_model_by_lead`` — the comparison model the backtest named per lead.

    Read from ``results.json`` by way of ``FittedWeights.skill``, so the name varies with the
    lead exactly as the backtest recorded it. It is never a constant written here.
    """
    by_lead = {int(entry["lead_h"]): str(entry["best_single_model"]) for entry in fitted.skill["by_lead"]}
    published: dict[str, str] = {}
    for lead in leads:
        name = by_lead.get(lead)
        if name is None:
            raise ContractError(
                f"the backtest names no best single model at {lead} h (it names them at "
                f"{sorted(by_lead)}); the comparison model is read from results.json and is "
                "never assumed"
            )
        if name not in names:
            raise ContractError(
                f"the backtest names {name!r} as the best single model at {lead} h, which is "
                f"not one of the published members {sorted(names)}"
            )
        published[str(lead)] = name
    return published


# --------------------------------------------------------------------------- the document


def build_history_document(
    forecasts: pd.DataFrame,
    obs: pd.DataFrame,
    fitted: FittedWeights,
    *,
    generated_at: datetime,
) -> dict:
    """Assemble the FORECAST-SPEC §10 history document. **Pure**: it reads no clock.

    Args:
        forecasts: the backtest archive, as read from ``data/forecasts.parquet``.
        obs: the observed series, as read from ``data/obs.parquet``.
        fitted: the label-matched vectors from :func:`forecast.weights.load_fitted_weights`.
        generated_at: an aware UTC instant, injected by the caller.

    Raises:
        ContractError: any input guard fails, or the assembled document violates §10.
    """
    if generated_at.tzinfo is None:
        raise ContractError(
            "generated_at: is a naive datetime; this function reads no wall clock and requires "
            "an aware UTC instant from its caller (UTC everywhere)"
        )

    payload_names = list(fitted.models_included)
    matched, stats = match_forecasts(forecasts, obs, fitted)

    # leads_available is DERIVED from what actually matched, never typed as a literal.
    leads_available = sorted({int(value) for value in matched["lead_h"]})
    if not leads_available:
        raise ContractError(f"no lead survived the join. {_FAKE_ZERO} (SPEC §10)")

    weights_by_lead = _weights_by_lead(fitted, leads_available, payload_names)
    best_by_lead = _best_single_by_lead(fitted, leads_available, payload_names)

    steps = _collect_steps(matched, payload_names)

    # `days` is built ONLY from the dates that survived the join. A date that matched nothing is
    # never reached from here; it is declared in meta.omitted_days instead.
    by_date: dict[date, list[dict]] = {}
    for key in sorted(steps, key=lambda item: (item[0], item[1])):
        entry = _build_entry(key, steps[key], payload_names, weights_by_lead, best_by_lead)
        by_date.setdefault(_utc_date(key[0]), []).append(entry)

    days: list[dict] = []
    for day in sorted(by_date):
        entries = by_date[day]
        mae_f, n_by_lead = _summarize_day(entries)
        days.append(
            {"date": day.isoformat(), "entries": entries, "mae_f": mae_f, "n_by_lead": n_by_lead}
        )

    join_block = _join_block(forecasts, matched, stats)

    # The count guard, stated rather than trusted: every emitted entry stands for exactly one
    # matched row per member, so the two numbers are the same fact counted two ways.
    n_entries = sum(len(day["entries"]) for day in days)
    expected_rows = n_entries * len(payload_names)
    if expected_rows != join_block["n_matched_rows"]:
        raise ContractError(
            f"{n_entries} emitted entries over {len(payload_names)} members account for "
            f"{expected_rows} matched rows, but the join matched "
            f"{join_block['n_matched_rows']}. {_FAKE_ZERO} (SPEC §10) — a document whose "
            "entries do not account for its matched rows is scoring something it does not show."
        )

    weights_source = copy.deepcopy(fitted.weights_source)
    # Repo-relative: an absolute path prints the operator's home directory onto a page whose
    # audience is a customer, and makes two correct runs differ byte for byte.
    weights_source["path"] = repo_relative_source_path(str(weights_source["path"]))

    document = {
        "meta": {
            "site": copy.deepcopy(fitted.site),
            "variable": VARIABLE,
            "units": UNITS,
            # Copied verbatim from results.json: the window the weights were fitted on. It is
            # NOT len(days) — the archive's UTC dates include two partial days at the edges.
            "window": copy.deepcopy(fitted.weights_source["window"]),
            "leads_available": leads_available,
            "weights_source": weights_source,
            "generated_at": _iso(generated_at),
            "is_synthetic": False,
            "models_included": list(payload_names),
            "weights_by_lead": weights_by_lead,
            "best_single_model_by_lead": best_by_lead,
            "join": join_block,
            "omitted_days": _omitted_days(forecasts, matched),
            "source": SOURCE,
        },
        "days": days,
    }

    # Validate on the way out, so a malformed document never reaches a caller.
    validate_history(document)
    return document


# --------------------------------------------------------------------------- the CLI

EXIT_OK = 0
EXIT_CONTRACT = 1
EXIT_NO_WEIGHTS = 2
EXIT_NO_INPUT = 3


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """The whole flag surface: the three inputs and the output, and deliberately not a fifth.

    In particular there is no flag that trims the window, drops a lead or excludes a date.
    Reshaping the sample until the numbers read better is exactly the tuning SPEC §10 bans.
    """
    parser = argparse.ArgumentParser(
        prog="python -m forecast.history",
        description=(
            "Build data/forecast_history.json: the backtest archive joined to the observed "
            "series and scored through the fitted blend, day by day."
        ),
    )
    parser.add_argument("--forecasts", default=str(DEFAULT_FORECASTS_PATH), help="forecast archive")
    parser.add_argument("--obs", default=str(DEFAULT_OBS_PATH), help="observed series")
    parser.add_argument("--results", default=str(RESULTS_PATH), help="backtest output")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="where the document lands")
    return parser.parse_args(argv)


def _print_run(document: dict, out: Path) -> None:
    meta = document["meta"]
    join = meta["join"]
    days = document["days"]
    n_entries = sum(len(day["entries"]) for day in days)

    print(f"wrote {out}")
    print(
        f"  days={len(days)}  entries={n_entries}  omitted_days={len(meta['omitted_days'])}  "
        f"leads_available={meta['leads_available']}"
    )
    print(
        f"  join: {join['n_matched_rows']}/{join['n_forecast_rows']} matched "
        f"({join['matched_pct']}%)  mean_abs_offset_min={join['mean_abs_offset_min']}  "
        f"tolerance_min={join['tolerance_min']}"
    )
    for lead in meta["leads_available"]:
        key = str(lead)
        errors = [
            abs(float(entry["error_f"]))
            for day in days
            for entry in day["entries"]
            if int(entry["lead_h"]) == lead
        ]
        vector = " / ".join(
            f"{name} {meta['weights_by_lead'][key][name]}" for name in meta["models_included"]
        )
        print(
            f"  lead {lead:>2} h: n={len(errors)}  mae_f={sum(errors) / len(errors):.4f}  "
            f"best_single={meta['best_single_model_by_lead'][key]}  weights=[{vector}]"
        )
    print(
        f"  weights={meta['weights_source']['path']}  source={meta['source']}  "
        f"is_synthetic={meta['is_synthetic']}"
    )


def main(argv: list[str] | None = None) -> int:
    """Build and write the history document. ``0`` on success, non-zero on a named failure."""
    args = _parse_args(argv)
    out = Path(args.out)
    _refuse_parquet_target(out)

    # The one wall-clock reading in this module, threaded through from here.
    now = now_utc()

    try:
        fitted = load_fitted_weights(Path(args.results), now)
    except ContractError as exc:
        print(f"REFUSING TO BUILD: the fitted weights could not be read from {args.results}")
        print(f"  {exc}")
        print(f"  They are produced by: {PRODUCED_BY}")
        return EXIT_NO_WEIGHTS

    try:
        forecasts = read_forecasts(args.forecasts)
        obs = read_observations(args.obs)
    except ContractError as exc:
        print("REFUSING TO BUILD: an input could not be read")
        print(f"  {exc}")
        return EXIT_NO_INPUT

    try:
        document = build_history_document(forecasts, obs, fitted, generated_at=now)
    except ContractError as exc:
        print(f"REFUSING TO WRITE: {out}")
        print(f"  the assembled document violates the FORECAST-SPEC §10 contract: {exc}")
        return EXIT_CONTRACT

    try:
        write_atomic(document, out, tmp=temp_path_for(out), validator=validate_history)
    except ContractError as exc:
        print(f"REFUSING TO WRITE: {out}")
        print(f"  the assembled document violates the FORECAST-SPEC §10 contract: {exc}")
        return EXIT_CONTRACT

    _print_run(document, out)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
