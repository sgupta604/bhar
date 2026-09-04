"""The **one** CLI that produces ``data/forecast.json`` (F3, Stream 5).

``uv run --no-sync python -m forecast.refresh`` walks the whole path end to end::

    load_fitted_weights -> select_cycle -> build_forecast_document -> validate -> write_atomic

**This module supersedes ``forecast/live.py``'s ``__main__`` harness** — FR11's manual-run
harness, which fetched a cycle into the disk cache and printed a tally but wrote no payload.
``forecast/live.py`` is **left unmodified**: its harness stays where it is, still usable for a
cache warm-up, and this module is the real CLI. There is **no third CLI surface**; the only
other entry point in the package is ``forecast/make_fixture.py``, which writes the loudly
synthetic fixture and is reached from here through ``--fixture``.

Properties this module is required to hold:

* **The one wall clock.** Every other module in F3 takes its instants as arguments — that is
  what makes the cycle ladder, the weight age and the staleness banner exercisable at frozen
  times with no mocking. :func:`now_utc` is read **once** in :func:`main` and threaded through
  as ``now``. ``datetime.now(timezone.utc)``, aware, never a naive local reading.
* **One atomic write, shared.** The write goes through
  :func:`forecast.contract.write_atomic`, which validates *before* it opens anything and puts
  its scratch file in the **target's own directory** (``data/.forecast.json.tmp``) because
  ``os.replace`` is only atomic within one filesystem. No second implementation lives here.
  **Nothing is written on failure** — not a truncated file, not a leftover temp file.
* **No fallback, by design (FORECAST-SPEC §16 R3).** When ``data/results.json`` is absent or
  fails its contract, this CLI produces no document and writes nothing. There is no default
  vector, no equal-weight substitute and no reuse of a previously written file: a blend
  nobody fitted, served under the fitted blend's banner, is worse than no forecast at all.
* **A minimal flag surface: ``--fixture``, ``--cache-root``, ``--out``.** In particular there
  is **no ``--init`` flag**. Hunting a different cycle until the numbers look better is
  exactly the tuning FORECAST-SPEC §15 bans, and F2 declined the same flag for the same
  reason. ``--refetch-missing`` and ``--workers`` are absent for the same reason: they are
  knobs on the honesty of the run, not conveniences.
* **No traceback for an expected failure.** A missing backtest, an unpublished cycle and a
  contract violation are all *operating conditions*. Each is caught, reported in one readable
  block naming the path involved, and turned into an exit code.
* **No bare ``assert``** — ``python -O`` deletes assertions, so every guard raises.

Order note (a deliberate deviation from the plan's left-to-right arrow): the fitted weights
are loaded **first**, before the cycle is selected. Both orders produce the same document, but
this one fails in milliseconds and touches no network when the backtest output is missing,
rather than after ~64 archive requests.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from fetch.grib import fetch_point
from forecast import make_fixture
from forecast.build import build_forecast_document
from forecast.contract import ContractError, write_atomic
from forecast.live import LIVE_ROOT, Fetcher, NoCycleAvailable, select_cycle
from forecast.weights import PRODUCED_BY, load_fitted_weights

__all__ = [
    "DEFAULT_OUTPUT",
    "FETCHER",
    "RESULTS_PATH",
    "main",
    "now_utc",
    "temp_path_for",
]

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where the served payload lands. Gitignored — it is regenerated, never committed.
DEFAULT_OUTPUT = REPO_ROOT / "data" / "forecast.json"

#: The backtest output the fitted weights come from, and the only source of them.
RESULTS_PATH = REPO_ROOT / "data" / "results.json"

#: The archive reader handed to :func:`forecast.live.select_cycle`. A module attribute rather
#: than a CLI flag: a test replaces it with a fetcher that raises, so a run that still
#: succeeds off the populated cache has demonstrably consulted no network at all.
FETCHER: Fetcher = fetch_point

#: Exit codes, so an operator's shell can tell the three expected failures apart.
EXIT_OK = 0
EXIT_CONTRACT = 1
EXIT_NO_WEIGHTS = 2
EXIT_NO_CYCLE = 3


def now_utc() -> datetime:
    """The single wall-clock reading in F3: an aware UTC instant.

    A named function, not an inline call, so a test can freeze the instant without touching
    ``datetime`` itself and without this module growing a ``--now`` flag.
    """
    return datetime.now(timezone.utc)


def temp_path_for(target: Path) -> Path:
    """The scratch file :func:`forecast.contract.write_atomic` writes through.

    A dotfile **beside** the target, in the target's own directory: ``os.replace`` is atomic
    only within a single filesystem, so a temp file under ``/tmp`` would turn the rename into
    a copy and reintroduce the torn-file window this exists to close.
    """
    target = Path(target)
    return target.parent / f".{target.name}.tmp"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """The whole flag surface. Three flags, and deliberately not a fourth — see the docstring."""
    parser = argparse.ArgumentParser(
        prog="python -m forecast.refresh",
        description=(
            "Refresh data/forecast.json: fit-time weights from data/results.json applied to "
            "one live NOAA cycle. Supersedes forecast/live.py's manual-run harness."
        ),
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help=(
            "write the loudly synthetic fixture instead: no network, no data/results.json "
            "and no cache are consulted"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=LIVE_ROOT,
        help=f"the on-disk cycle cache to read and fill (default: {LIVE_ROOT})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"where the document is written (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args(argv)


def _report_missing_weights(target: Path, detail: str) -> None:
    """Say which file is missing, what makes it, and that nothing was substituted."""
    print(f"REFUSING TO BUILD: the fitted weights at {target} are unusable")
    print(f"  {detail}")
    print(f"  It is produced by: {PRODUCED_BY}")
    print(
        "  There is no fallback by design (FORECAST-SPEC §16 R3): no default vector, no "
        "equal-weight substitute, and no reuse of a previously written forecast.json. "
        "Nothing was written."
    )


def _fitted_vector_lines(document: dict) -> list[str]:
    """One line per fitted lead, showing the vector the rows banded onto it actually used."""
    lines: list[str] = []
    for lead in document["meta"]["weights_source"]["fitted_leads"]:
        row = next(
            (r for r in document["forecast"] if r["weights_fitted_at_lead_h"] == lead), None
        )
        if row is None:
            lines.append(f"  fitted {lead:>2}h  no served row bands onto this vector")
            continue
        vector = "  ".join(f"{name} {value:g}" for name, value in row["weights"].items())
        lines.append(f"  fitted {lead:>2}h  {vector}")
    return lines


def _print_run(document: dict, out: Path) -> None:
    """The recorded facts of the run, so an operator can read what was served."""
    meta = document["meta"]
    cycle_block = meta["cycle"]
    source_block = meta["weights_source"]
    rows = document["forecast"]

    print(f"wrote {out}")
    print(
        f"  cycle={cycle_block['run_label']}  init={cycle_block['init_time']}  "
        f"target={cycle_block['target_init_time']}  age_minutes={cycle_block['age_minutes']}"
    )
    print(
        f"  is_stale={cycle_block['is_stale']}  "
        f"cycles_fallen_back={cycle_block['cycles_fallen_back']}"
    )
    print(f"  stale_reason={cycle_block['stale_reason']}")
    print(
        f"  rows={len(rows)}  gaps={len(document['gaps'])}  "
        f"extrapolated_rows={sum(1 for r in rows if r['is_extrapolated_lead'])}  "
        f"step_h={meta['step_h']}  horizon_h={meta['horizon_h']}"
    )
    print(
        f"  weights={source_block['path']}  generated_at={source_block['generated_at']}  "
        f"weights_age_days={source_block['weights_age_days']}"
    )
    for line in _fitted_vector_lines(document):
        print(line)
    print(
        f"  models_included={meta['models_included']}  source={meta['source']}  "
        f"is_synthetic={meta['is_synthetic']}"
    )


def main(argv: list[str] | None = None) -> int:
    """Refresh the served forecast document. ``0`` on success, non-zero on a named failure."""
    args = _parse_args(argv)
    out = Path(args.out)

    # The one wall-clock reading in the whole feature, threaded through from here.
    now = now_utc()

    if args.fixture:
        document = make_fixture.build_fixture_document(
            generated_at=now, init_time=make_fixture.default_init_time(now)
        )
    else:
        try:
            fitted = load_fitted_weights(RESULTS_PATH, now)
        except ContractError as exc:
            _report_missing_weights(RESULTS_PATH, str(exc))
            return EXIT_NO_WEIGHTS

        try:
            cycle_result = select_cycle(now, fetcher=FETCHER, cache_root=Path(args.cache_root))
        except NoCycleAvailable as exc:
            print("REFUSING TO BUILD: no candidate cycle is published, so nothing was written")
            print(f"  {exc}")
            return EXIT_NO_CYCLE

        try:
            document = build_forecast_document(cycle_result, fitted, generated_at=now)
        except ContractError as exc:
            print(f"REFUSING TO WRITE: {out}")
            print(f"  the assembled document violates the FORECAST-SPEC §9 contract: {exc}")
            return EXIT_CONTRACT

    try:
        write_atomic(document, out, tmp=temp_path_for(out))
    except ContractError as exc:
        print(f"REFUSING TO WRITE: {out}")
        print(f"  the assembled document violates the FORECAST-SPEC §9 contract: {exc}")
        return EXIT_CONTRACT

    _print_run(document, out)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
