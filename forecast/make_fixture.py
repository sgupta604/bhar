"""Deterministic, loudly synthetic ``forecast.json`` — the forward page's insurance artifact.

Run it with::

    uv run python -m forecast.make_fixture --out data/forecast.fixture.json

**This payload is fake and says so at every level** (FORECAST-SPEC §15, D-F3-G).
``meta.is_synthetic`` is a real JSON ``true``, ``meta.source`` is ``"synthetic_fixture"``,
the site name carries ``(SYNTHETIC FIXTURE)``, ``meta.weights_source.path`` states in words
that no ``results.json`` was read, and every temperature and every skill number is a
repdigit — 55.5555 / 66.6666 / 77.7777 / 88.8888, 5.55 / 6.66 / 7.77 / 8.88 — so that a
reader who sees this page cannot mistake it for a real forecast at four in the afternoon.
Models never disagree by 33 °F.

Why the file exists at all
--------------------------
F2's live run came back 64/64 clean: not one archive miss. So the **gap branch** and the
**extrapolated-lead branch** of the payload have never once run against real data, and the
page that renders them has never been exercised. This document therefore *deliberately*
contains both:

* two ``gaps`` entries — one mid-grid model absence, one past a model's own horizon — with
  ``missing_models`` UPPERCASE, and
* seven forecast rows at leads beyond the longest fitted lead, flagged
  ``is_extrapolated_lead: true``.

It also declares a cycle fallback, so the stale treatment is renderable too. All of it
passes **the same** :func:`forecast.contract.validate_forecast` the real payload does.

What this module depends on
---------------------------
Nothing. No network, no ``data/live/`` cache, no ``data/results.json``, no fitted-weights
module — the whole point of a fixture is that it still builds when every one of those is
gone. The only import out of the standard library is :mod:`forecast.contract`.

Purity
------
``generated_at`` and ``init_time`` arrive as arguments; this module never reads a wall
clock. Only :func:`main` supplies defaults, from ``datetime.now(timezone.utc)``. Two calls
with the same arguments produce byte-identical output.

Numbers, and how they are made
------------------------------
Members are fabricated on a repdigit base per model plus a repdigit sawtooth, then stored
**rounded to 4 dp**. ``blend_f`` is computed from *those stored values* and serialized
unrounded, and ``member_spread_f`` is ``max − min`` of the same stored values (D-F3-C).
That makes §9 rule 6 and rule 6b true by construction rather than by luck: the identity the
validator recomputes is the identity that produced the number.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forecast.contract import (
    STALE_AGE_MINUTES,
    ContractError,
    band_for_lead,
    is_extrapolated_lead,
    write_atomic,
)

__all__ = ["build_fixture_document", "default_init_time", "main", "write_fixture"]

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Default output. Deliberately **not** ``data/forecast.json``: the served file is the live
#: payload, and quietly replacing it with a fixture is the §11 failure ("never silently fall
#: back to the synthetic fixture") with a filename on it.
DEFAULT_OUTPUT = REPO_ROOT / "data" / "forecast.fixture.json"

#: Canonical model order, UPPERCASE throughout the payload.
MODELS: tuple[str, ...] = ("HRRR", "GFS", "NAM", "NBM")

#: The marker that must survive every rename of this file.
SYNTHETIC_MARKER = " (SYNTHETIC FIXTURE)"

SITE = {
    "id": "KOMA",
    "iem_station": "OMA",
    "name": "Omaha Eppley Airfield" + SYNTHETIC_MARKER,
    "lat": 41.3032,
    "lon": -95.8941,
    "station_elev_m": 295.7,
}

STEP_H = 3
HORIZON_H = 48
FITTED_LEADS: tuple[int, ...] = (6, 12, 24)

#: Model runs are six hours apart, so one cycle of fallback is six hours earlier.
CYCLE_INTERVAL_H = 6
CYCLES_FALLEN_BACK = 1

#: The two declared holes. Leads here appear in ``gaps`` and nowhere else; every other lead
#: on the grid appears in ``forecast`` and nowhere else (§9 rule 8).
GAPS: dict[int, tuple[tuple[str, ...], str]] = {
    21: (("NAM",), "fabricated gap: NAM absent from archive"),
    48: (("NAM", "NBM"), "beyond model horizon"),
}

#: Weight vectors, one per fitted lead. On the 0.1 grid (SPEC §5) and summing to 1.0.
#: When a model is missing the whole step becomes a gap — weights are never rescaled over a
#: subset of models, because that would publish a blend nobody ever fitted.
BAND_WEIGHTS: dict[int, dict[str, float]] = {
    6: {"HRRR": 0.5, "GFS": 0.1, "NAM": 0.0, "NBM": 0.4},
    12: {"HRRR": 0.4, "GFS": 0.2, "NAM": 0.1, "NBM": 0.3},
    24: {"HRRR": 0.2, "GFS": 0.3, "NAM": 0.1, "NBM": 0.4},
}

#: Repdigit base temperature per model, degrees F. 33 °F apart on purpose.
MEMBER_BASE: dict[str, float] = {
    "HRRR": 66.6666,
    "GFS": 77.7777,
    "NAM": 88.8888,
    "NBM": 55.5555,
}

#: A repdigit sawtooth, so every fabricated temperature stays a repdigit at 4 dp.
MEMBER_WAVE: tuple[float, ...] = (0.0, 1.1111, 2.2222, 3.3333, 2.2222, 1.1111)

#: Phase offset into the sawtooth per model, so member spread varies across the grid
#: instead of being a constant that would hide a spread bug.
MEMBER_PHASE: dict[str, int] = {"HRRR": 0, "GFS": 2, "NAM": 4, "NBM": 3}

#: Fabricated backtest errors, degrees F. Repdigits (D3). The 24 h lead is a deliberate
#: LOSS: FORECAST-SPEC §15 requires a zero or negative improvement to render honestly, and
#: a fixture in which the blend always wins would let that path go unseen.
SKILL_MAE: dict[int, dict[str, object]] = {
    6: {"blend": 5.55, "in_sample": 4.44, "best_model": "HRRR", "best": 6.66},
    12: {"blend": 6.66, "in_sample": 5.55, "best_model": "NBM", "best": 7.77},
    24: {"blend": 9.99, "in_sample": 7.77, "best_model": "GFS", "best": 8.88},
}

SKILL_N_TEST = 44
SKILL_INDEPENDENT_DAYS = 33

#: Fixed fabricated window, independent of the injected instants so the document stays
#: deterministic.
FABRICATED_WINDOW = {
    "start": "2026-08-05T00:00:00Z",
    "end": "2026-09-04T00:00:00Z",
    "days": 30,
}
FABRICATED_SPLIT = {"method": "chronological", "train_days": 20, "test_days": 10}
FABRICATED_WEIGHTS_STAMP = "2026-09-04T12:53:01Z"

#: NOT ``data/results.json``. These weights were typed into this file by hand, and the
#: payload has to say so rather than borrow the real artifact's provenance.
WEIGHTS_SOURCE_PATH = (
    "fabricated in forecast/make_fixture.py — no results.json was read, and these weights "
    "were never fitted against observations"
)

STALE_REASON = (
    "fell back 1 cycle: fabricated for the synthetic fixture so the stale treatment can be "
    "rendered with no network"
)

SKILL_NOTE = (
    "FABRICATED. Nothing here was measured. The real page reports the 30-day backtest in "
    "the past tense; this document exists only so the forecast view can be rendered with "
    "no network."
)


def _aware_utc(value: datetime, name: str) -> datetime:
    """Return ``value`` as an aware UTC instant, refusing a naive one.

    A naive datetime here would serialize without the trailing ``Z`` the contract requires,
    and would silently mean local time on somebody's laptop. UTC everywhere.
    """
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{name} must be timezone-aware UTC (datetime.now(timezone.utc)); a naive "
            "datetime means local time on whichever machine ran this"
        )
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    """ISO-8601 UTC to the second with a trailing ``Z`` — the contract's only stamp form."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_init_time(generated_at: datetime) -> datetime:
    """The most recent six-hourly cycle at or before ``generated_at``.

    Pure: derived from the instant it is handed. :func:`main` is the only caller that turns
    a wall clock into that instant.
    """
    moment = _aware_utc(generated_at, "generated_at")
    return moment.replace(
        hour=(moment.hour // CYCLE_INTERVAL_H) * CYCLE_INTERVAL_H,
        minute=0,
        second=0,
        microsecond=0,
    )


def step_grid() -> list[int]:
    """Every lead on the published step grid, ``step_h`` out to ``horizon_h`` inclusive."""
    return list(range(STEP_H, HORIZON_H + 1, STEP_H))


def _members_at(lead_h: int) -> dict[str, float]:
    """Fabricated member temperatures, stored rounded to 4 dp (D-F3-C)."""
    slot = lead_h // STEP_H
    return {
        model: round(
            MEMBER_BASE[model] + MEMBER_WAVE[(slot + MEMBER_PHASE[model]) % len(MEMBER_WAVE)],
            4,
        )
        for model in MODELS
    }


def _forecast_row(lead_h: int, init_time: datetime) -> dict:
    fitted_at = band_for_lead(lead_h, FITTED_LEADS)
    weights = {model: BAND_WEIGHTS[fitted_at][model] for model in MODELS}
    members = _members_at(lead_h)

    # Computed from the STORED member values, never transcribed: §9 rule 6 has to be true by
    # construction, and a hand-typed blend is a number with no provenance.
    blend_f = sum(weights[model] * members[model] for model in MODELS)
    spread_f = max(members.values()) - min(members.values())

    return {
        "valid_time": _stamp(init_time + timedelta(hours=lead_h)),
        "lead_h": lead_h,
        "blend_f": blend_f,
        "weights": weights,
        "weights_fitted_at_lead_h": fitted_at,
        "is_extrapolated_lead": is_extrapolated_lead(lead_h, FITTED_LEADS),
        "members": members,
        "member_spread_f": spread_f,
    }


def _gap_entry(lead_h: int, init_time: datetime) -> dict:
    missing, reason = GAPS[lead_h]
    return {
        "valid_time": _stamp(init_time + timedelta(hours=lead_h)),
        "lead_h": lead_h,
        "missing_models": list(missing),
        "reason": reason,
    }


def _skill_block() -> dict:
    by_lead = []
    for lead_h in FITTED_LEADS:
        numbers = SKILL_MAE[lead_h]
        blend_mae = float(numbers["blend"])
        best_mae = float(numbers["best"])
        by_lead.append(
            {
                "lead_h": lead_h,
                "blend_mae": blend_mae,
                "blend_mae_in_sample": float(numbers["in_sample"]),
                "best_single_model": str(numbers["best_model"]),
                "best_single_mae": best_mae,
                "improvement_pct": round((best_mae - blend_mae) / best_mae * 100.0, 4),
                "n_test": SKILL_N_TEST,
                "independent_days_approx": SKILL_INDEPENDENT_DAYS,
            }
        )
    return {
        "basis": "historical_out_of_sample",
        "window": dict(FABRICATED_WINDOW),
        "note": SKILL_NOTE,
        "by_lead": by_lead,
    }


def build_fixture_document(generated_at: datetime, init_time: datetime) -> dict:
    """Fabricate a complete FORECAST-SPEC §9 document. Pure, and loudly synthetic.

    Both instants are injected. Nothing on disk and nothing on the network is consulted, so
    this succeeds on a machine that has never fetched a single GRIB file.
    """
    generated = _aware_utc(generated_at, "generated_at")
    init = _aware_utc(init_time, "init_time")

    # A fallback moves to an EARLIER cycle, so the cycle we wanted is later than the one we
    # got. Always set here: the fixture exists partly to make the stale treatment visible.
    target_init = init + timedelta(hours=CYCLE_INTERVAL_H * CYCLES_FALLEN_BACK)
    age_minutes = round(max(0.0, (generated - init).total_seconds() / 60.0), 1)
    is_stale = CYCLES_FALLEN_BACK > 0 or age_minutes > STALE_AGE_MINUTES

    gap_leads = sorted(GAPS)
    row_leads = [lead for lead in step_grid() if lead not in GAPS]

    return {
        "meta": {
            "site": dict(SITE),
            "variable": "2m_temperature",
            "units": "degF",
            "cycle": {
                "init_time": _stamp(init),
                "run_label": f"{init:%H}z",
                "target_init_time": _stamp(target_init),
                "fetched_at": _stamp(generated),
                "age_minutes": age_minutes,
                "is_stale": is_stale,
                "stale_reason": STALE_REASON if is_stale else None,
                "cycles_fallen_back": CYCLES_FALLEN_BACK,
            },
            "weights_source": {
                "path": WEIGHTS_SOURCE_PATH,
                "generated_at": FABRICATED_WEIGHTS_STAMP,
                "weights_age_days": 0,
                "window": dict(FABRICATED_WINDOW),
                "split": dict(FABRICATED_SPLIT),
                "fitted_leads": list(FITTED_LEADS),
            },
            "models_included": list(MODELS),
            "horizon_h": HORIZON_H,
            "step_h": STEP_H,
            "source": "synthetic_fixture",
            "generated_at": _stamp(generated),
            "is_synthetic": True,
        },
        "forecast": [_forecast_row(lead, init) for lead in row_leads],
        "gaps": [_gap_entry(lead, init) for lead in gap_leads],
        "skill": _skill_block(),
    }


def write_fixture(
    path: str | Path,
    generated_at: datetime,
    init_time: datetime,
    tmp: Path | None = None,
) -> dict:
    """Build, **validate**, then atomically write the fixture. Returns the document.

    The write goes through :func:`forecast.contract.write_atomic` — the one shared
    implementation, which validates before it opens anything, so a document that fails the
    contract leaves neither a target file nor a temp file behind.
    """
    document = build_fixture_document(generated_at=generated_at, init_time=init_time)
    write_atomic(document, Path(path), tmp=tmp)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. ``0`` on success; ``1`` printing REFUSING TO WRITE on a violation."""
    parser = argparse.ArgumentParser(
        prog="python -m forecast.make_fixture",
        description=(
            "Write a loudly synthetic forecast.json fixture. Fake data, flagged as fake: "
            "is_synthetic true, source synthetic_fixture, repdigit temperatures."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    generated_at = datetime.now(timezone.utc)
    init_time = default_init_time(generated_at)

    try:
        document = write_fixture(args.out, generated_at=generated_at, init_time=init_time)
    except ContractError as exc:
        print(f"REFUSING TO WRITE: {args.out}")
        print(f"  the generated document violates the FORECAST-SPEC §9 contract: {exc}")
        return 1

    meta = document["meta"]
    rows = document["forecast"]
    extrapolated = [row for row in rows if row["is_extrapolated_lead"]]
    print(f"wrote {args.out}")
    print(f"  is_synthetic={meta['is_synthetic']}  source={meta['source']}")
    print(f"  site={meta['site']['name']}")
    print(
        f"  cycle={meta['cycle']['run_label']} {meta['cycle']['init_time']}  "
        f"is_stale={meta['cycle']['is_stale']}"
    )
    print(
        f"  rows={len(rows)}  gaps={len(document['gaps'])}  "
        f"extrapolated_rows={len(extrapolated)}  "
        f"grid={STEP_H}h to {HORIZON_H}h"
    )
    print("  every temperature and every skill number in this file is fabricated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
