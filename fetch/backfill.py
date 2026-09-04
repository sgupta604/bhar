"""Ledger-driven backfill of the 30-day forecast window (T4, Stream 3).

`fetch_point` is the primitive; this module is the thin orchestrator around it.

**The append-only JSONL ledger at `data/raw/backfill_ledger.jsonl` is the single source
of truth.** `data/forecasts.parquet` and `data/coverage.json` are pure functions of it —
which is what makes the whole thing resumable after a crash and testable offline: every
derivation here runs on a ledger read from disk, never on live state held in memory.

Design points that are load-bearing, not stylistic:

* **`missing` is not an error.** `ArchiveMissing` (HTTP 404/403) counts into the coverage
  denominator and is **never retried** — a key that does not exist will not exist five
  seconds later (SPEC §11 R2). It never aborts the run.
* **Classification reads `__cause__`.** `fetch/grib.py:_get` wraps a
  `requests.RequestException` in a plain `RuntimeError` (`raise ... from last_exc`), so
  `except requests.RequestException` here would never fire. See `classify`.
* **A global deadline guard (900 s) makes SPEC §8's "under 15 minutes" enforced rather
  than hoped for.** A hung socket is otherwise 120 s x 3 attempts holding one of 8
  workers. On expiry: stop submitting, mark the rest `not_attempted`, write what exists,
  say so loudly.
* **8 workers is the spike-F2-validated number.** Decode is CPU-bound under the GIL;
  ~10x headroom against the budget. Do not raise it. `--executor process` is the named
  escape hatch if cfgrib ever misbehaves under threads.

**T4 FLAGS AND REPORTS. T5 DECIDES EXCLUSION (SPEC §5). T4 MUST NEVER DROP A MODEL.**
Every model appears in `coverage.json` and all of its successful rows reach
`forecasts.parquet`, whatever its coverage. If a model lands under the 90% floor that is
a RESULT TO REPORT, not a bug to fix — never widen the window, change the site, drop a
lead, or adjust a denominator to lift a number (SPEC §9 hard stop #3 / SPEC §10).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Executor, ProcessPoolExecutor
from concurrent.futures import ThreadPoolExecutor, wait
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from fetch.grib import MODELS, ArchiveMissing, _as_utc, fetch_point, valid_time
from fetch.schema import FORECAST_SCHEMA, write_parquet_checked
from fetch.window import LEADS_H, default_window, obs_bounds, work_items

# --- constants ---------------------------------------------------------------------------

LEDGER_PATH = Path("data/raw/backfill_ledger.jsonl")
FORECASTS_PATH = Path("data/forecasts.parquet")
COVERAGE_PATH = Path("data/coverage.json")
OBS_PATH = Path("data/obs.parquet")

DEFAULT_WORKERS = 8  # spike F2 validated. Do NOT raise it (GIL-bound decode).
DEADLINE_S = 900  # SPEC §8: the fetch completes in under 15 minutes, enforced.
BACKOFF_S = (2, 5)  # 3 attempts total: initial, +2 s, +5 s.
COVERAGE_FLOOR_PCT = 90.0  # exactly 90.0 PASSES; 89.99 flags.
MAX_ERROR_CHARS = 300
PROGRESS_EVERY = 50

STATUSES = ("success", "missing", "failed_network", "failed_decode", "not_attempted")
SKIP_STATUSES = ("success", "missing")  # resume rule: everything else is re-queued.

LEDGER_FIELDS = (
    "model",
    "init_time",
    "lead_h",
    "valid_time",
    "status",
    "temp_f",
    "grid_lat",
    "grid_lon",
    "distance_deg",
    "error",
    "attempted_at",
)

_LEDGER_LOCK = threading.Lock()


# --- time helpers ------------------------------------------------------------------------


def _iso(moment: datetime) -> str:
    """ISO-8601 UTC with a trailing `Z` (SPEC §2). A naive input is UTC, never local."""
    return _as_utc(moment).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_maybe(value) -> str | None:
    """`_iso` for datetimes, pass-through for strings/None — obs summaries vary."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, pd.Timestamp):
        return _iso(value.to_pydatetime())
    return str(value)


def _now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


# --- 3.1 the ledger ----------------------------------------------------------------------


LedgerKey = tuple[str, str, int]


def ledger_key(model: str, init_time, lead_h: int) -> LedgerKey:
    """`(model, init_time_iso, lead_h)` — the identity of one work item."""
    init_iso = init_time if isinstance(init_time, str) else _iso(init_time)
    return (str(model), init_iso, int(lead_h))


def make_record(
    item: tuple[str, datetime, int],
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> dict:
    """One ledger line. Every key present every time, in `LEDGER_FIELDS` order."""
    model, init, lead = item
    init_utc = _as_utc(init)
    result = result or {}
    record = {
        "model": str(model),
        "init_time": _iso(init_utc),
        "lead_h": int(lead),
        "valid_time": _iso(result.get("valid_time") or valid_time(init_utc, int(lead))),
        "status": status,
        "temp_f": None,
        "grid_lat": None,
        "grid_lon": None,
        "distance_deg": None,
        "error": None if error is None else error[:MAX_ERROR_CHARS],
        "attempted_at": _now_iso(),
    }
    if status == "success":
        record["temp_f"] = float(result["temp_f"])
        record["grid_lat"] = float(result["grid_lat"])
        record["grid_lon"] = float(result["grid_lon"])
        record["distance_deg"] = float(result["distance_deg"])
    return record


def append_ledger(path, record: dict) -> None:
    """Append one JSON line, flushed, under a module-level lock (the pool is concurrent)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record) + "\n"
    with _LEDGER_LOCK:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


def load_ledger(path) -> dict[LedgerKey, dict]:
    """Latest record per `(model, init_time_iso, lead_h)`.

    Tolerates a crash-truncated final line and blank lines — a half-written line is a
    normal consequence of killing the process, not a reason to lose the other 1439
    outcomes. A missing file is an empty ledger, not an error.
    """
    source = Path(path)
    if not source.exists():
        return {}
    records: dict[LedgerKey, dict] = {}
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
                key = ledger_key(record["model"], record["init_time"], record["lead_h"])
            except (KeyError, TypeError, ValueError):
                continue
            records[key] = record
    return records


def should_skip(record: dict | None) -> bool:
    """Resume rule: `success` and `missing` are settled; everything else is re-queued."""
    if not record:
        return False
    return record.get("status") in SKIP_STATUSES


def pending_items(
    items: list[tuple[str, datetime, int]], ledger: dict[LedgerKey, dict]
) -> list[tuple[str, datetime, int]]:
    """The work items not already settled by the ledger."""
    return [item for item in items if not should_skip(ledger.get(ledger_key(*item)))]


# --- 3.2 classification (research D3) ----------------------------------------------------


def classify(exc: BaseException) -> str:
    """Map an exception to a ledger status.

    Order matters, and rule 2 is the gotcha: `fetch/grib.py:_get` **wraps** a
    `requests.RequestException` in a plain `RuntimeError` with the original attached as
    `__cause__`, so `except requests.RequestException` in this module would never fire.
    A plain `RuntimeError` with no `RequestException` cause (an HTTP 500, a non-GRIB
    body) is `failed_decode` and must NEVER be called `missing` — misclassifying a
    server error as an archive hole silently deflates the numerator and fakes a clean
    run (SPEC §10).
    """
    if isinstance(exc, ArchiveMissing):
        return "missing"
    if isinstance(getattr(exc, "__cause__", None), requests.RequestException):
        return "failed_network"
    return "failed_decode"


# --- 3.3 attempt, retry, pool ------------------------------------------------------------


def attempt_item(
    item: tuple[str, datetime, int],
    fetcher=fetch_point,
    backoff: tuple[int, ...] = BACKOFF_S,
    sleep=time.sleep,
) -> dict:
    """Fetch one item with retries, returning the ledger record. Module-level: picklable.

    3 attempts total (initial + `len(backoff)` retries) for `failed_network` /
    `failed_decode` only. **`ArchiveMissing` is attempted exactly once.**
    """
    model, init, lead = item
    attempt = 0
    while True:
        try:
            result = fetcher(model, init, lead)
            return make_record(item, status="success", result=result)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a ledger row
            status = classify(exc)
            if status == "missing" or attempt >= len(backoff):
                return make_record(item, status=status, error=str(exc))
            sleep(backoff[attempt])
            attempt += 1


def _make_executor(kind: str, workers: int) -> Executor:
    """`thread` by default; `process` is the named cfgrib-under-threads escape hatch."""
    if kind == "thread":
        return ThreadPoolExecutor(max_workers=workers)
    if kind == "process":
        return ProcessPoolExecutor(max_workers=workers)
    raise ValueError(f"--executor must be 'thread' or 'process'; got {kind!r}")


def run_backfill(
    items: list[tuple[str, datetime, int]],
    *,
    fetcher=fetch_point,
    workers: int = DEFAULT_WORKERS,
    deadline_s: float = DEADLINE_S,
    ledger_path=LEDGER_PATH,
    executor: str = "thread",
    sleep=time.sleep,
    now=time.monotonic,
    backoff: tuple[int, ...] = BACKOFF_S,
    progress_every: int = PROGRESS_EVERY,
) -> dict:
    """Run `items` through `fetcher`, appending one ledger line per outcome.

    `fetcher`, `sleep` and `now` are injectable so no test touches the network or the
    wall clock. Returns a run summary: `workers`, `executor`, `elapsed_s`, `deadline_s`,
    `deadline_hit`, `total`, `attempted` and a count per status.
    """
    ledger = Path(ledger_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)

    counts = dict.fromkeys(STATUSES, 0)
    total = len(items)
    started = now()
    deadline_hit = False

    def expired() -> bool:
        return (now() - started) >= deadline_s

    def record(rec: dict) -> None:
        append_ledger(ledger, rec)
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1

    pending = deque(items)
    completed = 0
    in_flight_cap = max(workers * 2, workers + 1)

    with _make_executor(executor, workers) as pool:
        futures: dict = {}

        def top_up() -> bool:
            """Submit up to the in-flight cap. False once the deadline has expired."""
            nonlocal deadline_hit
            while pending and len(futures) < in_flight_cap:
                if expired():
                    deadline_hit = True
                    return False
                item = pending.popleft()
                futures[pool.submit(attempt_item, item, fetcher, backoff, sleep)] = item
            return True

        top_up()
        while futures:
            done, _ = wait(set(futures), return_when=FIRST_COMPLETED, timeout=1.0)
            for future in done:
                item = futures.pop(future)
                try:
                    record(future.result())
                except Exception as exc:  # a pool-level failure is still an outcome
                    record(make_record(item, status=classify(exc), error=str(exc)))
                completed += 1
                if progress_every and completed % progress_every == 0:
                    _print_progress(completed, total, now() - started, counts)
            if not deadline_hit and expired():
                deadline_hit = True
            if not deadline_hit:
                top_up()
            if deadline_hit and pending:
                _drain_not_attempted(pending, record)

        if pending:
            # The deadline fired before anything was in flight.
            deadline_hit = True
            _drain_not_attempted(pending, record)

    elapsed = now() - started
    _print_progress(completed, total, elapsed, counts)
    if deadline_hit:
        print(
            f"DEADLINE HIT: the {deadline_s:.0f} s budget (SPEC §8) expired after "
            f"{elapsed:.1f} s with {counts['not_attempted']} of {total} items "
            "unsubmitted. They are recorded 'not_attempted'; everything already "
            "fetched has been written. Re-run to resume — the ledger is the state."
        )

    summary = {
        "workers": workers,
        "executor": executor,
        "elapsed_s": round(float(elapsed), 3),
        "deadline_s": deadline_s,
        "deadline_hit": deadline_hit,
        "total": total,
        "attempted": completed,
    }
    summary.update(counts)
    return summary


def _drain_not_attempted(pending: deque, record) -> None:
    while pending:
        record(make_record(pending.popleft(), status="not_attempted"))


def _print_progress(completed: int, total: int, elapsed: float, counts: dict) -> None:
    tally = " ".join(f"{name}={counts.get(name, 0)}" for name in STATUSES)
    print(f"[{elapsed:7.1f}s] {completed}/{total} {tally}", flush=True)


# --- 3.4 coverage and parquet, derived purely from the ledger ----------------------------


def _as_map(records) -> dict[LedgerKey, dict]:
    """Accept either a `load_ledger` mapping or an iterable of records (latest wins)."""
    if isinstance(records, dict):
        return records
    out: dict[LedgerKey, dict] = {}
    for record in records:
        out[ledger_key(record["model"], record["init_time"], record["lead_h"])] = record
    return out


def _pct(success: int, denom: int) -> float:
    return 0.0 if denom <= 0 else success / denom * 100.0


def empty_obs_block() -> dict:
    """The `obs` block when the obs step did not run in this invocation."""
    return {"rows": 0, "distinct_hours": 0, "start": None, "end": None}


def coverage_from_ledger(
    records,
    *,
    models: tuple[str, ...],
    inits: list[datetime],
    leads: tuple[int, ...],
    obs: dict | None = None,
    run: dict | None = None,
    generated_at: str | None = None,
    threshold_pct: float = COVERAGE_FLOOR_PCT,
) -> dict:
    """Build `data/coverage.json` from the ledger. **The shape is LOCKED** — T5 reads it.

    Denominators come from the enumerated work items (360 per model, 120 per
    (model, lead)), **never** from how many rows happen to be in the ledger: a short
    ledger must report low coverage, not 100% of a small number.

    A model under the floor is flagged and reported in full. It is never dropped —
    T5 decides exclusion (SPEC §5).
    """
    ledger = _as_map(records)
    per_model_lead = len(inits)
    per_model = per_model_lead * len(leads)

    model_blocks: dict[str, dict] = {}
    for model in models:
        counts = dict.fromkeys(STATUSES, 0)
        by_lead: dict[str, dict] = {}
        for lead in leads:
            lead_success = 0
            for init in inits:
                record = ledger.get(ledger_key(model, init, lead))
                status = (record or {}).get("status", "not_attempted")
                if status not in counts:
                    status = "failed_decode"
                counts[status] += 1
                if status == "success":
                    lead_success += 1
            by_lead[str(int(lead))] = {
                "success": lead_success,
                "total": per_model_lead,
                "coverage_pct": round(_pct(lead_success, per_model_lead), 4),
            }
        pct = _pct(counts["success"], per_model)
        model_blocks[model] = {
            **counts,
            "total": per_model,
            "coverage_pct": round(pct, 4),
            "below_floor": pct < threshold_pct,  # exactly 90.0 PASSES
            "by_lead": by_lead,
        }

    obs_start, obs_end = obs_bounds(list(inits), tuple(leads))
    return {
        "generated_at": generated_at or _now_iso(),
        "window": {
            "start_init": _iso(min(inits)),
            "end_init": _iso(max(inits)),
            "n_inits": len(inits),
            "leads_h": [int(lead) for lead in leads],
            "models": list(models),
            "obs_start": _iso(obs_start),
            "obs_end": _iso(obs_end),
        },
        "denominators": {"per_model": per_model, "per_model_lead": per_model_lead},
        "threshold_pct": float(threshold_pct),
        "models": model_blocks,
        "obs": obs or empty_obs_block(),
        "run": {
            "workers": (run or {}).get("workers", DEFAULT_WORKERS),
            "executor": (run or {}).get("executor", "thread"),
            "elapsed_s": float((run or {}).get("elapsed_s", 0.0)),
            "deadline_s": (run or {}).get("deadline_s", DEADLINE_S),
            "deadline_hit": bool((run or {}).get("deadline_hit", False)),
        },
    }


def write_coverage(coverage: dict, path=COVERAGE_PATH) -> Path:
    """Write `coverage.json`, preserving an existing `obs` block this run did not refresh."""
    out = Path(path)
    if coverage.get("obs") in (None, empty_obs_block()) and out.exists():
        try:
            previous = json.loads(out.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = {}
        if isinstance(previous, dict) and isinstance(previous.get("obs"), dict):
            coverage = {**coverage, "obs": previous["obs"]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    return out


def print_coverage(coverage: dict) -> None:
    """SPEC §8: the coverage table is printed **and** stored."""
    denominators = coverage["denominators"]
    threshold = coverage["threshold_pct"]
    print(
        f"\ncoverage — denominator {denominators['per_model']} per model, "
        f"{denominators['per_model_lead']} per (model, lead); floor {threshold:.1f}%"
    )
    header = f"{'model':6} {'succ':>5} {'miss':>5} {'net':>5} {'dec':>5} {'n/a':>5} {'cov%':>7}"
    print(header)
    print("-" * len(header))
    for model, block in coverage["models"].items():
        print(
            f"{model:6} {block['success']:5d} {block['missing']:5d} "
            f"{block['failed_network']:5d} {block['failed_decode']:5d} "
            f"{block['not_attempted']:5d} {block['coverage_pct']:7.2f}"
        )
        leads = " ".join(
            f"f{lead:>3}={data['coverage_pct']:.1f}%" for lead, data in block["by_lead"].items()
        )
        print(f"       by lead: {leads}")
    for model, block in coverage["models"].items():
        if block["below_floor"]:
            print(
                f"FLAG: {model} coverage {block['coverage_pct']:.1f}% < "
                f"{threshold:.1f}% floor — T5 decides exclusion (SPEC §5). "
                "This is a RESULT, not a bug."
            )


def forecasts_from_ledger(records) -> pd.DataFrame:
    """The `status == "success"` rows as a SPEC §6 frame, deterministically sorted.

    `model` is a plain string column, **never** a `pandas.Categorical` — a Categorical
    round-trips through parquet as a pyarrow dictionary type and surprises T5.
    """
    rows = [
        record
        for record in _as_map(records).values()
        if record.get("status") == "success" and record.get("temp_f") is not None
    ]
    rows.sort(key=lambda r: (r["model"], r["init_time"], int(r["lead_h"])))
    frame = pd.DataFrame(
        {
            "model": [str(r["model"]) for r in rows],
            "init_time": pd.to_datetime(
                [r["init_time"] for r in rows], utc=True, format="ISO8601"
            ),
            "lead_h": pd.Series([int(r["lead_h"]) for r in rows], dtype="int32"),
            "valid_time": pd.to_datetime(
                [r["valid_time"] for r in rows], utc=True, format="ISO8601"
            ),
            "temp_f": pd.Series([float(r["temp_f"]) for r in rows], dtype="float64"),
        }
    )
    return frame.reset_index(drop=True)


def assert_every_model_present(frame: pd.DataFrame, models: tuple[str, ...]) -> None:
    """SPEC §9 hard stop #1: a model with zero successes across the whole window.

    That is a source returning nothing for the entire window — stop and report it by
    name. **HRRR merely having holes is NOT a hard stop**; only zero is.
    """
    present = set(frame["model"].tolist())
    for model in models:
        if model not in present:
            raise AssertionError(
                f"SPEC §9 hard stop #1: model {model!r} has ZERO successful rows across "
                "the entire window — the source returned nothing, so there is nothing to "
                "score. Reported, not fabricated. (Holes in a model that has data are a "
                "coverage RESULT, not this.)"
            )


def write_forecasts(frame: pd.DataFrame, path=FORECASTS_PATH, models: tuple[str, ...] = MODELS):
    """Assert every model has data, then write under `FORECAST_SCHEMA`."""
    assert_every_model_present(frame, models)
    return write_parquet_checked(
        frame, path, FORECAST_SCHEMA, min_rows=1, label="forecasts"
    )


# --- the obs step (lazily imported: fetch/obs.py is a sibling stream) --------------------


def run_obs_step(inits: list[datetime], leads: tuple[int, ...], out_path=OBS_PATH) -> dict | None:
    """Fetch and write observations. Returns the `coverage.json` `obs` block, or None."""
    try:
        from fetch.obs import fetch_obs, obs_summary, write_obs
    except ImportError as exc:
        print(f"WARN: obs step skipped — fetch/obs.py is not importable ({exc}).")
        return None
    start, end = obs_bounds(list(inits), tuple(leads))
    frame = fetch_obs(start, end)
    # No floor overrides: `fetch/obs.py` owns MIN_ROWS / MIN_DISTINCT_HOURS. Passing
    # looser numbers from here would weaken another stream's guard (SPEC §10).
    write_obs(frame, out_path)
    summary = obs_summary(frame)
    return {
        "rows": int(summary.get("rows", 0)),
        "distinct_hours": int(summary.get("distinct_hours", 0)),
        "start": _iso_maybe(summary.get("start")),
        "end": _iso_maybe(summary.get("end")),
    }


# --- CLI ----------------------------------------------------------------------------------


def _models_arg(text: str) -> tuple[str, ...]:
    chosen = tuple(part.strip().lower() for part in text.split(",") if part.strip())
    unknown = [model for model in chosen if model not in MODELS]
    if not chosen or unknown:
        raise argparse.ArgumentTypeError(
            f"SPEC §3 names exactly {MODELS}; got unknown {unknown or list(chosen)}"
        )
    return chosen


def _leads_arg(text: str) -> tuple[int, ...]:
    try:
        leads = tuple(int(part.strip()) for part in text.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--leads must be a comma list of hours: {exc}") from exc
    if not leads:
        raise argparse.ArgumentTypeError("--leads must name at least one lead hour")
    return leads


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fetch.backfill",
        description="Backfill the 30-day forecast window into a resumable JSONL ledger.",
    )
    parser.add_argument("--models", type=_models_arg, default=MODELS)
    parser.add_argument("--days", type=int, default=30, help="n_inits = days * 4")
    parser.add_argument("--leads", type=_leads_arg, default=LEADS_H)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--deadline", type=float, default=DEADLINE_S)
    parser.add_argument("--executor", choices=("thread", "process"), default="thread")
    parser.add_argument("--obs-only", action="store_true")
    parser.add_argument("--forecasts-only", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="ignore the existing ledger")
    parser.add_argument("--out", default=str(FORECASTS_PATH))
    parser.add_argument("--coverage-out", default=str(COVERAGE_PATH))
    parser.add_argument("--ledger", default=str(LEDGER_PATH))
    parser.add_argument("--obs-out", default=str(OBS_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.obs_only and args.forecasts_only:
        raise SystemExit("--obs-only and --forecasts-only are mutually exclusive")

    models = tuple(args.models)
    leads = tuple(args.leads)
    _, inits = default_window(n_inits=max(1, args.days * 4))
    items = work_items(inits, models, leads)

    print(
        f"window {_iso(min(inits))} .. {_iso(max(inits))} — {len(inits)} inits x "
        f"{len(models)} models x {len(leads)} leads = {len(items)} items"
    )

    run_summary: dict = {}
    if not args.obs_only:
        ledger = {} if args.fresh else load_ledger(args.ledger)
        todo = pending_items(items, ledger)
        print(f"ledger {args.ledger}: {len(ledger)} records, {len(todo)} items to attempt")
        run_summary = run_backfill(
            todo,
            workers=args.workers,
            deadline_s=args.deadline,
            ledger_path=args.ledger,
            executor=args.executor,
        )

    obs_block = None
    if not args.forecasts_only:
        obs_block = run_obs_step(inits, leads, args.obs_out)

    records = load_ledger(args.ledger)
    coverage = coverage_from_ledger(
        records, models=models, inits=inits, leads=leads, obs=obs_block, run=run_summary
    )
    # Report BEFORE the hard-stop assert: a run that trips SPEC §9 must still leave the
    # coverage table and coverage.json behind, or the morning starts with no evidence.
    print_coverage(coverage)
    written = write_coverage(coverage, args.coverage_out)
    print(f"wrote {written}")

    if not args.obs_only:
        frame = forecasts_from_ledger(records)
        out = write_forecasts(frame, args.out, models)
        print(f"wrote {out} ({len(frame)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
