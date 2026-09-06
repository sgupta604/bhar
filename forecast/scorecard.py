"""The F9 forecast scorecard — a forward-validated record of realized error.

What this module is
-------------------

The forward page (F4) publishes a blend for the next 48 hours. This module writes that
blend, and every member beside it, **down before the outcome exists**, then comes back
later and records what was actually observed. The result is not a backtest: nothing here
can be re-fitted, re-chosen or re-graded after the fact, because the prediction line was
already on disk when the observation was taken.

Three layers, and the boundary between them is the whole design
---------------------------------------------------------------

**(a) The ledger** — ``data/forecast_ledger.jsonl``, committed, **append-only**. One
complete JSON object per line, appended in ``"a"`` mode, flushed, under a module-level
lock. Mirrors ``fetch/backfill.py:154-193``. No code path in this module ever opens the
ledger in a mode that shortens it, and a source scan with a positive control proves it.
An atomic-replace helper is the right tool for ``data/forecast.json`` and the **wrong**
tool here: replacing a file *is* discarding what it held, and the point of this file is
that nothing already written to it can be taken back.

**(b) The impure passes** — ``record()`` reads ``data/forecast.json`` and appends one
prediction row per (step, series); ``grade()`` reads observations behind exactly **one**
bounded request and appends grade rows. They touch the clock, the disk and the network by
nature, and they are the only things here that do. Every failure either becomes a stated
skip that the payload carries, or — for the one failure that must never be smoothed over,
a join that was offered rows and matched none of them — an exception.

**(c) The pure function** — :func:`scorecard`. It reads **nothing but its arguments**: no
network, no disk, no clock. ``now`` and the static ``meta`` block are injected. Same rows
in, byte-identical JSON out. Both the CLI and the endpoint reach it through the same
composer, so the number an operator sees at a terminal is the number the page renders.

The purity boundary, stated so it can be tested
-----------------------------------------------

``recorded_at`` / ``graded_at`` are stamped by the passes, above the boundary. Below it,
:data:`PURE_FUNCTION_NAMES` enumerates every function :func:`scorecard` relies on, and a
test scans their source (with a positive control) for ``datetime.now``, ``utcnow``,
``time.time``, ``time.monotonic``, ``open(``, ``Path(`` and ``requests``. If a helper
below the line ever grows a clock, that test goes red rather than the output going
quietly non-reproducible.

Conventions this module holds to
--------------------------------

* **UTC everywhere**, ISO-8601 with a trailing ``Z`` — never ``+00:00``
  (``fetch/backfill.py:90`` house style).
* **Degrees F at the boundary.** Nothing here sees Kelvin.
* **Signed ``error_f``** (``forecast_f − observed_f``), matching ``forecast/history.py``'s
  §10 convention, so bias is visible; ``abs_error_f`` is carried beside it so no consumer
  re-derives it and no two consumers derive it differently.
* **Every mean carries its own ``n``.** A statistic over zero rows is ``None``, never
  ``0.0`` — an empty mean scores perfectly and is fake (SPEC §10).
* **Gap rows are excluded from every mean**, and counted separately.
* **No smoothing of any kind.** No rolling window, no EMA, no moving average. The record
  is short; smoothing a short record manufactures a trend that is not in it.
* **No bare ``assert``.** ``python -O`` deletes assertions, and this module decides what
  the page claims about the blend's realized skill, so every guard raises.

Two comparisons that are deliberately harsh, and are not accidents
------------------------------------------------------------------

``best_single_model`` is the member with the **lowest realized error in hindsight** on the
compared steps. Nobody could have picked it in advance, and the payload never claims
otherwise: it is the hardest available comparator, chosen so a "the blend won" line can
never be an artifact of a soft baseline.

``blend_beaten`` is computed on the **same steps** for the blend and for every member. A
mean over one set of steps compared against a mean over a different set is not a
comparison, so where the sets differ the excluded rows are counted and stated in
``skips`` rather than quietly averaged in.

The locked scorecard ``meta`` key set (Stream 5 codes against this verbatim)
---------------------------------------------------------------------------

``generated_at``, ``site``, ``variable``, ``units``, ``obs_source``, ``tolerance_min``,
``never_interpolated``, ``models_included``, ``lead_hours``, ``counts``, ``window``,
``weights_fitted_window``.

``models_included`` and ``lead_hours`` both sit **directly under ``meta``**, not under
``meta.window``: the frontend iterates the first (it is forbidden from typing a model
name) and names the leads from the second (it is forbidden from typing a bare ``16``).
They are the two lists the copy reads, so they live together, and this placement is
stable — Streams 2-5 depend on it.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from fetch.obs import fetch_obs
from forecast.contract import (
    BANNED_FIELD_NAMES,
    UNITS,
    VARIABLE,
    ContractError,
    load_and_validate_forecast,
)
from score.build import SITE
from score.join import TOLERANCE as _JOIN_TOLERANCE
from score.join import join_forecasts_to_obs

__all__ = [
    "ScorecardError",
    "LEDGER_PATH",
    "FORECAST_PATH",
    "HTTP_TIMEOUT",
    "GRADE_DEADLINE_S",
    "GAP_GRACE_H",
    "MAX_OBS_WINDOW_DAYS",
    "OBS_SOURCE",
    "TOLERANCE_MIN",
    "MIN_CYCLES_FOR_ENOUGH",
    "BLEND_SERIES",
    "SERIES_KINDS",
    "GRADE_STATUSES",
    "PREDICTION_FIELDS",
    "GRADE_FIELDS",
    "PURE_FUNCTION_NAMES",
    "row_identity",
    "series_identity",
    "step_identity",
    "make_prediction_row",
    "make_grade_row",
    "append_ledger",
    "load_ledger",
    "dedupe",
    "has_identity",
    "ledger_meta",
    "streaks",
    "scorecard",
    "validate_scorecard",
    "OUTSIDE_WINDOW_REASON",
    "RESULTS_PATH",
    "EXIT_OK",
    "EXIT_CONTRACT",
    "EXIT_NO_PASS_SELECTED",
    "EXIT_EMPTY_JOIN",
    "now_utc",
    "record",
    "grade",
    "observation_window",
    "weights_fitted_window",
    "serve_scorecard",
    "main",
]


class ScorecardError(ContractError):
    """A scorecard payload or ledger row that must never reach the page.

    A **subclass** of :class:`backend.contract.ContractError` rather than a new root, for
    the same reason ``forecast/contract.py`` re-exports that class: a caller handling both
    ``results.json`` and the forecast documents already writes one ``except ContractError``
    clause, and a scorecard fault is the same category of fault — a document that would
    render a confident, wrong number. The distinct class name keeps the message readable
    when the two are caught together.
    """


# --- paths and tunables ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The append-only ledger. **Module global, read at call time** (never captured in a
#: default argument) so a test can repoint it at a fixture without patching every caller.
LEDGER_PATH = REPO_ROOT / "data" / "forecast_ledger.jsonl"

#: The §9 forward payload the record pass reads. Gitignored — a fresh clone has none, and
#: that is a stated no-op, not an error.
FORECAST_PATH = REPO_ROOT / "data" / "forecast.json"

#: ``(connect, read)`` for the one observation request a grading pass issues.
#: ``fetch/obs.py``'s 120 s is sized for a 30-day backfill and is far too long for a
#: request path.
HTTP_TIMEOUT = (3.05, 5.0)

#: Wall-clock budget for a grading pass, in seconds.
GRADE_DEADLINE_S = 6.0

#: Hours past a step's valid time before an unmatched row is called a ``gap`` rather than
#: left pending. ASOS reports once an hour; three missed hours is a real hole, not lag.
GAP_GRACE_H = 3

#: The widest observation window one pass will ask for. After long downtime an uncapped
#: window would request months of data on a 6 s deadline. Rows beyond it stay pending with
#: a stated reason and a count in ``meta.counts``; nothing is silently dropped.
MAX_OBS_WINDOW_DAYS = 7

#: The observation series every grade is scored against, named in the payload so a reader
#: never has to guess which station or which network.
OBS_SOURCE = "iem_asos_OMA"

#: The join's match window in minutes. **Derived from** :data:`score.join.TOLERANCE` so the
#: number the page prints can never drift from the number the join enforced.
TOLERANCE_MIN = int(_JOIN_TOLERANCE.total_seconds() // 60)

#: Cycles required before the payload stops saying "not enough days yet".
#:
#: **28** = four cycles a day (00/06/12/18z) times seven days. Below one full week of
#: forward record every mean here is dominated by a single synoptic regime, so a
#: blend-versus-member verdict would be reporting the weather rather than any skill. Seven
#: days is the smallest span over which the site sees more than one pattern; it is a floor
#: on *honesty of the claim*, not a target, and the real numbers are published either way
#: — :data:`not_enough_reason` states the count, it never hides the record.
MIN_CYCLES_FOR_ENOUGH = 28

#: The blend's series name in the ledger. The four members use their own model names.
BLEND_SERIES = "BLEND"

SERIES_KINDS = ("model", "blend")
GRADE_STATUSES = ("graded", "gap")

#: Decimal places every published statistic is rounded to. The comparison
#: (``blend_beaten``) is made on these **rounded** values on purpose: a reader recomputing
#: from the page must reach the same verdict the page states, and a "beaten" beside two
#: identical printed numbers is a page arguing with itself.
STAT_DECIMALS = 3

_LEDGER_LOCK = threading.Lock()


# --- the LOCKED ledger row contract ---------------------------------------------------------

#: Identity of a ledger row: ``(kind, init_time, valid_time, lead_h, series)``.
IDENTITY_FIELDS = ("kind", "init_time", "valid_time", "lead_h", "series")

PREDICTION_FIELDS = (
    "kind",
    "init_time",
    "run_label",
    "valid_time",
    "lead_h",
    "series",
    "series_kind",
    "forecast_f",
    "weights_fitted_at_lead_h",
    "is_extrapolated_lead",
    "source_generated_at",
    "recorded_at",
)

GRADE_FIELDS = (
    "kind",
    "init_time",
    "valid_time",
    "lead_h",
    "series",
    "status",
    "observed_f",
    "obs_offset_min",
    "error_f",
    "abs_error_f",
    "reason",
    "obs_source",
    "tolerance_min",
    "graded_at",
)


# --- time helpers ---------------------------------------------------------------------------


def _as_utc(moment: datetime) -> datetime:
    """A naive input is UTC, never local (``fetch/backfill.py:90``)."""
    if not isinstance(moment, datetime):
        raise ScorecardError(f"expected a datetime, got {type(moment).__name__}")
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    """ISO-8601 UTC with a trailing ``Z`` — never ``+00:00`` (SPEC §2)."""
    return _as_utc(moment).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str, path: str) -> datetime:
    """Parse a stored ``...Z`` stamp back to an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        raise ScorecardError(f"{path}: expected an ISO-8601 UTC stamp, got {value!r}")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return _as_utc(datetime.fromisoformat(text))
    except ValueError as exc:
        raise ScorecardError(f"{path}: {value!r} is not an ISO-8601 instant") from exc


def _now_iso() -> str:
    """Wall clock. **Above the purity boundary** — never called from :func:`scorecard`."""
    return _iso(datetime.now(timezone.utc))


def _stamp(value, fallback_now: bool) -> str | None:
    """Normalise a caller-supplied stamp; ``None`` means "stamp it now" where allowed."""
    if value is None:
        return _now_iso() if fallback_now else None
    if isinstance(value, datetime):
        return _iso(value)
    return str(value)


# --- row identity ----------------------------------------------------------------------------


def row_identity(record: dict) -> tuple[str, str, str, int, str]:
    """``(kind, init_time, valid_time, lead_h, series)`` — the identity of one ledger row.

    A prediction and its grade share four of the five parts and differ in ``kind``, so the
    two lines never collide while still joining on the step they describe.
    """
    if not isinstance(record, dict):
        raise ScorecardError(f"a ledger row must be an object, got {type(record).__name__}")
    missing = [field for field in IDENTITY_FIELDS if field not in record]
    if missing:
        raise ScorecardError(f"ledger row is missing identity field(s) {missing}")
    return (
        str(record["kind"]),
        str(record["init_time"]),
        str(record["valid_time"]),
        int(record["lead_h"]),
        str(record["series"]),
    )


def series_identity(record: dict) -> tuple[str, str, int, str]:
    """The identity with ``kind`` dropped — what joins a grade line to its prediction."""
    return row_identity(record)[1:]


def step_identity(record: dict) -> tuple[str, str, int]:
    """``(init_time, valid_time, lead_h)`` — one forecast step, all series together."""
    identity = row_identity(record)
    return (identity[1], identity[2], identity[3])


# --- the row builders -------------------------------------------------------------------------


def make_prediction_row(
    *,
    init_time,
    run_label,
    valid_time,
    lead_h,
    series,
    series_kind,
    forecast_f,
    weights_fitted_at_lead_h,
    is_extrapolated_lead,
    source_generated_at,
    recorded_at=None,
) -> dict:
    """One prediction line. Every key present every time, in :data:`PREDICTION_FIELDS` order.

    The shape is ``fetch/backfill.py:122``'s: a row never grows or loses a key depending on
    which branch built it, because a consumer reading ``row["forecast_f"]`` must not have to
    know which branch that was.
    """
    kind = str(series_kind)
    if kind not in SERIES_KINDS:
        raise ScorecardError(f"series_kind must be one of {list(SERIES_KINDS)}, got {kind!r}")
    name = str(series)
    if kind == "blend" and name != BLEND_SERIES:
        raise ScorecardError(f"the blend series is named {BLEND_SERIES!r}, got {name!r}")
    if kind == "model" and name == BLEND_SERIES:
        raise ScorecardError(f"{BLEND_SERIES!r} is the blend, and may not be recorded as a model")
    record = {
        "kind": "prediction",
        "init_time": _stamp(init_time, False),
        "run_label": None if run_label is None else str(run_label),
        "valid_time": _stamp(valid_time, False),
        "lead_h": int(lead_h),
        "series": name,
        "series_kind": kind,
        "forecast_f": float(forecast_f),
        "weights_fitted_at_lead_h": (
            None if weights_fitted_at_lead_h is None else int(weights_fitted_at_lead_h)
        ),
        "is_extrapolated_lead": (
            None if is_extrapolated_lead is None else bool(is_extrapolated_lead)
        ),
        "source_generated_at": _stamp(source_generated_at, False),
        "recorded_at": _stamp(recorded_at, True),
    }
    _require_fields(record, PREDICTION_FIELDS, "prediction")
    return record


def make_grade_row(
    *,
    init_time,
    valid_time,
    lead_h,
    series,
    status,
    observed_f=None,
    obs_offset_min=None,
    error_f=None,
    abs_error_f=None,
    reason=None,
    obs_source=OBS_SOURCE,
    tolerance_min=None,
    graded_at=None,
) -> dict:
    """One grade line. Every key present every time, in :data:`GRADE_FIELDS` order.

    ``status`` is ``"graded"`` or ``"gap"``. **``pending`` is the absence of a grade line**,
    never a line of its own: a pending row is a row nobody has scored yet, and writing that
    down would create a fact where there is none.

    A ``gap`` carries ``None`` for every number and a **non-null sentence** in ``reason`` —
    a hole in the observations that is stated is a fact; a hole that is silently averaged
    away is a lie about the denominator.
    """
    state = str(status)
    if state not in GRADE_STATUSES:
        raise ScorecardError(f"status must be one of {list(GRADE_STATUSES)}, got {state!r}")

    if state == "gap":
        if reason is None or not str(reason).strip():
            raise ScorecardError("a gap row must carry a non-empty reason naming what is missing")
        for label, value in (
            ("observed_f", observed_f),
            ("obs_offset_min", obs_offset_min),
            ("error_f", error_f),
            ("abs_error_f", abs_error_f),
        ):
            if value is not None:
                raise ScorecardError(f"a gap row carries no {label}; got {value!r}")
    else:
        if observed_f is None or error_f is None or obs_offset_min is None:
            raise ScorecardError(
                "a graded row must carry observed_f, obs_offset_min and error_f; a graded "
                "row missing its observation is a pending row, not a graded one"
            )
        if abs(int(obs_offset_min)) > TOLERANCE_MIN:
            raise ScorecardError(
                f"obs_offset_min {obs_offset_min} lies outside the +/-{TOLERANCE_MIN} minute "
                "join window; the observation was never a match for this step"
            )
        if abs_error_f is None:
            abs_error_f = abs(float(error_f))
        elif abs(float(abs_error_f) - abs(float(error_f))) > 1e-9:
            raise ScorecardError(
                f"abs_error_f {abs_error_f} disagrees with |error_f| {abs(float(error_f))}; "
                "the two are carried together so no consumer re-derives one from the other"
            )

    record = {
        "kind": "grade",
        "init_time": _stamp(init_time, False),
        "valid_time": _stamp(valid_time, False),
        "lead_h": int(lead_h),
        "series": str(series),
        "status": state,
        "observed_f": None if observed_f is None else float(observed_f),
        "obs_offset_min": None if obs_offset_min is None else int(obs_offset_min),
        "error_f": None if error_f is None else float(error_f),
        "abs_error_f": None if abs_error_f is None else float(abs_error_f),
        "reason": None if reason is None else str(reason),
        "obs_source": None if obs_source is None else str(obs_source),
        "tolerance_min": TOLERANCE_MIN if tolerance_min is None else int(tolerance_min),
        "graded_at": _stamp(graded_at, True),
    }
    _require_fields(record, GRADE_FIELDS, "grade")
    return record


def _require_fields(record: dict, fields: tuple[str, ...], label: str) -> None:
    """Every declared key present, in the declared order, and nothing else."""
    if tuple(record.keys()) != fields:
        raise ScorecardError(
            f"a {label} row must carry exactly {list(fields)} in that order, got "
            f"{list(record.keys())}"
        )


# --- (a) append-only ledger I/O ---------------------------------------------------------------


def append_ledger(path, record: dict) -> None:
    """Append one JSON line, flushed, under a module-level lock.

    ``fetch/backfill.py:154`` line for line, and for the same reason: a whole line is
    written in one call while the lock is held, so a concurrent writer can never interleave
    half of its object into the middle of this one.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record) + "\n"
    with _LEDGER_LOCK:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


def load_ledger(path) -> list[dict]:
    """Every ledger row, in file order.

    **A missing file is an empty ledger, not an error** — that is the state of a fresh
    clone, and of the moment before the first pass. Blank lines are skipped, and a
    crash-truncated final line is skipped rather than raised on: a half-written line is a
    normal consequence of killing the process, not a reason to lose every row before it.
    A row that cannot be identified is skipped for the same reason.
    """
    source = Path(path)
    if not source.exists():
        return []
    rows: list[dict] = []
    with open(source, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                continue  # truncated final line from a crash — skip it, never raise
            if not isinstance(record, dict):
                continue
            try:
                row_identity(record)
            except (ScorecardError, TypeError, ValueError):
                continue
            rows.append(record)
    return rows


def dedupe(rows) -> list[dict]:
    """One row per identity: **latest-wins for ``prediction``, first-wins for ``grade``**.

    A prediction may legitimately be re-stated (a corrected payload for a cycle nobody has
    graded yet); a grade never may — it is the outcome, and an outcome that can be
    overwritten is not a record. The **writer** refuses a second line for any existing
    identity, so on any ledger this module produces the two rules are observationally
    identical, and a test pins exactly that.

    First-appearance order of identities is preserved, so the output is deterministic.
    """
    chosen: dict[tuple, dict] = {}
    order: list[tuple] = []
    for record in rows:
        identity = row_identity(record)
        if identity not in chosen:
            chosen[identity] = record
            order.append(identity)
        elif identity[0] == "prediction":
            chosen[identity] = record
    return [chosen[identity] for identity in order]


def has_identity(rows, identity) -> bool:
    """The write-side guard both passes use before appending anything."""
    wanted = tuple(identity)
    for record in rows:
        if row_identity(record) == wanted:
            return True
    return False


# --- (b) the impure passes ----------------------------------------------------------------------
#
# Everything below this banner and above the "(c) the pure core" banner reads a clock, a
# disk or a socket. That is what these functions are for, and it is why they are kept apart
# from the layer beneath them: the number the page publishes is computed by a function that
# can do none of those things, from rows these passes wrote down earlier.


#: What a row beyond :data:`MAX_OBS_WINDOW_DAYS` is told it is. Stated once, so the sentence
#: a pass reports and the ``meta.counts.rows_outside_grading_window`` figure
#: :func:`scorecard` publishes are describing the same rows in the same words.
OUTSIDE_WINDOW_REASON = "outside this pass's observation window"

#: The committed backtest output. Read **read-only**, and only for the one fact the ledger
#: row contract does not carry: the days the weights were fitted over. Nothing in this
#: module ever changes it.
RESULTS_PATH = REPO_ROOT / "data" / "results.json"


def now_utc() -> datetime:
    """The wall clock, as an aware UTC instant.

    A named function rather than an inline call, exactly as ``forecast/refresh.py:87`` does
    it, so a test can freeze the instant without touching ``datetime`` itself and without
    the CLI growing a ``--now`` flag. **Above the purity boundary**: :func:`scorecard` is
    handed the result, it never asks for it.
    """
    return datetime.now(timezone.utc)


# --- the record pass ------------------------------------------------------------------------


def _prediction_rows_for_cycle(document: dict, *, recorded_at=None) -> list[dict]:
    """One prediction row per (step, series) for a validated §9 forecast document.

    ``(len(models_included) + 1) x len(forecast)`` rows: every member, **and the blend
    beside them**, from the same step, in the same pass. The blend is not an afterthought
    here — a record that carries the members but not the blend cannot say whether the blend
    was beaten, which is the only question this feature exists to answer.
    """
    meta = document["meta"]
    cycle = meta["cycle"]
    models = [str(name) for name in meta["models_included"]]
    stamp = _now_iso() if recorded_at is None else _stamp(recorded_at, False)

    rows: list[dict] = []
    for step in document["forecast"]:
        members = step["members"]
        common = {
            "init_time": cycle["init_time"],
            "run_label": cycle.get("run_label"),
            "valid_time": step["valid_time"],
            "lead_h": step["lead_h"],
            "weights_fitted_at_lead_h": step.get("weights_fitted_at_lead_h"),
            "is_extrapolated_lead": step.get("is_extrapolated_lead"),
            "source_generated_at": meta.get("generated_at"),
            "recorded_at": stamp,
        }
        for name in models:
            if name not in members:
                raise ScorecardError(
                    f"the step valid at {step['valid_time']} is missing member {name!r}, which "
                    f"the payload publishes in models_included; a step short of a member was "
                    "never blended and belongs nowhere in a record of what was served"
                )
            rows.append(
                make_prediction_row(
                    series=name, series_kind="model", forecast_f=members[name], **common
                )
            )
        rows.append(
            make_prediction_row(
                series=BLEND_SERIES,
                series_kind="blend",
                forecast_f=step["blend_f"],
                **common,
            )
        )

    expected = (len(models) + 1) * len(document["forecast"])
    if len(rows) != expected:
        raise ScorecardError(
            f"a cycle of {len(document['forecast'])} step(s) over {len(models)} member(s) is "
            f"{expected} rows (every member, plus the blend, at every step), got {len(rows)}"
        )
    return rows


def record(payload_path=None, ledger_path=None) -> dict:
    """Write one served cycle into the ledger, **before any of it can be graded**.

    Returns a stated outcome; it raises only where the ledger itself cannot be appended to.

    Three outcomes are no-ops rather than errors, and each says which one it was:

    * **The payload is absent.** ``data/forecast.json`` is gitignored, so a fresh clone has
      none. That is the ordinary state of a clone, not a fault, and the page renders from
      the committed ledger alone.
    * **The payload fails its §9 contract.** A cycle that cannot be validated is never
      written into a file whose whole value is that nothing in it can be taken back.
    * **The cycle is already recorded.** The first write of an ``init_time`` wins and the
      pass appends nothing. Re-running is free and leaves the file byte-identical.
    """
    payload = Path(FORECAST_PATH if payload_path is None else payload_path)
    ledger = Path(LEDGER_PATH if ledger_path is None else ledger_path)
    outcome = {
        "recorded": 0,
        "init_time": None,
        "run_label": None,
        "reason": None,
        "payload_path": str(payload),
        "ledger_path": str(ledger),
    }

    if not payload.exists():
        outcome["reason"] = (
            f"{payload} is absent, so there was no served cycle to write down. The payload is "
            "gitignored and a fresh clone has none; the scorecard is rendered from the "
            "committed ledger alone. Nothing was appended."
        )
        return outcome

    try:
        document = load_and_validate_forecast(payload)
    except ContractError as exc:
        outcome["reason"] = (
            f"{payload} does not satisfy the FORECAST-SPEC §9 contract ({exc}); a cycle that "
            "cannot be validated is not written into a record that can never be corrected. "
            "Nothing was appended."
        )
        return outcome

    cycle = document["meta"]["cycle"]
    outcome["init_time"] = str(cycle["init_time"])
    outcome["run_label"] = None if cycle.get("run_label") is None else str(cycle["run_label"])

    existing = load_ledger(ledger)
    already = [
        row
        for row in existing
        if row.get("kind") == "prediction" and str(row.get("init_time")) == outcome["init_time"]
    ]
    if already:
        outcome["reason"] = (
            f"cycle {outcome['init_time']} is already in the ledger with {len(already)} "
            "prediction row(s); the first write of a cycle wins and nothing was appended. A "
            "prediction that could be restated after its outcome was known would not be a "
            "forward record."
        )
        return outcome

    for row in _prediction_rows_for_cycle(document):
        if has_identity(existing, row_identity(row)):
            continue
        append_ledger(ledger, row)
        existing.append(row)
        outcome["recorded"] += 1
    return outcome


# --- the bounded fetch and the observation window -----------------------------------------------


def _bounded_get(url, timeout=None):
    """``requests.get`` under :data:`HTTP_TIMEOUT`, whatever timeout it is handed.

    **The ``timeout`` argument is accepted and discarded on purpose.** ``fetch/obs.py``
    passes its own module constant — ``_TIMEOUT = 120`` at ``fetch/obs.py:51`` — to every
    ``session_get`` it calls. That figure is sized for the 30-day backfill, where two
    minutes on one request is nothing; on a request path with a 6 s budget it is a hang.
    This wrapper exists solely to override it, so **do not "fix" the unused parameter**:
    accepting it is how the seam is honoured, and ignoring it is the whole point.
    """
    return requests.get(url, timeout=HTTP_TIMEOUT)


def _bounded(session_get):
    """The transport a pass hands to ``fetch_obs``, bounded the same way for tests and life.

    An injected transport is wrapped rather than passed through, so the timeout a test
    observes is the timeout production uses. A stub that saw ``120`` would be proving the
    bound on some other code path than the one that ships.
    """
    if session_get is None:
        return _bounded_get

    def bounded(url, timeout=None):
        return session_get(url, timeout=HTTP_TIMEOUT)

    return bounded


def observation_window(ungraded_rows, now):
    """``(start, end, inside, outside)`` — the one slice of observations a pass will ask for.

    ``[min valid_time − tolerance, min(now, max valid_time + tolerance)]``. The tolerance
    padding is the join's own ±30 minutes: an observation eight minutes *before* the first
    step is the one that scores it, and a window that started at the step would not contain
    it.

    The window is **capped at** :data:`MAX_OBS_WINDOW_DAYS`. After a long silence an
    uncapped window would ask for months of observations on a six-second budget and get
    nothing at all. Rows older than the cap are returned in ``outside``: they stay
    **pending**, they are reported as :data:`OUTSIDE_WINDOW_REASON`, and
    :func:`scorecard` counts them in ``meta.counts.rows_outside_grading_window``. Nothing
    is dropped quietly — a widened window in a later pass will still find them.
    """
    moment = _as_utc(now)
    cutoff = moment - timedelta(days=MAX_OBS_WINDOW_DAYS)
    padding = timedelta(minutes=TOLERANCE_MIN)

    inside: list[dict] = []
    outside: list[dict] = []
    for row in ungraded_rows:
        if _parse_iso(row["valid_time"], "valid_time") < cutoff:
            outside.append(row)
        else:
            inside.append(row)
    if not inside:
        return (None, None, inside, outside)

    times = [_parse_iso(row["valid_time"], "valid_time") for row in inside]
    start = min(times) - padding
    end = min(moment, max(times) + padding)
    if end < start:
        end = start
    return (start, end, inside, outside)


# --- the grade pass -------------------------------------------------------------------------


def _offered_frame(rows, coverage_start, coverage_end, obs):
    """The **member** rows inside the observed coverage, shaped for the imported join.

    Two filters, and both matter:

    * **The blend is never offered.** ``score.blend.canonical_model_name`` raises on
      ``"BLEND"`` (``score/blend.py:70``), so the blend physically cannot pass through the
      join; it is attached afterwards to the observation its own members matched.
    * **Only rows inside the observed coverage.** A live cycle runs 48 hours into the
      future, and those steps have no observation yet — offering them would put a 0 %
      group in front of the 80 % floor and kill a pass that had nothing wrong with it.
    """
    records = []
    for row in rows:
        if str(row.get("series")) == BLEND_SERIES:
            continue
        moment = _parse_iso(row["valid_time"], "valid_time")
        if moment < coverage_start or moment > coverage_end:
            continue
        records.append(
            {
                "model": str(row["series"]),
                "init_time": _parse_iso(row["init_time"], "init_time"),
                "valid_time": moment,
                "lead_h": int(row["lead_h"]),
                "temp_f": float(row["forecast_f"]),
            }
        )
    columns = ["model", "init_time", "valid_time", "lead_h", "temp_f"]
    frame = pd.DataFrame.from_records(records, columns=columns)
    if frame.empty:
        return frame
    stamp_dtype = obs["valid_time"].dtype
    for column in ("init_time", "valid_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True).astype(stamp_dtype)
    frame["lead_h"] = frame["lead_h"].astype(int)
    frame["temp_f"] = frame["temp_f"].astype(float)
    return frame


def _any_offered_row_could_match(offered, obs) -> bool:
    """Could **any** offered row have matched **any** observation within the tolerance?

    A pre-flight over two small lists of timestamps, and deliberately not a second join: it
    never decides which observation scores a step — ``score.join`` owns that and is never
    mirrored — it answers one yes/no question at the pass boundary. It exists to tell the
    two failures apart after the join has raised, because the join reports both with a
    ``RuntimeError``:

    * some group came in under the 80 % floor while others matched — a thin sample, which
      is a **stated skip**; and
    * nothing matched anything at all — which is the failure mode this whole feature is
      built against. Observations land at ``:52`` and forecasts on the hour; a system that
      compared them as exact timestamps would match zero rows, report a flawless mean over
      an empty frame, and be entirely fictional. That is never a skip. It **raises**.
    """
    limit = float(TOLERANCE_MIN) * 60.0
    obs_times = [pd.Timestamp(stamp) for stamp in obs["valid_time"]]
    for stamp in offered["valid_time"]:
        moment = pd.Timestamp(stamp)
        for other in obs_times:
            if abs((other - moment).total_seconds()) <= limit:
                return True
    return False


def _collect_observations(matched) -> dict:
    """``{(init_time, valid_time, lead_h): {"observed_f", "obs_offset_min"}}`` from the join.

    ``forecast/history.py:294-330``'s shape, and it checks the same thing that module
    checks: the join carries **no ``by=`` argument**, so every member of one step matched
    the same single global observation series. If two members of a step disagree about
    their observation, the blend has two candidate answers and there is no honest way to
    pick one, so this raises rather than choosing.

    ``obs_offset_min`` is published as an integer and is **never rounded to make it fit** —
    a rounded offset states a match that did not happen.
    """
    steps: dict[tuple[str, str, int], dict] = {}
    for row in matched.itertuples(index=False):
        offset = float(row.offset_min)
        if abs(offset - round(offset)) > 1e-9:
            raise ScorecardError(
                f"the row valid at {row.valid_time} sits {offset!r} minutes from its "
                "observation, a fractional number of minutes; obs_offset_min is published as "
                "an integer and is never rounded to make it fit"
            )
        key = (
            _iso(pd.Timestamp(row.init_time).to_pydatetime()),
            _iso(pd.Timestamp(row.valid_time).to_pydatetime()),
            int(row.lead_h),
        )
        observation = {"observed_f": float(row.obs_f), "obs_offset_min": int(round(offset))}
        seen = steps.setdefault(key, observation)
        if seen != observation:
            raise ScorecardError(
                f"the members of the step valid at {key[1]} / {key[2]} h matched different "
                "observations; the observed series is one global series and every member of a "
                "step is scored against the same reading, so the blend cannot be attached to "
                "one of two answers"
            )
    return steps


def _grade_outcome(ledger) -> dict:
    """The stated shape every exit from :func:`grade` returns, so no caller reads a hole."""
    return {
        "graded": 0,
        "gap": 0,
        "pending": 0,
        "matched": 0,
        "offered": 0,
        "outside_window": 0,
        "obs_rows": 0,
        "window": None,
        "skips": [],
        "reason": None,
        "ledger_path": str(ledger),
    }


def grade(ledger_path=None, *, now=None, deadline_s=GRADE_DEADLINE_S, session_get=None) -> dict:
    """Score the rows whose observations have since been published. **One request, bounded.**

    Returns a stated outcome. A fetch that fails, a window with nothing in it, a sample too
    thin for the join's floor and a budget that ran out are all *operating conditions*: each
    becomes a named skip and leaves its rows **pending**, because a pending row is a row
    nobody has scored yet, and that is a state rather than an error.

    One thing is **not** an operating condition and raises: a pass that offered the join
    rows against real observations and matched **none** of them. An empty join scores
    perfectly (SPEC §4/§10), and reporting a clean sheet there is the single most damaging
    thing this module could do.

    The budget is :data:`GRADE_DEADLINE_S` of wall clock, read from ``time.monotonic`` before
    the request is issued and again before anything is joined or written. There is no
    thread, no future and no timer: one HTTP request per pass is what makes a plain
    before/after check honest, and a background worker left running past a deadline is worse
    than the wait it was meant to save.
    """
    ledger = Path(LEDGER_PATH if ledger_path is None else ledger_path)
    moment = _as_utc(now_utc() if now is None else now)
    started = time.monotonic()
    outcome = _grade_outcome(ledger)

    rows = dedupe(load_ledger(ledger))
    already_graded = {series_identity(row) for row in rows if row.get("kind") == "grade"}
    ungraded = [
        row
        for row in rows
        if row.get("kind") == "prediction" and series_identity(row) not in already_graded
    ]
    outcome["pending"] = len(ungraded)
    if not ungraded:
        outcome["reason"] = (
            "every recorded row already carries a grade line, so no observation was "
            "requested. A grade is written once and is never revised."
        )
        return outcome

    start, end, inside, outside = observation_window(ungraded, moment)
    outcome["outside_window"] = len(outside)
    if outside:
        outcome["skips"].append(
            {
                "init_time": sorted(str(row["init_time"]) for row in outside)[0],
                "reason": (
                    f"{len(outside)} recorded row(s) are {OUTSIDE_WINDOW_REASON}: their valid "
                    f"times are more than {MAX_OBS_WINDOW_DAYS} days old, and one pass will not "
                    f"ask for months of observations on a {deadline_s:g} s budget. They stay "
                    "pending and are counted, not dropped."
                ),
                "n_rows": len(outside),
            }
        )
    if not inside:
        outcome["reason"] = (
            f"every ungraded row is {OUTSIDE_WINDOW_REASON}; nothing was requested and "
            "nothing was written."
        )
        return outcome
    outcome["window"] = {"start": _iso(start), "end": _iso(end)}

    if time.monotonic() - started > deadline_s:
        outcome["reason"] = (
            f"the pass reached its {deadline_s:g} s budget before the observation request was "
            "issued; every row it would have graded is still pending. A timeout is an ungraded "
            "row, not an error."
        )
        return outcome

    try:
        obs = fetch_obs(start, end, session_get=_bounded(session_get))
    except Exception as exc:  # a fetch failure is an ungraded row, never a broken page
        outcome["reason"] = (
            f"the observation request failed ({type(exc).__name__}: {exc}); every ungraded row "
            "is still pending and nothing was written. There is no second observation source "
            "and no substitute reading."
        )
        return outcome
    outcome["obs_rows"] = int(len(obs))

    if time.monotonic() - started > deadline_s:
        outcome["reason"] = (
            f"the pass reached its {deadline_s:g} s budget with the observations in hand but "
            "before anything was joined; nothing was written and every row is still pending."
        )
        return outcome

    if obs.empty:
        outcome["reason"] = (
            f"{OBS_SOURCE} published no usable reading between {_iso(start)} and {_iso(end)}; "
            "there was nothing to score against, and an empty join scores perfectly and is "
            "fake. Nothing was written."
        )
        return outcome

    padding = timedelta(minutes=TOLERANCE_MIN)
    coverage_start = _as_utc(pd.Timestamp(obs["valid_time"].min()).to_pydatetime()) - padding
    coverage_end = _as_utc(pd.Timestamp(obs["valid_time"].max()).to_pydatetime()) + padding
    offered = _offered_frame(inside, coverage_start, coverage_end, obs)
    outcome["offered"] = int(len(offered))

    steps: dict[tuple[str, str, int], dict] = {}
    if outcome["offered"]:
        try:
            matched, _stats = join_forecasts_to_obs(offered, obs)
        except (RuntimeError, ValueError) as exc:
            if not _any_offered_row_could_match(offered, obs):
                raise ScorecardError(
                    f"the join was offered {outcome['offered']} forecast row(s) against "
                    f"{outcome['obs_rows']} observation(s) and matched none of them within "
                    f"±{TOLERANCE_MIN} minutes — an empty join. An empty join scores perfectly "
                    "and is fake (SPEC §4/§10): observations land near :52 and forecast steps "
                    "on the hour, so a pass that matches zero rows has compared the wrong "
                    f"things rather than found a quiet day. The join said: {exc}"
                ) from exc
            outcome["skips"].append(
                {
                    "init_time": sorted(str(row["init_time"]) for row in inside)[0],
                    "reason": (
                        f"the observation sample was too thin for the join's 80 % per-(model, "
                        f"lead) floor, so no row in this pass was graded: {exc}"
                    ),
                    "n_rows": outcome["offered"],
                }
            )
            outcome["reason"] = (
                "the join refused the sample it was offered and nothing was written; every "
                "row is still pending and the shortfall is reported rather than averaged over."
            )
            return outcome
        outcome["matched"] = int(len(matched))
        steps = _collect_observations(matched)

    graded_at = _now_iso()
    grace = moment - timedelta(hours=GAP_GRACE_H)
    for row in inside:
        step = steps.get(step_identity(row))
        if step is None:
            if _parse_iso(row["valid_time"], "valid_time") > grace:
                continue  # still pending: the observation may simply not exist yet
            line = make_grade_row(
                init_time=row["init_time"],
                valid_time=row["valid_time"],
                lead_h=row["lead_h"],
                series=row["series"],
                status="gap",
                reason=(
                    f"no {OBS_SOURCE} observation within ±{TOLERANCE_MIN} minutes of "
                    f"{row['valid_time']} had been published {GAP_GRACE_H} h after the step; "
                    "the hole is stated and excluded from every mean, never filled"
                ),
                graded_at=graded_at,
            )
        else:
            error = float(row["forecast_f"]) - step["observed_f"]
            line = make_grade_row(
                init_time=row["init_time"],
                valid_time=row["valid_time"],
                lead_h=row["lead_h"],
                series=row["series"],
                status="graded",
                observed_f=step["observed_f"],
                obs_offset_min=step["obs_offset_min"],
                error_f=error,
                abs_error_f=abs(error),
                graded_at=graded_at,
            )
        if has_identity(rows, row_identity(line)):
            continue  # first grade wins: an outcome that can be overwritten is not a record
        append_ledger(ledger, line)
        rows.append(line)
        outcome["graded" if line["status"] == "graded" else "gap"] += 1

    outcome["pending"] = len(ungraded) - outcome["graded"] - outcome["gap"]
    return outcome


# --- (c) the pure core ------------------------------------------------------------------------

#: Every function :func:`scorecard` relies on, below the purity boundary. The purity test
#: scans the source of each one; adding a helper without registering it here is the way the
#: boundary would rot, so the list is the contract and the test reads it.
PURE_FUNCTION_NAMES = (
    "scorecard",
    "streaks",
    "ledger_meta",
    "dedupe",
    "has_identity",
    "row_identity",
    "series_identity",
    "step_identity",
    "_as_utc",
    "_iso",
    "_parse_iso",
    "_mean",
    "_round",
    "_group_comparison",
    "_require_fields",
)


def _round(value):
    """Publish at :data:`STAT_DECIMALS`. ``None`` stays ``None``, never becomes ``0.0``."""
    if value is None:
        return None
    return round(float(value), STAT_DECIMALS)


def _mean(values):
    """The mean, or ``None`` over an empty sample. **Never ``0.0``** — see SPEC §10."""
    if not values:
        return None
    return _round(sum(values) / len(values))


def ledger_meta(rows, *, weights_fitted_window=None) -> dict:
    """The static block :func:`scorecard` is handed, composed with **zero disk reads**.

    Site, variable and units are pinned facts imported from ``score.build`` and
    ``forecast.contract`` rather than re-typed here. ``models_included`` is derived from the
    ledger's **own** prediction rows in first-appearance order, so a fresh clone with
    nothing but the committed ledger still knows which members to render — the §9 payload
    is gitignored and may be absent.

    ``weights_fitted_window`` is **injected**, not read: it lives in ``forecast.json``'s
    ``meta.weights_source.window`` and the ledger row contract does not carry it. Where the
    payload is absent the window is ``None``, and the page says so rather than inventing one.
    """
    models: list[str] = []
    for record in rows:
        if not isinstance(record, dict):
            continue
        if record.get("kind") != "prediction" or record.get("series_kind") != "model":
            continue
        name = str(record.get("series"))
        if name not in models:
            models.append(name)
    return {
        "site": dict(SITE),
        "variable": VARIABLE,
        "units": UNITS,
        "obs_source": OBS_SOURCE,
        "tolerance_min": TOLERANCE_MIN,
        "never_interpolated": True,
        "models_included": models,
        "weights_fitted_window": (
            None if weights_fitted_window is None else dict(weights_fitted_window)
        ),
    }


def streaks(cycle_results) -> dict:
    """Run lengths over cycles, **in the chronological order given**.

    A cycle is *won* when the blend's mean absolute error is strictly below the best
    member's on the same steps, and *beaten* when it is strictly above. **A tie is neither**
    — it breaks both runs and starts neither, because "the blend has won its last four
    cycles" must not be true of four cycles it merely drew. A cycle with no comparison
    (either mean ``None``) also breaks both runs and is not counted in ``n_cycles_scored``:
    an unscored cycle is not evidence in either direction.
    """
    current_beaten = longest_beaten = 0
    current_won = longest_won = 0
    scored = 0
    for cycle in cycle_results:
        blend = cycle.get("blend_mae_f")
        best = cycle.get("best_single_mae_f")
        if blend is None or best is None:
            current_beaten = 0
            current_won = 0
            continue
        scored += 1
        if blend > best:
            current_beaten += 1
            current_won = 0
        elif blend < best:
            current_won += 1
            current_beaten = 0
        else:
            current_beaten = 0
            current_won = 0
        longest_beaten = max(longest_beaten, current_beaten)
        longest_won = max(longest_won, current_won)
    return {
        "n_cycles_scored": scored,
        "current_beaten_cycles": current_beaten,
        "longest_beaten_cycles": longest_beaten,
        "current_won_cycles": current_won,
        "longest_won_cycles": longest_won,
    }


def _group_comparison(entries, models):
    """Blend versus best member **over the steps where both were graded**.

    Returns ``(blend_mae_f, best_single_model, best_single_mae_f, blend_beaten, n_compared,
    n_excluded)``. ``n_excluded`` counts graded rows in the group that no comparison could
    use because some series was not graded at that step — they are reported, never averaged
    across a different denominator.

    The winner is chosen by ``(mae, name)`` so two members tied to the last published
    decimal resolve by name rather than by dict order; the verdict must not depend on the
    order rows happened to be written.
    """
    graded_by_step: dict[tuple, dict[str, float]] = {}
    for entry in entries:
        if entry["status"] != "graded":
            continue
        graded_by_step.setdefault(entry["step"], {})[entry["series"]] = entry["abs_error_f"]

    wanted = set(models) | {BLEND_SERIES}
    compared = [step for step, seen in graded_by_step.items() if wanted.issubset(seen)]
    n_excluded = sum(
        len(seen) for step, seen in graded_by_step.items() if step not in set(compared)
    )
    if not compared:
        return (None, None, None, None, 0, n_excluded)

    blend_mae = _mean([graded_by_step[step][BLEND_SERIES] for step in compared])
    scores = sorted(
        (_mean([graded_by_step[step][model] for step in compared]), model) for model in models
    )
    best_mae, best_model = scores[0]
    beaten = None if blend_mae is None or best_mae is None else bool(blend_mae > best_mae)
    return (blend_mae, best_model, best_mae, beaten, len(compared), n_excluded)


def scorecard(rows, now, *, meta) -> dict:
    """The realized-error scorecard. **PURE**: no network, no disk, no clock.

    ``rows`` is a ledger as :func:`load_ledger` returns it, ``now`` an aware UTC instant
    injected by the caller, and ``meta`` the static block from :func:`ledger_meta`. Calling
    this twice on the same arguments yields byte-identical ``json.dumps(..., sort_keys=True)``.

    Statuses: a prediction with a ``graded`` grade line is graded; with a ``gap`` line it is
    a gap and is **excluded from every mean**; with no grade line at all it is pending.
    A pending row whose valid time is older than :data:`MAX_OBS_WINDOW_DAYS` is additionally
    counted in ``meta.counts.rows_outside_grading_window`` — it is not lost, it is stated.
    """
    now_utc = _as_utc(now)
    for field in ("site", "variable", "units", "obs_source", "tolerance_min",
                  "never_interpolated", "models_included"):
        if field not in meta:
            raise ScorecardError(
                f"the static meta block is missing {field!r}; scorecard() invents nothing and "
                "is handed every fact it publishes"
            )
    models = [str(name) for name in meta["models_included"]]

    deduped = dedupe(rows)
    predictions = [record for record in deduped if record.get("kind") == "prediction"]
    grades = {
        series_identity(record): record
        for record in deduped
        if record.get("kind") == "grade"
    }

    cutoff = now_utc - timedelta(days=MAX_OBS_WINDOW_DAYS)
    entries = []
    counts = {"graded": 0, "pending": 0, "gap": 0, "rows_outside_grading_window": 0}
    for record in predictions:
        grade = grades.get(series_identity(record))
        status = "pending" if grade is None else str(grade.get("status"))
        if status not in ("graded", "gap", "pending"):
            raise ScorecardError(
                f"grade row for {series_identity(record)} carries status {status!r}; the only "
                f"statuses written are {list(GRADE_STATUSES)}, and pending is the absence of a row"
            )
        if status == "pending" and _parse_iso(record["valid_time"], "valid_time") < cutoff:
            counts["rows_outside_grading_window"] += 1
        counts[status] += 1
        entries.append(
            {
                "init_time": str(record["init_time"]),
                "run_label": record.get("run_label"),
                "valid_time": str(record["valid_time"]),
                "lead_h": int(record["lead_h"]),
                "series": str(record["series"]),
                "series_kind": str(record.get("series_kind")),
                "step": step_identity(record),
                "status": status,
                "error_f": None if grade is None else grade.get("error_f"),
                "abs_error_f": None if grade is None else grade.get("abs_error_f"),
            }
        )

    ordering = [name for name in models if any(e["series"] == name for e in entries)]
    ordering += [BLEND_SERIES] if any(e["series"] == BLEND_SERIES for e in entries) else []
    ordering += sorted(
        {e["series"] for e in entries} - set(ordering)
    )

    by_series = []
    for name in ordering:
        graded = [e for e in entries if e["series"] == name and e["status"] == "graded"]
        by_series.append(
            {
                "series": name,
                "series_kind": next(
                    (e["series_kind"] for e in entries if e["series"] == name), "model"
                ),
                "mae_f": _mean([float(e["abs_error_f"]) for e in graded]),
                "bias_f": _mean([float(e["error_f"]) for e in graded]),
                "n": len(graded),
            }
        )

    by_lead = []
    for lead in sorted({e["lead_h"] for e in entries}):
        group = [e for e in entries if e["lead_h"] == lead]
        blend_mae, best_model, best_mae, beaten, n_compared, _ = _group_comparison(group, models)
        by_lead.append(
            {
                "lead_h": lead,
                "blend_mae_f": blend_mae,
                "n": n_compared,
                "best_single_model": best_model,
                "best_single_mae_f": best_mae,
                "blend_beaten": beaten,
            }
        )

    by_cycle = []
    skips = []
    for init in sorted({e["init_time"] for e in entries}):
        group = [e for e in entries if e["init_time"] == init]
        blend_mae, best_model, best_mae, beaten, n_compared, n_excluded = _group_comparison(
            group, models
        )
        n_graded = sum(1 for e in group if e["status"] == "graded")
        by_cycle.append(
            {
                "init_time": init,
                "run_label": next((e["run_label"] for e in group if e["run_label"]), None),
                "n_graded": n_graded,
                "n_pending": sum(1 for e in group if e["status"] == "pending"),
                "n_gap": sum(1 for e in group if e["status"] == "gap"),
                "blend_mae_f": blend_mae,
                "best_single_model": best_model,
                "best_single_mae_f": best_mae,
                "blend_beaten": beaten,
            }
        )
        if n_compared == 0 and n_graded > 0:
            skips.append(
                {
                    "init_time": init,
                    "reason": (
                        "no step in this cycle has the blend and every member graded, so no "
                        "blend-versus-best-member comparison was made for it"
                    ),
                    "n_rows": n_graded,
                }
            )
        elif n_excluded > 0:
            skips.append(
                {
                    "init_time": init,
                    "reason": (
                        f"{n_excluded} graded row(s) in this cycle sit at steps where some "
                        "series was not graded, and were left out of the blend-versus-"
                        "best-member comparison; the two means are taken over the same steps "
                        "or they are not compared at all"
                    ),
                    "n_rows": n_excluded,
                }
            )

    init_times = sorted({e["init_time"] for e in entries})
    cycles_recorded = len(init_times)
    enough = cycles_recorded >= MIN_CYCLES_FOR_ENOUGH
    payload = {
        "meta": {
            "generated_at": _iso(now_utc),
            "site": dict(meta["site"]),
            "variable": str(meta["variable"]),
            "units": str(meta["units"]),
            "obs_source": str(meta["obs_source"]),
            "tolerance_min": int(meta["tolerance_min"]),
            "never_interpolated": bool(meta["never_interpolated"]),
            "models_included": list(models),
            "lead_hours": sorted({e["lead_h"] for e in entries if e["status"] == "graded"}),
            "counts": {
                "cycles_recorded": cycles_recorded,
                "rows_recorded": len(entries),
                "graded": counts["graded"],
                "pending": counts["pending"],
                "gap": counts["gap"],
                "rows_outside_grading_window": counts["rows_outside_grading_window"],
            },
            "window": {
                "first_init_time": init_times[0] if init_times else None,
                "last_init_time": init_times[-1] if init_times else None,
                "days_recorded": len({stamp[:10] for stamp in init_times}),
            },
            "weights_fitted_window": (
                None
                if meta.get("weights_fitted_window") is None
                else dict(meta["weights_fitted_window"])
            ),
        },
        "enough": enough,
        "not_enough_reason": (
            None if enough else f"not enough days yet, {cycles_recorded} recorded"
        ),
        "by_series": by_series,
        "by_lead": by_lead,
        "by_cycle": by_cycle,
        "skips": skips,
        "streaks": streaks(by_cycle),
    }
    return payload


# --- the scorecard-JSON validator ---------------------------------------------------------------

_TOP_KEYS = (
    "meta",
    "enough",
    "not_enough_reason",
    "by_series",
    "by_lead",
    "by_cycle",
    "skips",
    "streaks",
)
_META_KEYS = (
    "generated_at",
    "site",
    "variable",
    "units",
    "obs_source",
    "tolerance_min",
    "never_interpolated",
    "models_included",
    "lead_hours",
    "counts",
    "window",
    "weights_fitted_window",
)
_COUNT_KEYS = (
    "cycles_recorded",
    "rows_recorded",
    "graded",
    "pending",
    "gap",
    "rows_outside_grading_window",
)
_WINDOW_KEYS = ("first_init_time", "last_init_time", "days_recorded")
_SERIES_KEYS = ("series", "series_kind", "mae_f", "bias_f", "n")
_LEAD_KEYS = (
    "lead_h",
    "blend_mae_f",
    "n",
    "best_single_model",
    "best_single_mae_f",
    "blend_beaten",
)
_CYCLE_KEYS = (
    "init_time",
    "run_label",
    "n_graded",
    "n_pending",
    "n_gap",
    "blend_mae_f",
    "best_single_model",
    "best_single_mae_f",
    "blend_beaten",
)
_SKIP_KEYS = ("init_time", "reason", "n_rows")
_STREAK_KEYS = (
    "n_cycles_scored",
    "current_beaten_cycles",
    "longest_beaten_cycles",
    "current_won_cycles",
    "longest_won_cycles",
)


def _exact_keys(value, keys: tuple[str, ...], path: str) -> dict:
    if not isinstance(value, dict):
        raise ScorecardError(f"{path}: expected an object, got {type(value).__name__}")
    seen = set(value)
    wanted = set(keys)
    if seen != wanted:
        raise ScorecardError(
            f"{path}: expected exactly {sorted(wanted)}, got {sorted(seen)} "
            f"(missing {sorted(wanted - seen)}, unexpected {sorted(seen - wanted)})"
        )
    return value


def _non_negative_int(value, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScorecardError(f"{path}: every n is a plain non-negative int, got {value!r}")
    if value < 0:
        raise ScorecardError(f"{path}: every n is non-negative, got {value}")
    return value


def _optional_float(value, path: str):
    """``None`` or a finite float. A statistic over no rows is ``None``, never ``0.0``."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScorecardError(f"{path}: expected null or a number, got {value!r}")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ScorecardError(f"{path}: {value!r} is not a finite number")
    return number


def _sweep_banned_names(value, path: str) -> None:
    """Reject a §6.2 banned field name **at any depth**, whatever else the payload holds."""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in BANNED_FIELD_NAMES:
                raise ScorecardError(
                    f"{path}.{key}: {key!r} is a field name banned outright by FORECAST-SPEC "
                    "§6.2; the scorecard states realized error in the past tense and never "
                    "carries a probability, a percentile or an interval around a future value"
                )
            _sweep_banned_names(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _sweep_banned_names(item, f"{path}[{index}]")


def _check_stat(entry: dict, stat: str, count: str, path: str) -> None:
    """A statistic and its denominator, checked together — that is the whole point of ``n``."""
    value = _optional_float(entry[stat], f"{path}.{stat}")
    n = _non_negative_int(entry[count], f"{path}.{count}")
    if n == 0 and value is not None:
        raise ScorecardError(
            f"{path}.{stat} is {value} over {count}=0; a mean over no rows is null, never a "
            "number — an empty sample scores perfectly and is fake"
        )


def validate_scorecard(payload: dict) -> dict:
    """Raise :class:`ScorecardError` unless ``payload`` is exactly the locked shape.

    Exact key sets per block, not a superset check: an unexpected key is a contract change
    that someone has to make deliberately, and a missing one is a renderer reading
    ``undefined``.
    """
    # The banned-name sweep runs FIRST, at every depth, so a smuggled ``confidence_pct`` is
    # reported as the §6.2 violation it is rather than as an unexpected key somewhere.
    _sweep_banned_names(payload, "scorecard")
    _exact_keys(payload, _TOP_KEYS, "scorecard")

    meta = _exact_keys(payload["meta"], _META_KEYS, "scorecard.meta")
    if not isinstance(meta["never_interpolated"], bool) or not meta["never_interpolated"]:
        raise ScorecardError(
            "scorecard.meta.never_interpolated must be true; observations are never "
            "interpolated, and a payload that says otherwise is not this system's"
        )
    _non_negative_int(meta["tolerance_min"], "scorecard.meta.tolerance_min")
    if not isinstance(meta["models_included"], list) or not all(
        isinstance(name, str) and name for name in meta["models_included"]
    ):
        raise ScorecardError("scorecard.meta.models_included must be a list of model names")
    if not isinstance(meta["lead_hours"], list) or not all(
        isinstance(lead, int) and not isinstance(lead, bool) for lead in meta["lead_hours"]
    ):
        raise ScorecardError("scorecard.meta.lead_hours must be a list of integer lead hours")

    counts = _exact_keys(meta["counts"], _COUNT_KEYS, "scorecard.meta.counts")
    for key in _COUNT_KEYS:
        _non_negative_int(counts[key], f"scorecard.meta.counts.{key}")
    window = _exact_keys(meta["window"], _WINDOW_KEYS, "scorecard.meta.window")
    _non_negative_int(window["days_recorded"], "scorecard.meta.window.days_recorded")

    if not isinstance(payload["enough"], bool):
        raise ScorecardError("scorecard.enough must be a boolean")
    reason = payload["not_enough_reason"]
    if payload["enough"]:
        if reason is not None:
            raise ScorecardError("scorecard.not_enough_reason must be null when enough is true")
    elif not isinstance(reason, str) or not reason.strip():
        raise ScorecardError(
            "scorecard.not_enough_reason must state the count when enough is false; a thin "
            "record that does not say it is thin is the failure this field exists to prevent"
        )

    for block, keys in (
        ("by_series", _SERIES_KEYS),
        ("by_lead", _LEAD_KEYS),
        ("by_cycle", _CYCLE_KEYS),
        ("skips", _SKIP_KEYS),
    ):
        if not isinstance(payload[block], list):
            raise ScorecardError(f"scorecard.{block} must be a list")
        for index, entry in enumerate(payload[block]):
            _exact_keys(entry, keys, f"scorecard.{block}[{index}]")

    for index, entry in enumerate(payload["by_series"]):
        path = f"scorecard.by_series[{index}]"
        if entry["series_kind"] not in SERIES_KINDS:
            raise ScorecardError(f"{path}.series_kind must be one of {list(SERIES_KINDS)}")
        _check_stat(entry, "mae_f", "n", path)
        _check_stat(entry, "bias_f", "n", path)

    for index, entry in enumerate(payload["by_lead"]):
        path = f"scorecard.by_lead[{index}]"
        _non_negative_int(entry["lead_h"], f"{path}.lead_h")
        _check_stat(entry, "blend_mae_f", "n", path)
        _check_stat(entry, "best_single_mae_f", "n", path)
        _check_beaten(entry, path)

    for index, entry in enumerate(payload["by_cycle"]):
        path = f"scorecard.by_cycle[{index}]"
        for key in ("n_graded", "n_pending", "n_gap"):
            _non_negative_int(entry[key], f"{path}.{key}")
        _optional_float(entry["blend_mae_f"], f"{path}.blend_mae_f")
        _optional_float(entry["best_single_mae_f"], f"{path}.best_single_mae_f")
        _check_beaten(entry, path)

    for index, entry in enumerate(payload["skips"]):
        path = f"scorecard.skips[{index}]"
        _non_negative_int(entry["n_rows"], f"{path}.n_rows")
        if not isinstance(entry["reason"], str) or not entry["reason"].strip():
            raise ScorecardError(f"{path}.reason must be a non-empty sentence")

    streak_block = _exact_keys(payload["streaks"], _STREAK_KEYS, "scorecard.streaks")
    for key in _STREAK_KEYS:
        _non_negative_int(streak_block[key], f"scorecard.streaks.{key}")
    return payload


def _check_beaten(entry: dict, path: str) -> None:
    """``blend_beaten`` states the published comparison, or is null where none was made."""
    blend = entry["blend_mae_f"]
    best = entry["best_single_mae_f"]
    beaten = entry["blend_beaten"]
    if blend is None or best is None:
        if beaten is not None:
            raise ScorecardError(
                f"{path}.blend_beaten must be null where no comparison was made; a verdict "
                "without two means behind it is an unsupported claim"
            )
        return
    if not isinstance(beaten, bool):
        raise ScorecardError(f"{path}.blend_beaten must be a boolean, got {beaten!r}")
    if beaten != (float(blend) > float(best)):
        raise ScorecardError(
            f"{path}.blend_beaten is {beaten} but blend_mae_f {blend} versus "
            f"best_single_mae_f {best} says otherwise; a reader recomputing from the page "
            "must reach the verdict the page states"
        )


# --- the one composer, and the CLI above it ------------------------------------------------------


def _read_json_window(path, keys):
    """One nested ``window`` object out of a JSON document, **read-only**, or ``None``.

    Every failure — an absent file, unreadable bytes, a key that is not there, a value that
    is not an object — is ``None``. The window is a fact the page states about how the
    weights were fitted; where it cannot be read, the page says nothing rather than
    inventing days.
    """
    target = Path(path)
    if not target.exists():
        return None
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for key in keys:
        if not isinstance(document, dict) or key not in document:
            return None
        document = document[key]
    return dict(document) if isinstance(document, dict) else None


def weights_fitted_window(payload_path=None, results_path=None):
    """The days the served weights were fitted over, resolved in a deliberate order.

    1. ``data/forecast.json``'s ``meta.weights_source.window`` — the window the *served*
       cycle actually used, and the most specific answer available.
    2. Failing that, the **committed** ``data/results.json``'s ``meta.window`` — the window
       the backtest fitted over, which is where (1) came from in the first place.
    3. Failing both, ``None``.

    Step 2 is not a nicety. ``data/forecast.json`` is gitignored, so in a fresh clone step 1
    finds nothing, and the copy beside the scorecard is required to name the fitting window
    by month — a page that renders "fitted over: unknown" on a clone is a page that cannot
    say what it is comparing. ``data/results.json`` is committed and carries the same
    window, and it is opened here for reading only: nothing in this module writes it.
    """
    window = _read_json_window(
        FORECAST_PATH if payload_path is None else payload_path,
        ("meta", "weights_source", "window"),
    )
    if window is not None:
        return window
    return _read_json_window(
        RESULTS_PATH if results_path is None else results_path, ("meta", "window")
    )


def serve_scorecard(*, now=None, deadline_s=GRADE_DEADLINE_S, session_get=None) -> dict:
    """**record → grade → scorecard.** The one path the CLI and the endpoint both take.

    Because there is one composer, the number an operator reads at a terminal is the number
    the page renders; two entry points computing the same statistic two ways is how a page
    and a shell come to disagree about whether the blend won.

    ``now`` is read **here**, above the purity boundary, and handed down. Both passes are
    wrapped: the record pass is pure disk with no network and no deadline exposure, the
    grade pass is bounded, and **every** failure of either becomes a stated skip carried in
    the payload's own ``skips`` block. Nothing propagates — a page that renders the record
    it has, with the reason the rest is missing printed beside it, is worth more than an
    error page. The one exception is the payload failing :func:`validate_scorecard`, which
    is a bug in this module and is allowed to be loud.
    """
    moment = _as_utc(now_utc() if now is None else now)
    ledger = Path(LEDGER_PATH)
    pass_skips: list[dict] = []

    try:
        record(ledger_path=ledger)
    except Exception as exc:  # a record failure must never cost the page its history
        pass_skips.append(
            {
                "init_time": None,
                "reason": (
                    f"the record pass did not run ({type(exc).__name__}: {exc}); the scorecard "
                    "below is built from the rows already in the ledger"
                ),
                "n_rows": 0,
            }
        )

    try:
        outcome = grade(ledger, now=moment, deadline_s=deadline_s, session_get=session_get)
        pass_skips.extend(dict(skip) for skip in outcome["skips"])
    except Exception as exc:
        pass_skips.append(
            {
                "init_time": None,
                "reason": (
                    f"the grading pass stopped without writing anything ({type(exc).__name__}: "
                    f"{exc}); the affected rows are still pending and are counted as pending"
                ),
                "n_rows": 0,
            }
        )

    rows = load_ledger(ledger)
    meta = ledger_meta(rows, weights_fitted_window=weights_fitted_window())
    payload = scorecard(rows, moment, meta=meta)
    payload["skips"].extend(pass_skips)
    return validate_scorecard(payload)


#: Exit codes, so an operator's shell can tell the failures apart (``refresh.py:81`` shape).
EXIT_OK = 0
EXIT_CONTRACT = 1
EXIT_NO_PASS_SELECTED = 2
EXIT_EMPTY_JOIN = 3


def _parse_args(argv):
    """Four flags: which passes to run, and which two files to run them against."""
    parser = argparse.ArgumentParser(
        prog="python -m forecast.scorecard",
        description=(
            "Record the served forecast cycle into the append-only ledger, grade the rows "
            "whose observations have since been published, and print the realized-error "
            "scorecard. Both passes may be named in one run."
        ),
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="append the served cycle's prediction rows (pure disk; no network)",
    )
    parser.add_argument(
        "--grade",
        action="store_true",
        help="fetch observations once and append grade rows for the steps they cover",
    )
    parser.add_argument(
        "--ledger", type=Path, default=None, help=f"the ledger to append to (default {LEDGER_PATH})"
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=None,
        help=f"the served forecast document to record (default {FORECAST_PATH})",
    )
    return parser.parse_args(argv)


def _print_record(outcome: dict) -> None:
    """What the record pass wrote, and — when it wrote nothing — why not."""
    print(f"record  {outcome['ledger_path']}")
    print(f"  payload         : {outcome['payload_path']}")
    print(f"  cycle           : init={outcome['init_time']}  run={outcome['run_label']}")
    print(f"  rows_appended   : {outcome['recorded']}")
    if outcome["reason"]:
        print(f"  nothing written : {outcome['reason']}")


def _print_grade(outcome: dict) -> None:
    """What the grade pass scored, what it skipped, and the sentence for each skip."""
    window = outcome["window"]
    span = "none" if window is None else f"{window['start']} .. {window['end']}"
    print(f"grade   {outcome['ledger_path']}")
    print(f"  window          : {span}")
    print(
        f"  observations    : {outcome['obs_rows']}  offered={outcome['offered']}  "
        f"matched={outcome['matched']}"
    )
    print(
        f"  graded          : {outcome['graded']}  gap={outcome['gap']}  "
        f"pending={outcome['pending']}  outside_window={outcome['outside_window']}"
    )
    if outcome["reason"]:
        print(f"  nothing written : {outcome['reason']}")
    for skip in outcome["skips"]:
        print(
            f"  skipped         : {skip['n_rows']} row(s) at {skip['init_time']} — "
            f"{skip['reason']}"
        )


def _print_scorecard(payload: dict) -> None:
    """The record as it now stands. Every mean is printed beside its own denominator."""
    counts = payload["meta"]["counts"]
    print("scorecard")
    print(
        f"  counts          : cycles={counts['cycles_recorded']}  "
        f"rows={counts['rows_recorded']}  graded={counts['graded']}  "
        f"pending={counts['pending']}  gap={counts['gap']}  "
        f"outside_window={counts['rows_outside_grading_window']}"
    )
    print(f"  enough          : {payload['enough']}  ({payload['not_enough_reason']})")
    for entry in payload["by_series"]:
        print(
            f"  {entry['series']:<7} mae_f={entry['mae_f']}  bias_f={entry['bias_f']}  "
            f"n={entry['n']}"
        )
    for entry in payload["by_cycle"]:
        print(
            f"  cycle {entry['init_time']}  blend_mae_f={entry['blend_mae_f']} "
            f"(n_graded={entry['n_graded']})  best_single={entry['best_single_model']} "
            f"{entry['best_single_mae_f']}  blend_beaten={entry['blend_beaten']}"
        )
    for skip in payload["skips"]:
        print(f"  skip            : {skip['init_time']} — {skip['reason']}")


def main(argv=None) -> int:
    """Run the named passes, then print the record. ``0`` on success, named codes otherwise.

    The passes are the **same functions** the endpoint reaches through
    :func:`serve_scorecard`; this is a different way to start them, not a second
    implementation of them.
    """
    args = _parse_args(argv)
    if not args.record and not args.grade:
        print("nothing to do: name at least one pass, --record or --grade (both may be given)")
        print("  --record appends the served cycle; --grade scores what has since been observed")
        return EXIT_NO_PASS_SELECTED

    ledger = LEDGER_PATH if args.ledger is None else Path(args.ledger)
    payload_path = FORECAST_PATH if args.payload is None else Path(args.payload)
    moment = now_utc()

    if args.record:
        _print_record(record(payload_path=payload_path, ledger_path=ledger))
    if args.grade:
        try:
            _print_grade(grade(ledger, now=moment))
        except ScorecardError as exc:
            print("REFUSING TO GRADE: the join was offered rows and matched none of them")
            print(f"  {exc}")
            print("  Nothing was written. An empty join scores perfectly and is fake.")
            return EXIT_EMPTY_JOIN

    rows = load_ledger(ledger)
    window = weights_fitted_window(payload_path=payload_path)
    try:
        payload = validate_scorecard(
            scorecard(rows, moment, meta=ledger_meta(rows, weights_fitted_window=window))
        )
    except ScorecardError as exc:
        print("REFUSING TO PUBLISH: the scorecard failed its own contract")
        print(f"  {exc}")
        return EXIT_CONTRACT

    _print_scorecard(payload)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
