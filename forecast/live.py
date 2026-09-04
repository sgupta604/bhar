"""FORECAST-SPEC §5 live layer: the derived step grid and the on-disk cycle cache (F2).

This module holds the pieces that decide **which leads are worth asking for** and **what
is already on disk**. It writes nothing outside `data/live/`.

Invariants this module is required to hold:

* **The grid is DERIVED, never copied.** `PROBE_PUBLISHED_LEADS` is the probe's observation
  written into code as data; `step_grid()` computes the intersection across all four models.
  `3` and `48` are a candidate *step* and a candidate *ceiling* — never loop literals that
  hand back a pre-decided answer. See `.claude/features/forecast-live-fetch/F2-findings.md` §2.
* **The cache directory IS the ledger.** No manifest, no index: a cache hit is a pure
  function of what is on disk. `missing` outcomes are cached alongside `success` ones, which
  is what makes the zero-network re-run real.
* **A damaged cache file is a MISS, never a crash.** Absent, unparseable, truncated or
  schema-incomplete all return `None` from `read_cached`.
* **Writes are atomic** — temp file in the same directory plus `os.replace`, mirroring
  `score/run.py:59 write_atomic`.
* **`data/live/` is the only place F2 writes.** The sibling entries in `data/` are symlinks
  into a different checkout; `_guard_cache_root` refuses to write through one.
* **UTC everywhere**, ISO-8601 with a trailing `Z` on disk. Temperatures are degrees F
  exactly as `fetch.grib.fetch_point` returns them — no unit conversion happens in this
  package, and none may ever be added here (`fetch.grib.decode_point` owns it).
* **No bare `assert`** — `python -O` strips them. Real exceptions citing their clause only.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fetch.grib import MODELS, ArchiveMissing, _as_utc, valid_time
from forecast import cycle

# --- the probe, written into code as data (plan §2.2) -----------------------------------

PROBE_INIT = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

#: Leads 0-48 h observed as PUBLISHED for `PROBE_INIT`, one HEAD request per lead
#: (196 in total). NAM is hourly to f036 then 3-hourly; NBM publishes no f000.
PROBE_PUBLISHED_LEADS: dict[str, tuple[int, ...]] = {
    "hrrr": tuple(range(0, 49)),  # 49/49
    "gfs": tuple(range(0, 49)),  # 49/49
    "nam": tuple(range(0, 37)) + (39, 42, 45, 48),  # 41/49
    "nbm": tuple(range(1, 49)),  # 48/49 — NO f000
}

#: FORECAST-SPEC §5 *candidates*, subject to the probe. Never used as loop literals.
CANDIDATE_STEP_H = 3
CANDIDATE_MAX_LEAD_H = 48

# --- the cache ---------------------------------------------------------------------------

LIVE_ROOT = Path("data/live")

#: The two settled statuses, mirroring `fetch/backfill.py:70 SKIP_STATUSES`.
CACHE_STATUSES = ("success", "missing")

#: The locked cache record schema — see F2-findings.md "Cache record schema".
RECORD_FIELDS = (
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
    "fetched_at",
)

#: Fields serialized as ISO-8601 UTC and deserialized back to tz-aware datetimes.
DATETIME_FIELDS = ("init_time", "valid_time", "fetched_at")

_REPO_ROOT = Path(__file__).resolve().parent.parent


# --- time ---------------------------------------------------------------------------------


def _iso(moment: datetime) -> str:
    """ISO-8601 UTC with a trailing `Z` (SPEC §2) — `fetch/backfill.py:90` house style."""
    return _as_utc(moment).isoformat(timespec="seconds").replace("+00:00", "Z")


# --- the derived step grid ------------------------------------------------------------------


def step_grid(
    published: dict[str, tuple[int, ...]] | None = None,
    step: int = CANDIDATE_STEP_H,
    max_lead: int = CANDIDATE_MAX_LEAD_H,
) -> tuple[int, ...]:
    """The **intersection**: every multiple of `step` in `(0, max_lead]` published by ALL models.

    `published` defaults to `PROBE_PUBLISHED_LEADS`, `step` and `max_lead` to the
    FORECAST-SPEC §5 candidates. All three are injectable so the derivation can be exercised
    against a table other than the recorded probe.

    On the recorded probe this returns `(3, 6, ..., 48)` — 16 steps, `horizon_h = 48`,
    `step_h = 3`. **That is what the data says, not what the spec prose says.** f000 is absent
    because NBM publishes none; NAM's f037-f047 holes are all non-multiples of 3 and so miss
    the grid entirely. Copying `48` out of the spec as a constant is forbidden (TR6): change
    the probe table and this function's answer changes with it.

    The range is half-open at zero (`0 < lead <= max_lead`) because a forecast at lead 0 is an
    analysis, not a forecast, and NBM does not publish one.
    """
    table = PROBE_PUBLISHED_LEADS if published is None else published
    if not table:
        raise RuntimeError(
            "FORECAST-SPEC §5.3: the step grid is the intersection across the models, and an "
            "empty published-lead table has no intersection to take. Pass the probe table."
        )
    if step <= 0:
        raise ValueError(f"FORECAST-SPEC §5.3: step must be a positive number of hours; got {step}")
    if max_lead < 0:
        raise ValueError(
            f"FORECAST-SPEC §5.3: max_lead must be a non-negative number of hours; got {max_lead}"
        )
    sets = {model: set(leads) for model, leads in table.items()}
    return tuple(
        lead
        for lead in range(step, max_lead + 1, step)
        if all(lead in leads for leads in sets.values())
    )


# --- cache paths and the root guard -----------------------------------------------------------


def _guard_cache_root(root: Path) -> Path:
    """Return `root` resolved, or raise `RuntimeError` naming the symlink that makes it unsafe.

    This worktree's `data/` holds symlinks that point into a **different, live checkout**.
    Writing through one would corrupt that checkout. `data/live/` is a real directory and is
    the only place F2 writes, so a cache root that is itself a symlink, or that sits directly
    inside one, is refused before a single byte is written.
    """
    root = Path(root)
    for suspect in (root, root.parent):
        if suspect.is_symlink():
            raise RuntimeError(
                f"FORECAST-SPEC §5.1: refusing cache root {root} — {suspect} is a symlink. "
                "F2 writes only to a real data/live/ directory inside this worktree; the "
                "other data/ entries are symlinks into a different live checkout and writing "
                "through one would corrupt it."
            )
    resolved = root.resolve()
    if root == LIVE_ROOT and _REPO_ROOT not in resolved.parents:
        raise RuntimeError(
            f"FORECAST-SPEC §5.1: the default cache root {root} resolves to {resolved}, which "
            f"is outside this repository ({_REPO_ROOT}). Run from the repository root, or pass "
            "an explicit root."
        )
    return resolved


def cache_dir(init: datetime, root: Path = LIVE_ROOT) -> Path:
    """`<root>/<YYYYMMDDHH>` for one init cycle, in UTC. Guards the root before returning."""
    _guard_cache_root(root)
    return Path(root) / _as_utc(init).strftime("%Y%m%d%H")


def cache_path(init: datetime, model: str, lead: int, root: Path = LIVE_ROOT) -> Path:
    """`<root>/<YYYYMMDDHH>/<model>_f<LLL>.json` — 4 models x 16 leads = 64 files per cycle."""
    if model != model.lower():
        raise ValueError(
            f"FORECAST-SPEC §9: model keys are lowercase throughout forecast/; got {model!r}. "
            "The scored leaderboard stores them UPPERCASE for display and F3 maps to that "
            "casing — F2 must not blur the distinction by silently lowercasing here."
        )
    if lead < 0:
        raise ValueError(f"FORECAST-SPEC §5.3: lead_h must be non-negative; got {lead}")
    return cache_dir(init, root=root) / f"{model}_f{lead:03d}.json"


# --- cache read / write --------------------------------------------------------------------


def read_cached(path: Path) -> dict | None:
    """The cached record, or `None` for a **miss**. Never raises on a damaged file.

    A miss is any of: the file is absent; it is not valid JSON; it is not a JSON object; it
    lacks one of `RECORD_FIELDS`; or one of its datetime fields will not parse. All of those
    are indistinguishable from "not fetched yet" as far as the caller is concerned, and the
    cure for every one of them is the same — fetch it again.

    `init_time`, `valid_time` and `fetched_at` come back as **tz-aware UTC datetimes**.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError, OSError):
        return None
    except UnicodeDecodeError:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None
    if any(field not in payload for field in RECORD_FIELDS):
        return None

    record = dict(payload)
    for field in DATETIME_FIELDS:
        value = payload[field]
        if not isinstance(value, str):
            return None
        try:
            record[field] = _as_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return record


def write_cached(path: Path, record: dict) -> None:
    """Write one cache record atomically: temp file in the same directory, then `os.replace`.

    Mirrors `score/run.py:59 write_atomic` (TR9). A killed process leaves either the previous
    file or the new one — never a half-written record that a later run would trust.
    """
    path = Path(path)
    _guard_cache_root(path.parent.parent)

    absent = [field for field in RECORD_FIELDS if field not in record]
    if absent:
        raise RuntimeError(
            f"FORECAST-SPEC §9: cache record for {path.name} is missing {absent}. The schema is "
            "locked in F2-findings.md 'Cache record schema' and F3 reads it — a partial record "
            "on disk would be read back as a miss and re-fetched forever."
        )
    if record["status"] not in CACHE_STATUSES:
        raise RuntimeError(
            f"FORECAST-SPEC §5.2: status must be one of {CACHE_STATUSES}; got "
            f"{record['status']!r}. Only an ArchiveMissing becomes 'missing'; every other "
            "failure propagates and is never written to the cache."
        )

    payload: dict = {}
    for field in RECORD_FIELDS:
        value = record[field]
        if field in DATETIME_FIELDS:
            if not isinstance(value, datetime):
                raise RuntimeError(
                    f"FORECAST-SPEC §2: {field} must be a datetime, got {type(value).__name__}. "
                    "UTC everywhere; the ISO-8601 serialization happens here, not upstream."
                )
            payload[field] = _iso(value)
        else:
            payload[field] = value
    for field in sorted(set(record) - set(RECORD_FIELDS)):
        payload[field] = record[field]

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    handle_fd, scratch = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(scratch, path)
    except BaseException:
        Path(scratch).unlink(missing_ok=True)
        raise


# --- the fetch layer ------------------------------------------------------------------------

#: Spike-F2-validated pool size. **Do not raise it**: the GRIB decode is GIL-bound, so more
#: threads buy nothing and cost memory (`fetch/backfill.py:60` reached the same number).
WORKERS = 8

#: The one reason an interior grid step is a gap. FORECAST-SPEC §9's example prose reads
#: "beyond model horizon", which under the definitions in `derive_horizon` describes
#: *truncation* rather than a gap — F3 is handed `truncated` and `grid_max_lead_h` so it can
#: label that case separately. This is a note for F3, not a contract change; F3 owns §9.
GAP_REASON = "absent from archive"

#: `fetch.grib.fetch_point`'s shape: `(model, init_time, lead_h) -> point dict`. Injected at
#: every call site so the whole of this module is exercisable with no network at all.
Fetcher = Callable[[str, datetime, int], dict]


def fetch_one(
    model: str,
    init: datetime,
    lead: int,
    *,
    fetcher: Fetcher,
    cache_root: Path = LIVE_ROOT,
    refetch_missing: bool = False,
    fetched_at: datetime | None = None,
) -> dict:
    """One (model, init, lead) item, **cache first**. Returns the settled cache record.

    A hit on disk returns immediately and makes no request — that, and the fact that a
    `missing` outcome is cached exactly like a `success` one, is the whole of FR8's
    zero-network re-run. `refetch_missing` **defaults to `False`** and must stay that way:
    flipping it would send every absent key back to the archive on every run.

    Failure handling is deliberately narrower than `fetch/backfill.py:212 classify`, which
    maps every failure to a status:

    * `ArchiveMissing` (HTTP 404/403) is an expected archive hole -> `status="missing"`,
      cached, no exception.
    * **Everything else propagates** (FR9). An HTTP 500 or a non-GRIB body filed as an
      archive hole would silently deflate coverage and fake a clean run.

    Two ordering traps, both live:

    1. `ArchiveMissing` **subclasses** `RuntimeError` (`fetch/grib.py:198`), so its `except`
       clause must come first — and no `except RuntimeError` may follow it here at all.
    2. `fetch/grib.py:_get` wraps a transport failure in a plain `RuntimeError` with the
       original as `__cause__`, so an `except requests.RequestException` clause in this
       package would never fire. `_get` also already retries once at 120 s, and a 404 is
       never retried, so **no retry layer belongs here**.

    `temp_f` is stored in degrees F exactly as `fetch_point` returns it. No unit conversion
    happens anywhere in this package (`fetch.grib.decode_point` owns it).
    """
    path = cache_path(init, model, lead, root=cache_root)
    cached = read_cached(path)
    if cached is not None and not (refetch_missing and cached["status"] == "missing"):
        return cached

    init_utc = _as_utc(init)
    # Whole seconds: `_iso` serializes at second precision, so a stamp carrying microseconds
    # would make the record returned by the fetching run differ from the byte-identical one
    # every later run reads back from disk. Truncate once, here, so the two always agree.
    stamp = (datetime.now(timezone.utc) if fetched_at is None else _as_utc(fetched_at)).replace(
        microsecond=0
    )

    try:
        point = fetcher(model, init_utc, lead)
    except ArchiveMissing as exc:  # MUST precede any RuntimeError clause — see the docstring
        record = {
            "model": model,
            "init_time": init_utc,
            "lead_h": lead,
            "valid_time": valid_time(init_utc, lead),
            "status": "missing",
            "temp_f": None,
            "grid_lat": None,
            "grid_lon": None,
            "distance_deg": None,
            "error": str(exc),
            "fetched_at": stamp,
        }
    else:
        record = {
            "model": point.get("model", model),
            "init_time": _as_utc(point.get("init_time", init_utc)),
            "lead_h": point.get("lead_h", lead),
            "valid_time": _as_utc(point.get("valid_time", valid_time(init_utc, lead))),
            "status": "success",
            "temp_f": point.get("temp_f"),
            "grid_lat": point.get("grid_lat"),
            "grid_lon": point.get("grid_lon"),
            "distance_deg": point.get("distance_deg"),
            "error": None,
            "fetched_at": stamp,
        }

    write_cached(path, record)
    return record


def fetch_leads(
    init: datetime,
    leads: Iterable[int],
    *,
    fetcher: Fetcher,
    cache_root: Path = LIVE_ROOT,
    workers: int = WORKERS,
    refetch_missing: bool = False,
    fetched_at: datetime | None = None,
) -> dict[tuple[str, int], dict]:
    """All four models at every lead in `leads`, pooled. Returns `{(model, lead): record}`.

    Cache hits are resolved **before** anything is submitted, so a fully cached cycle
    submits no work at all and the pool is never even entered. `fetch_point` is pure
    per-call (no shared session, no global state), so it is safe to drive from threads as-is,
    and `write_cached` uses `tempfile.mkstemp` in the target directory, so concurrent writes
    to the same cycle directory cannot collide.

    Exceptions from a worker are re-raised by `future.result()` and propagate out of this
    function unchanged (FR9) — only `ArchiveMissing` is ever absorbed, and that happens one
    level down in `fetch_one`.
    """
    records: dict[tuple[str, int], dict] = {}
    pending: list[tuple[str, int]] = []

    for lead in leads:
        for model in MODELS:
            cached = read_cached(cache_path(init, model, lead, root=cache_root))
            if cached is not None and not (refetch_missing and cached["status"] == "missing"):
                records[(model, lead)] = cached
            else:
                pending.append((model, lead))

    if not pending:
        return records

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                fetch_one,
                model,
                init,
                lead,
                fetcher=fetcher,
                cache_root=cache_root,
                refetch_missing=refetch_missing,
                fetched_at=fetched_at,
            ): (model, lead)
            for model, lead in pending
        }
        for future, key in futures.items():
            records[key] = future.result()

    return records


# --- horizon and gaps -------------------------------------------------------------------


def covered_leads(records: dict[tuple[str, int], dict]) -> tuple[int, ...]:
    """The leads where **all four** models settled `success`, ascending.

    A lead with three members is not covered. FR4 forbids serving a blend over a subset of
    the models, and nothing in this package rescales a member set to compensate — the step
    becomes a gap and stays honest.
    """
    leads = sorted({lead for (_model, lead) in records})
    return tuple(
        lead
        for lead in leads
        if all((records.get((model, lead)) or {}).get("status") == "success" for model in MODELS)
    )


def derive_horizon(records: dict[tuple[str, int], dict], grid: Sequence[int]) -> int:
    """The served horizon in hours: the **last grid step that is fully covered** (§5.3).

    Trailing incompleteness truncates; interior incompleteness does not. Walk the grid from
    its end and stop at the first step where all four models settled `success`:

    * NAM absent at f045 and f048 -> the tail is unusable -> `horizon_h = 42`, `truncated`.
    * NAM absent at f012 only -> the tail is intact -> `horizon_h` stays at the grid maximum
      and f012 is reported by `find_gaps` instead.

    Those two cases are what makes FORECAST-SPEC §9 rule 8 satisfiable at all: over the grid
    **up to `horizon_h`**, a step is either covered or a gap, never both and never neither.
    Truncation removes steps from that universe; gaps are holes inside it. Reading §5.3 as a
    strictly contiguous run from `grid[0]` would collapse `gaps` to always-empty and make
    plan §2.3's gap definition unreachable.

    The answer comes from the records that were actually fetched, never from a constant:
    change the archive's behaviour and this number changes with it (TR6). Returns 0 when no
    grid step is covered — `fetch_cycle` cannot reach that, because Phase A has already
    proved `grid[0]` complete before Phase B runs.
    """
    if not grid:
        raise RuntimeError(
            "FORECAST-SPEC §5.3: an empty step grid has no horizon to derive. The grid is the "
            "intersection across the four models and must be non-empty before a fetch starts."
        )
    covered = set(covered_leads(records))
    for lead in reversed(tuple(grid)):
        if lead in covered:
            return lead
    return 0


def _lead_valid_time(records: dict[tuple[str, int], dict], lead: int) -> datetime:
    """The UTC valid time of a grid step, taken from the records rather than recomputed."""
    for model in MODELS:
        record = records.get((model, lead))
        if record is not None:
            return _as_utc(record["valid_time"])
    for record in records.values():
        return valid_time(record["init_time"], lead)
    raise RuntimeError(
        f"FORECAST-SPEC §9: no record at all for f{lead:03d}, so its valid time cannot be "
        "established. An empty record set is a failure, not a success."
    )


def find_gaps(
    records: dict[tuple[str, int], dict],
    grid: Sequence[int],
    horizon_h: int,
) -> tuple[dict, ...]:
    """Interior grid steps at or below `horizon_h` that are missing at least one model.

    Each gap is `{lead_h, valid_time, missing_models, reason}`. `missing_models` is
    **lowercase** throughout this package (OQ3) and listed in `fetch.grib.MODELS` order, so
    the output is deterministic. `reason` is always `GAP_REASON`.

    Steps above `horizon_h` are not gaps — they were truncated away and `truncated` plus
    `grid_max_lead_h` describe them instead.
    """
    gaps: list[dict] = []
    for lead in grid:
        if lead > horizon_h:
            continue
        absent = tuple(
            model
            for model in MODELS
            if (records.get((model, lead)) or {}).get("status") != "success"
        )
        if not absent:
            continue
        gaps.append(
            {
                "lead_h": lead,
                "valid_time": _lead_valid_time(records, lead),
                "missing_models": absent,
                "reason": GAP_REASON,
            }
        )
    return tuple(gaps)


# --- the cycle result -----------------------------------------------------------------------


class NoCycleAvailable(RuntimeError):
    """No candidate in the FORECAST-SPEC §5.2 ladder is published.

    Raised only after every candidate's Phase A has failed. It carries each candidate's init
    and the reason it was rejected, because "no forecast today" without a reason is
    indistinguishable from a bug. **Nothing is written and nothing is fabricated** when this
    fires: serving a stale or partial blend would be worse than serving none.
    """


@dataclass(frozen=True)
class CycleResult:
    """One fully resolved forecast cycle — the values F2 produces, and nothing more.

    **Model keys are lowercase everywhere in this package** (`hrrr`/`gfs`/`nam`/`nbm`),
    matching `fetch.grib.MODELS` and what `fetch_point` returns. The scored leaderboard
    stores them UPPERCASE for display. **F3 owns the display casing and the JSON contract**;
    F2 produces values only and writes no payload of its own. F2 must not blur the two
    conventions together, which is why `cache_path` refuses a non-lowercase key outright
    rather than silently coercing it.

    Field meanings that are easy to confuse:

    * `grid_max_lead_h` — the last step that was **asked for** (the grid's ceiling).
    * `horizon_h` — the last step actually **served**; see `derive_horizon`.
    * `truncated` — `horizon_h < grid_max_lead_h`.
    * `gaps` — interior steps at or below `horizon_h` missing at least one model.
    * `records` — `{(model, lead): cache record}`, every member from **one** init (FR4).
    * `fallback_reasons` — one entry per candidate the ladder rejected before this one.
    """

    init_time: datetime
    target_init_time: datetime
    run_label: str
    fetched_at: datetime
    age_minutes: int
    is_stale: bool
    stale_reason: str | None
    cycles_fallen_back: int
    step_h: int
    horizon_h: int
    grid_max_lead_h: int
    truncated: bool
    records: dict[tuple[str, int], dict]
    gaps: tuple[dict, ...]
    fallback_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.records:
            raise RuntimeError(
                "SPEC §10 integrity: a CycleResult with zero records is a failure, not a "
                "success. An empty result scores perfectly and is fake — a cycle that "
                "produced nothing must raise, never be served as an empty forecast."
            )
        if (self.stale_reason is not None) != self.is_stale:
            raise RuntimeError(
                "FORECAST-SPEC §9 rule 11: stale_reason is non-null exactly when is_stale is "
                f"true; got is_stale={self.is_stale}, stale_reason={self.stale_reason!r}."
            )
        if self.truncated != (self.horizon_h < self.grid_max_lead_h):
            raise RuntimeError(
                "FORECAST-SPEC §5.3: truncated must mean horizon_h < grid_max_lead_h; got "
                f"truncated={self.truncated}, horizon_h={self.horizon_h}, "
                f"grid_max_lead_h={self.grid_max_lead_h}."
            )


def _require_one_cycle(records: dict[tuple[str, int], dict], init: datetime) -> None:
    """FR4 belt and braces: every member of a served cycle comes from **one** init.

    `fetch_cycle` only ever asks for one init, so this cannot fire through normal use — it
    exists because a blend silently mixing a 12z member with an 06z one would look perfectly
    healthy in the output and be wrong in a way no reader could see.
    """
    init_utc = _as_utc(init)
    strays = sorted(
        {
            _iso(record["init_time"])
            for record in records.values()
            if _as_utc(record["init_time"]) != init_utc
        }
    )
    if strays:
        raise RuntimeError(
            f"FORECAST-SPEC §5.2 / FR4: a cycle's members must all come from init "
            f"{_iso(init_utc)}, but records carry {strays}. Members are never mixed across "
            "cycles — that step is a gap instead."
        )


# --- Phase A / Phase B, and the fallback ladder ------------------------------------------


def fetch_cycle(
    init: datetime,
    *,
    fetcher: Fetcher,
    cache_root: Path = LIVE_ROOT,
    now: datetime,
    grid: Sequence[int] | None = None,
    workers: int = WORKERS,
    refetch_missing: bool = False,
    fetched_at: datetime | None = None,
    target_init: datetime | None = None,
    cycles_fallen_back: int = 0,
    fallback_reasons: Sequence[str] = (),
    unavailable_reasons: list[str] | None = None,
) -> CycleResult | None:
    """One whole cycle in two phases (plan §0.4). `None` when Phase A says it is not published.

    FORECAST-SPEC §5.2 ("any model 404s -> fall back a cycle") and §5.3 ("a short model
    horizon truncates and labels") collide when read literally: a NAM tail hole would force a
    pointless 18 h fallback and then serve nothing. The adopted resolution splits the fetch:

    * **Phase A** asks all four models for `grid[0]` — 4 requests. A `missing` here means the
      **cycle** is not published for that model, so the ladder falls back. Phase A probes
      `grid[0]`, **not the literal 3**: if the grid's first step ever moves, Phase A moves
      with it.
    * **Phase B** asks for the rest of the grid — 60 requests on the probe's grid. A trailing
      miss **truncates** `horizon_h`; an interior miss becomes a **gap** naming the absent
      models. **No fallback fires in Phase B**, ever.

    When Phase A fails, the reason is appended to `unavailable_reasons` (if a list was
    passed) and `None` is returned — `select_cycle` collects those into `fallback_reasons`
    and, if the whole ladder fails, into `NoCycleAvailable`.

    `now` and `fetched_at` are injected; this function never reads the wall clock.
    """
    steps = tuple(step_grid()) if grid is None else tuple(grid)
    if not steps:
        raise RuntimeError(
            "FORECAST-SPEC §5.3: the step grid is empty, so there is nothing to fetch. The "
            "grid is the intersection across the four models; an empty one means no lead is "
            "published by all of them."
        )

    init_utc = _as_utc(init)
    stamp = _as_utc(now) if fetched_at is None else _as_utc(fetched_at)
    common = {
        "fetcher": fetcher,
        "cache_root": cache_root,
        "workers": workers,
        "refetch_missing": refetch_missing,
        "fetched_at": stamp,
    }

    # --- Phase A: is this cycle published at all? ---
    probe_lead = steps[0]
    phase_a = fetch_leads(init_utc, (probe_lead,), **common)
    _require_one_cycle(phase_a, init_utc)

    absent = tuple(
        model for model in MODELS if phase_a[(model, probe_lead)]["status"] != "success"
    )
    if absent:
        reason = (
            f"FORECAST-SPEC §5.2: the {cycle.run_label(init_utc)} cycle {_iso(init_utc)} is "
            f"not published — f{probe_lead:03d} is absent for {', '.join(absent)}."
        )
        if unavailable_reasons is not None:
            unavailable_reasons.append(reason)
        return None

    # --- Phase B: how far does it reach, and where are the holes? (no fallback here) ---
    records = dict(phase_a)
    records.update(fetch_leads(init_utc, steps[1:], **common))
    _require_one_cycle(records, init_utc)

    horizon_h = derive_horizon(records, steps)
    grid_max_lead_h = steps[-1]
    age = cycle.age_minutes(init_utc, now)
    is_stale, stale_reason = cycle.staleness(cycles_fallen_back, age)

    return CycleResult(
        init_time=init_utc,
        target_init_time=init_utc if target_init is None else _as_utc(target_init),
        run_label=cycle.run_label(init_utc),
        fetched_at=stamp,
        age_minutes=age,
        is_stale=is_stale,
        stale_reason=stale_reason,
        cycles_fallen_back=cycles_fallen_back,
        step_h=(steps[1] - steps[0]) if len(steps) > 1 else CANDIDATE_STEP_H,
        horizon_h=horizon_h,
        grid_max_lead_h=grid_max_lead_h,
        truncated=horizon_h < grid_max_lead_h,
        records=records,
        gaps=find_gaps(records, steps, horizon_h),
        fallback_reasons=tuple(fallback_reasons),
    )


def select_cycle(
    now_utc: datetime,
    *,
    fetcher: Fetcher,
    cache_root: Path = LIVE_ROOT,
    grid: Sequence[int] | None = None,
    workers: int = WORKERS,
    refetch_missing: bool = False,
    fetched_at: datetime | None = None,
) -> CycleResult:
    """Walk the FORECAST-SPEC §5.2 ladder and return the first cycle that is published.

    `cycle.target_cycle(now_utc)` picks the target init; `cycle.candidate_cycles` enumerates
    it plus three earlier ones, spanning 18 h. Each candidate's Phase A decides whether the
    ladder moves on, so `cycles_fallen_back` is simply the index that succeeded, and the
    rejected candidates' reasons travel with the result for the staleness banner.

    Every instant is injected — `now_utc`, and optionally `fetched_at` — so this function
    never reads the wall clock itself and the entire ladder is exercisable at a frozen time.

    Raises `NoCycleAvailable` when all four candidates fail, having written no payload and
    fabricated nothing. Cached `missing` records are the only things left behind, and they
    are what make the next run cost zero requests.
    """
    now = _as_utc(now_utc)
    target = cycle.target_cycle(now)
    candidates = cycle.candidate_cycles(target)
    reasons: list[str] = []

    for fallen_back, init in enumerate(candidates):
        result = fetch_cycle(
            init,
            fetcher=fetcher,
            cache_root=cache_root,
            now=now,
            grid=grid,
            workers=workers,
            refetch_missing=refetch_missing,
            fetched_at=fetched_at,
            target_init=target,
            cycles_fallen_back=fallen_back,
            fallback_reasons=tuple(reasons),
            unavailable_reasons=reasons,
        )
        if result is not None:
            return result

    raise NoCycleAvailable(
        f"FORECAST-SPEC §5.2: none of the {len(candidates)} candidate cycles spanning "
        f"{(len(candidates) - 1) * cycle.INIT_STEP_H} h back from {_iso(target)} is "
        "published. Nothing is served and nothing is fabricated.\n  - "
        + "\n  - ".join(reasons)
    )


if __name__ == "__main__":  # pragma: no cover
    # FR11 manual-run harness ONLY; F3's forecast/refresh.py is the real CLI and supersedes it.
    import argparse

    from fetch.grib import fetch_point

    ap = argparse.ArgumentParser(description="FR11: fetch one live cycle into the disk cache.")
    ap.add_argument("--refetch-missing", action="store_true")
    ap.add_argument("--cache-root", type=Path, default=LIVE_ROOT)
    args = ap.parse_args()
    res = select_cycle(datetime.now(timezone.utc), fetcher=fetch_point,
                       cache_root=args.cache_root, refetch_missing=args.refetch_missing)
    tally = [record["status"] for record in res.records.values()]
    print(f"init={_iso(res.init_time)} run_label={res.run_label} "
          f"cycles_fallen_back={res.cycles_fallen_back} age_minutes={res.age_minutes}\n"
          f"is_stale={res.is_stale} stale_reason={res.stale_reason}\n"
          f"step_h={res.step_h} horizon_h={res.horizon_h} "
          f"grid_max_lead_h={res.grid_max_lead_h} truncated={res.truncated}\n"
          f"success={tally.count('success')} missing={tally.count('missing')}\n"
          f"gaps={[dict(g, valid_time=_iso(g['valid_time'])) for g in res.gaps] or 'none'}")
