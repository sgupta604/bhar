# F2 Findings — `forecast-live-fetch`

**Ticket:** FORECAST-SPEC §12 F2 · **Branch:** `feat/forecast-page` · **Worktree:** `/Users/sanjaygupta/Projects/Bhar-forecast`
**Sources:** `2026-09-04T11-55-22_research.md` (the probe), `2026-09-04T12-01-07_plan.md` §0.2 / §2.2 / §2.3 / §0.4

§12-F2 requires the probe's findings to be **written down** and `horizon_h` / `step_h` to be
**derived from them**. This file is that record. The probe is **settled — do not re-run it.**

---

## 1. The probe

Read-only reconnaissance executed **2026-09-04 ~16:53Z**. **196 HEAD requests** against the four
models' `.idx` keys for leads **f000–f048** of a single recent synoptic cycle.

- **Init probed:** `2026-09-04 12z` — the target cycle for that instant (`16:53Z − 4 h setback = 12:53Z`, floored to a synoptic hour).
- **Method:** HTTP HEAD on the `.idx` object. A `200` means the key exists; a `404` means the lead is not published.
- **Scope:** 4 models × 49 leads = 196 requests.

### 1.1 Published leads per model, 0–48 h

| Model | Published leads in 0–48 | Count | Absent (404) |
|---|---|---|---|
| **HRRR** | 0–48, **every hour** | **49 / 49** | none |
| **GFS** | 0–48, **every hour** | **49 / 49** | none |
| **NAM** | 0–36 hourly, then **39, 42, 45, 48** | **41 / 49** | **37, 38, 40, 41, 43, 44, 46, 47** |
| **NBM** | 1–48, every hour | **48 / 49** | **f000 — NBM publishes no f000** |

Notes on the two irregular models:

- **NAM** (`awphys`) is hourly to f036 and 3-hourly thereafter. Its eight holes are all
  **non-multiples of 3**, which is why a 3-hourly grid clears them exactly. The `awip` key split
  that §16 R1 warned might be needed was **not** needed — `awphys` covered the whole 0–48 grid.
- **HRRR** reaches f048 only because **00/06/12/18z are HRRR's extended runs** — and those are
  exactly and only the inits this project uses (§5 `init_runs`). A non-synoptic HRRR run stops at
  f018; we never ask for one.

### 1.2 Anchored-needle verification (6 `.idx` bodies fetched and parsed)

A cheap GET of six `.idx` texts, searched with the anchored needle `":TMP:2 m above ground:"`
(leading colon), rejecting `ens std dev`:

| `.idx` file | lines | anchored `:TMP:2 m above ground:` hits | message # | `APTMP:2 m above ground` present |
|---|---|---|---|---|
| hrrr f048 | 173 | **1** | 71 | no |
| gfs  f048 | 743 | **1** | 581 | **yes** |
| nam  f039 | 452 | **1** | 321 | no |
| nam  f048 | 454 | **1** | 321 | no |
| nbm  f003 | 156 | **1** | **135** | **yes** |
| nbm  f048 | 192 | **1** | **173** | **yes** |

**Exactly one anchored hit at every probed lead, for every model.** `select_tmp_2m`'s
`len(hits) != 1` hard failure will not misfire on the live path.

Two conclusions, both binding on the implementation:

1. **NBM's message index moved 135 → 173 between f003 and f048 of the same cycle.**
   **No message index may ever be hardcoded — anywhere, for any model.** Parse the `.idx` every
   time. (Re-proves spike F10 on live data.)
2. **The APTMP trap is live in GFS as well as NBM.** Both carry an `APTMP:2 m above ground` record
   alongside the real `TMP` one. The **anchored needle with its leading colon** is what separates
   them; an unanchored substring search would match `APTMP` and silently decode apparent
   temperature as air temperature.

---

## 2. The derived grid

| Quantity | Value |
|---|---|
| Grid | **`f003, f006, … , f048`** |
| `step_h` | **3** |
| Steps | **16** |
| `horizon_h` | **48** |
| `grid_max_lead_h` | 48 |

This is the **intersection across all four models** — the set of leads published by HRRR **and**
GFS **and** NAM **and** NBM on a 3-hourly grid. All four are present at every one of the 16 steps,
so the §12-F2 acceptance floor (3-hourly to 48 h, all four models) is **MET** on this cycle: no
truncation and no gap is expected on a healthy cycle.

**It is computed, not copied.** The grid is produced at import time by `step_grid()` in
`forecast/live.py` from the `PROBE_PUBLISHED_LEADS` table — the §1.1 observation written into code
as data. **`48` and `3` are the candidate ceiling and candidate step, never loop literals**, and
`(3, 6, …, 48)` comes out **because the data says so**, not because the spec prose says so.
Copying `horizon_h = 48` out of FORECAST-SPEC as a constant is explicitly forbidden (TR6).

Two properties of the grid worth stating plainly:

- **`f000` is excluded, and that exclusion is load-bearing.** **NBM has no f000.** A grid that
  started at 0 would 404 on NBM at the very first step of every cycle — and under the §0.4 Phase A
  rule that first-step miss would trigger a fallback, walk the whole 18 h ladder, and then serve
  nothing. Start at f003.
- **A 3-hourly grid dodges NAM's f037–f047 holes exactly.** NAM's absent leads (37, 38, 40, 41,
  43, 44, 46, 47) are all non-multiples of 3; its published tail (39, 42, 45, 48) is entirely on
  the grid. The intersection survives NAM's post-f036 thinning without losing a single step.

---

## 3. Probe caveat — one cycle, one day

**The probe sampled a single cycle (`2026090412z`) on a single day. The intersection is verified,
not proven invariant.** NOAA's publication can be late, partial, or reorganized on any given day.

**Mitigation:** `derive_horizon()` **re-derives the served horizon from the records actually
fetched at runtime** — the largest grid lead reachable by a contiguous all-four-`success` run
starting at `step_grid()[0]`. It never reads a constant. So a short NOAA day **truncates and
labels** (`horizon_h < grid_max_lead_h`, `truncated = true`) rather than crashing or, worse,
serving a 48 h horizon it does not actually have. The probe fixes what we *ask for*; the runtime
derivation fixes what we *claim to have served*.

Two smaller residual caveats:

- An `.idx` HTTP 200 proves the **key** exists; it does not prove the GRIB message **decodes**.
  The six `.idx` bodies in §1.2 close most of that gap; the manual live run (§6) closes the rest by
  decoding all 64 records.
- KOMA's nearest-cell distance is unexercised for NAM at f039–f048. A `SPEC §5` distance-sanity
  failure would surface in the manual live run.

---

## 4. The adopted OQ1 two-phase rule

§5.2 ("any model 404s → fall back a cycle") and §5.3 ("a short model horizon truncates and labels")
collide when read literally: a NAM tail hole would force a pointless 18 h fallback and then serve
nothing. The plan (§0.4) **adopts the two-phase rule without modification**:

| Phase | What is fetched | A `missing` there means |
|---|---|---|
| **A** | `step_grid()[0]` (= f003) for all four models — **4 requests** | The **cycle** is not published for that model → **fall back one cycle**, max **3** (18 h), then **serve nothing** with the reason |
| **B** | f006 … f048 for all four models — **60 requests** | A **trailing** contiguous miss **truncates `horizon_h`** and labels it. An **interior** miss is a **gap**, with the missing models **named**. |

- **No fallback fires in Phase B.** Once Phase A has established the cycle exists for all four
  models, a later hole is a horizon or a gap, never a reason to change cycles.
- **Phase A probes `step_grid()[0]`, not the literal `3`** — if a future probe moves the grid's
  first step, Phase A moves with it.
- **Never mix models across cycles.** All four members come from one init, or that step is a gap.
- **Weights are NEVER renormalized over a subset of models — absolute, regardless of phase.** F2
  touches no weights at all and must not add a helper that would let F3 do so. A gap is honest; a
  blend silently rescaled over three of four models is not.

The rule invents no numeric threshold, costs 4 extra requests, honours both sections, and the probe
says **neither branch fires on a healthy cycle**.

---

## 5. v2 note — hourly steps are blocked on a data source (record only, do not solve)

FORECAST-SPEC **§22 item 2** (v2: hourly forecast steps) **cannot work with the current four
sources.** NAM publishes nothing at **f037–f047** on the 12z run, so an hourly grid's intersection
across all four models collapses to 0–36 h. Extending hourly coverage to 48 h would require a
**second source for NAM f037–f047** (or dropping NAM from the tail, which would mean renormalizing
weights over a subset — forbidden).

**Recorded here as a known v2 blocker. F2 does not solve it and must not attempt to.**

---

## Cache record schema

**Locked by Task 3.1 before any Stream 3 code was written. F3 reads this file — it is a contract.**

### Path

```
data/live/<YYYYMMDDHH>/<model>_f<LLL>.json
```

- `<YYYYMMDDHH>` is the **init** time in **UTC** (e.g. `2026090412` for `2026-09-04 12z`).
- `<model>` is the lowercase model key; `<LLL>` is the lead in hours, **3-digit zero-padded**
  (`f003` … `f048`).
- **4 models x 16 grid steps = 64 files per full cycle.**
- Built by `cache_dir(init, root)` / `cache_path(init, model, lead, root)` in `forecast/live.py`,
  under `LIVE_ROOT = data/live` — a **real directory in this worktree**, never a symlink
  (`_guard_cache_root` enforces it; see "The root guard" below).

### Fields

Exactly these eleven keys, in this order:

| Field | Type | Notes |
|---|---|---|
| `model` | str | **lowercase** — `hrrr` / `gfs` / `nam` / `nbm` |
| `init_time` | str | ISO-8601 UTC, trailing `Z` |
| `lead_h` | int | hours, a member of `step_grid()` |
| `valid_time` | str | ISO-8601 UTC, trailing `Z` = `init_time + lead_h` |
| `status` | str | `"success"` or `"missing"` — nothing else |
| `temp_f` | float \| null | **degrees F**; `null` when `status == "missing"` |
| `grid_lat` | float \| null | nearest grid cell; `null` on `missing` |
| `grid_lon` | float \| null | nearest grid cell; `null` on `missing` |
| `distance_deg` | float \| null | degrees from KOMA to that cell; `null` on `missing` |
| `error` | str \| null | the `ArchiveMissing` text on `missing`; `null` on `success` |
| `fetched_at` | str | ISO-8601 UTC, trailing `Z` — when the record was produced |

`read_cached` returns `init_time`, `valid_time` and `fetched_at` as **tz-aware UTC `datetime`
objects**; every other field comes back exactly as written.

### Rules

- **All datetimes are ISO-8601 UTC with a trailing `Z`** — `fetch/backfill.py:90 _iso` house style
  (`timespec="seconds"`, `+00:00` rewritten to `Z`). A naive datetime is UTC, never local
  (`fetch.grib._as_utc`, reused; never reimplemented).
- **`temp_f` is degrees F**, exactly as `fetch.grib.fetch_point` returns it. **Kelvin never appears
  anywhere in `forecast/`** — the conversion lives in `decode_point` and stays there.
- **`status` has exactly two settled values, `"success"` and `"missing"`**, mirroring
  `fetch/backfill.py:70 SKIP_STATUSES`. Only `ArchiveMissing` produces `"missing"`; every other
  exception propagates and is **never** written as a `missing` record (plan §9 decision 5).
- **`missing` records are cached too.** This is precisely what makes the zero-network re-run
  (FR8) real: without it, every 404 is re-requested on every single run, and a cycle with a
  genuine archive hole would hit the network forever. `refetch_missing` defaults to `False`.
- **The cache directory IS the ledger.** There is no manifest file and no index: a cache hit is a
  **pure function of what is on disk**. A file that is absent, unparseable, truncated, or missing
  a required key is a **miss** (`read_cached` returns `None`) — never a crash, never a partial
  record.
- **Writes are atomic**: a temp file in the **same directory** plus `os.replace`, `encoding="utf-8"`,
  trailing newline — mirroring `score/run.py:59 write_atomic`. A killed process leaves either the
  old file or the new one, never a half-written one that a later run would trust.
- **Model keys are lowercase** (`hrrr`/`gfs`/`nam`/`nbm`), matching `fetch.MODELS` and
  `fetch_point`'s return. `results.json meta.models_included` is **UPPERCASE**;
  **F3 maps to display casing** when it builds the payload. F2 stores lowercase throughout and
  must not silently lose the distinction (OQ3, plan §2.4).

### The root guard

`_guard_cache_root(root)` raises `RuntimeError` **naming the offending symlink** when `root` or
`root.parent` is a symlink, and — for the default `LIVE_ROOT` — additionally requires it to resolve
inside this repository. `data/raw`, `data/forecasts.parquet` and `data/obs.parquet` in this worktree
are symlinks into a **different live checkout**; writing through one would corrupt it. `data/live/`
is the only real directory F2 writes, and the guard is called from every write path.

### Example

```json
{
  "model": "nbm",
  "init_time": "2026-09-04T12:00:00Z",
  "lead_h": 3,
  "valid_time": "2026-09-04T15:00:00Z",
  "status": "success",
  "temp_f": 71.42,
  "grid_lat": 41.3,
  "grid_lon": -95.9,
  "distance_deg": 0.012,
  "error": null,
  "fetched_at": "2026-09-04T16:53:00Z"
}
```

---

## 6. Manual live run

FR11, Task 6.1. A real run against NOAA's public S3 buckets — 64 byte-range GRIB GETs, 64 cfgrib
decodes, no mocks. Not part of the pytest suite (TR8: no live network in tests); the harness is the
`if __name__ == "__main__":` block at the foot of `forecast/live.py` (20 lines, argparse with
`--refetch-missing` and `--cache-root` and nothing else). **F3's `forecast/refresh.py` is the real
CLI and supersedes it.**

### The command

```
cd /Users/sanjaygupta/Projects/Bhar-forecast
time uv run --no-sync python -m forecast.live
```

Run 1 started **2026-09-04T17:30:06Z**; run 2 started ~**2026-09-04T17:30:40Z**. Both used the
default cache root (`data/live`) and the default `--refetch-missing` (off).

### Run 1 — output verbatim

```
init=2026-09-04T12:00:00Z run_label=12z cycles_fallen_back=0 age_minutes=330
is_stale=False stale_reason=None
step_h=3 horizon_h=48 grid_max_lead_h=48 truncated=False
success=64 missing=0
gaps=none
uv run --no-sync python -m forecast.live  3.52s user 0.41s system 52% cpu 7.535 total
```

| Field | Value |
|---|---|
| `init_time` | `2026-09-04T12:00:00Z` |
| `run_label` | `12z` |
| `cycles_fallen_back` | `0` — the target cycle itself; the ladder never fell back |
| `age_minutes` | `330` (5 h 30 min; the 4 h setback had elapsed) |
| `is_stale` / `stale_reason` | `False` / `None` (0 fallbacks, 330 ≤ 540 min) |
| `step_h` | `3` |
| `horizon_h` | `48` |
| `grid_max_lead_h` | `48` |
| `truncated` | `False` |
| `success` / `missing` | **64 / 0** |
| `gaps` | none |

### On disk

```
$ ls data/live/
2026090412

$ ls data/live/2026090412/ | wc -l
      64

$ grep -l '"status": "success"' data/live/2026090412/*.json | wc -l
      64
$ grep -l '"status": "missing"' data/live/2026090412/*.json | wc -l
       0
```

16 files per model (`hrrr`, `gfs`, `nam`, `nbm`), at exactly the 16 derived grid steps
f003 f006 f009 f012 f015 f018 f021 f024 f027 f030 f033 f036 f039 f042 f045 f048.

One sample record, verbatim — `data/live/2026090412/nam_f048.json`, deliberately the corner the
plan §10 flagged as unexercised (NAM at the far end of its 3-hourly tail):

```json
{
  "model": "nam",
  "init_time": "2026-09-04T12:00:00Z",
  "lead_h": 48,
  "valid_time": "2026-09-06T12:00:00Z",
  "status": "success",
  "temp_f": 74.75570190429691,
  "grid_lat": 41.28636980923781,
  "grid_lon": -95.9304834327101,
  "distance_deg": 0.04008752295743236,
  "error": null,
  "fetched_at": "2026-09-04T17:30:12Z"
}
```

The symlink hazard held. `data/live` is a real directory; the three symlinks into the other
checkout still carry their original `11:11:24` mtimes, untouched:

```
drwxr-xr-x@ 3 ... Sep  4 12:30:13 2026 live
lrwxr-xr-x@ 1 ... Sep  4 11:11:24 2026 forecasts.parquet -> /Users/.../Bhar/data/forecasts.parquet
lrwxr-xr-x@ 1 ... Sep  4 11:11:24 2026 obs.parquet       -> /Users/.../Bhar/data/obs.parquet
lrwxr-xr-x@ 1 ... Sep  4 11:11:24 2026 raw               -> /Users/.../Bhar/data/raw
```

(Local clock is UTC−5, so `12:30:13` local is `17:30:13Z`.)

### Run 2 — the zero-network proof

```
init=2026-09-04T12:00:00Z run_label=12z cycles_fallen_back=0 age_minutes=330
is_stale=False stale_reason=None
step_h=3 horizon_h=48 grid_max_lead_h=48 truncated=False
success=64 missing=0
gaps=none
uv run --no-sync python -m forecast.live  0.22s user 0.04s system 90% cpu 0.293 total
```

| | Run 1 (cold cache) | Run 2 (warm cache) |
|---|---|---|
| wall clock | **7.535 s** | **0.293 s** |
| user CPU | 3.52 s | 0.22 s |

**26x faster, and byte-identical output.** Run 2's 0.293 s is essentially interpreter startup and
the `xarray`/`cfgrib`/`pandas` import chain — there is no room in it for 64 HTTPS round trips, let
alone 64 GRIB decodes. The stronger evidence is on disk: **every one of the 64 cache files still
carries a run-1 mtime** (`12:30:13`–`12:30:19` local, i.e. `17:30:13Z`–`17:30:19Z`), and run 2
started at ~`17:30:40Z`. Run 2 wrote nothing, so it fetched nothing. FR8 holds: cache hits are
resolved in `fetch_leads` before the thread pool is entered, and with `pending` empty the pool is
never constructed at all.

### Did the probe's f003–f048 intersection hold?

**Yes — but read this carefully, because this run is _not_ the independent second sample Task 6.1
hoped for.** The §5.2 ladder, run at 17:30Z, targets `17:30Z − 4 h = 13:30Z` floored to a synoptic
hour, which is **12z on 2026-09-04 — the same init as `PROBE_INIT`** (`forecast/live.py:43`). The
probe was taken at 17:0xZ the same day and the setback had not yet advanced the target to 18z.

So what this run independently confirms is the **method**, not a second cycle:

* the probe established publication with **196 HEAD requests**;
* this run performed **64 byte-range GETs plus 64 full `cfgrib` decodes** and got a real temperature
  out of every single one — 64/64 `success`, 0 `missing`, no gaps, no truncation.

That closes the gap between "the `.idx` exists" and "the message decodes to a usable 2 m
temperature", which the probe never tested. It does **not** add a second day/cycle to §3's
"one cycle, one day" caveat, which therefore **stands unreduced**. A genuine second sample will
arrive for free the first time F3's `refresh.py` runs on a different cycle; it was not manufactured
here, because the harness takes no `--init` and inventing one to hunt a nicer sample is exactly the
tuning SPEC §10 forbids.

### Anything surprising

* **Nothing 404'd.** No divergence from the probe: no model returned an archive hole at any grid
  step, so neither `derive_horizon`'s truncation path nor `find_gaps` fired on live data. Both
  remain covered only by the injected-fetcher tests.
* **The 0.5° sanity floor was never approached**, including at the f039–f048 NAM tail that plan §10
  singled out as unexercised. Worst-case `distance_deg` per model across all 16 steps:
  `nbm 0.0088`, `hrrr 0.0120`, `nam 0.0401`, `gfs 0.1185` — the largest is under a quarter of the
  floor, and it is GFS simply because 0.25° is the coarsest grid of the four. NAM at f048 sat at
  0.0401°. **No distance failure to report.**
* **No slow model.** 64 fetches finished in 7.5 s wall on 8 workers — roughly one 8-wide round per
  second, with no straggler stretching the tail.
* `age_minutes` read `330` in both runs: run 2 landed inside the same wall-clock minute as run 1,
  and `age_minutes` floors.
* The run is **honest about being unexciting**: a fully healthy cycle exercises the happy path only.
  The truncation, gap, fallback and `NoCycleAvailable` paths were not reached by live data and rest
  entirely on the offline tests — that is a coverage fact worth carrying into F3, not a complaint.
