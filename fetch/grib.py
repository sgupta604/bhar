"""S3 key building, ranged GRIB fetch, cfgrib point decode (T2, Stream 3).

`fetch_point()` is the single primitive T4 thread-pools: build the S3 key, read the
`.idx`, select the anchored `:TMP:2 m above ground:` record, range-GET exactly that
message, decode it with cfgrib, take the nearest grid cell to KOMA and convert K to F.

Invariants this module is required to hold:

* **Pure per-call.** No module-level session, no cache, no global state, at most one
  retry — T4 must be able to thread-pool `fetch_point` untouched.
* **No hardcoded message index.** The `.idx` is parsed every time; NBM's index moves
  with lead time (spike F10).
* **No interpolation.** Nearest cell by plain euclidean degrees (SPEC §5).
* **UTC everywhere**, degrees F at the boundary; Kelvin never leaves `decode_point`.
* **SPEC §11 R1 (Open-Meteo) is RETIRED and FORBIDDEN.** There is no fallback source.
  An unreachable NOAA archive is a SPEC §9 hard stop.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
import xarray as xr

from fetch.idx import byte_range, parse_idx, range_header, select_tmp_2m

# --- constants -------------------------------------------------------------------------

KOMA_LAT, KOMA_LON = 41.3032, -95.8941
MODELS = ("hrrr", "gfs", "nam", "nbm")

# Verified S3 key patterns (spike F2/F10). Host is https://{bucket}.s3.amazonaws.com/{key};
# the `.idx` URL is the GRIB URL plus ".idx". Buckets are public — no credentials.
# {d}=YYYYMMDD  {h}=init HH  {ff}=2-digit lead  {fff}=3-digit lead
_KEYS: dict[str, tuple[str, str]] = {
    "hrrr": ("noaa-hrrr-bdp-pds", "hrrr.{d}/conus/hrrr.t{h}z.wrfsfcf{ff}.grib2"),
    "gfs": ("noaa-gfs-bdp-pds", "gfs.{d}/{h}/atmos/gfs.t{h}z.pgrb2.0p25.f{fff}"),
    "nam": ("noaa-nam-pds", "nam.{d}/nam.t{h}z.awphys{ff}.tm00.grib2"),
    # ".co" is CONUS. ak/hi/pr/gu exist and are WRONG for KOMA (spike F10).
    "nbm": ("noaa-nbm-grib2-pds", "blend.{d}/{h}/core/blend.t{h}z.core.f{fff}.co.grib2"),
}

_SANITY_DEG = 0.5  # SPEC §5: a nearest cell further than this means the search went wrong.
_TIMEOUT = 120


# --- time ------------------------------------------------------------------------------


def _as_utc(moment: datetime) -> datetime:
    """SPEC §2 (UTC everywhere): a naive datetime is UTC, never local time."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def valid_time(init_time: datetime, lead_h: int) -> datetime:
    """`init_time + lead_h` hours, timezone-aware UTC (SPEC §2)."""
    return _as_utc(init_time) + timedelta(hours=lead_h)


# --- urls ------------------------------------------------------------------------------


def build_urls(model: str, init_time: datetime, lead_h: int) -> tuple[str, str]:
    """Return `(grib_url, idx_url)` for a model run (spike F2/F10 verified keys)."""
    if model not in _KEYS:
        raise ValueError(
            f"SPEC §3 names exactly {MODELS}; got model={model!r}. "
            "There is no fallback source (SPEC §11 R1 is RETIRED)."
        )
    bucket, template = _KEYS[model]
    init_utc = _as_utc(init_time)
    key = template.format(
        d=init_utc.strftime("%Y%m%d"),
        h=init_utc.strftime("%H"),
        ff=f"{lead_h:02d}",
        fff=f"{lead_h:03d}",
    )
    grib_url = f"https://{bucket}.s3.amazonaws.com/{key}"
    return grib_url, grib_url + ".idx"


# --- geometry and units ------------------------------------------------------------------


def normalize_lon(lon):
    """Fold longitudes into [-180, 180). GFS is 0-360; skip this and the distance math lies."""
    return ((lon + 180.0) % 360.0) - 180.0


def kelvin_to_f(kelvin: float) -> float:
    """`F = (K - 273.15) * 9/5 + 32` (SPEC §2). Kelvin never escapes the decoder."""
    return (float(kelvin) - 273.15) * 9.0 / 5.0 + 32.0


def nearest_cell(
    lats, lons, lat: float = KOMA_LAT, lon: float = KOMA_LON
) -> tuple[tuple[int, ...], float, float, float]:
    """Nearest grid cell to `(lat, lon)` by plain euclidean degrees. **No interpolation.**

    Handles both 1-D coordinate vectors (GFS) and 2-D curvilinear grids (HRRR/NAM/NBM):
    1-D inputs are broadcast to a mesh first, then `argmin` runs over the flattened
    distance array.

    Returns `(index, grid_lat, grid_lon, distance_deg)`.
    """
    lat_arr = np.asarray(lats, dtype=float)
    lon_arr = normalize_lon(np.asarray(lons, dtype=float))

    if lat_arr.ndim == 1 and lon_arr.ndim == 1:
        mesh_lat, mesh_lon = np.meshgrid(lat_arr, lon_arr, indexing="ij")
    elif lat_arr.ndim == 2 and lon_arr.ndim == 2:
        mesh_lat, mesh_lon = lat_arr, lon_arr
    else:
        raise AssertionError(
            f"SPEC §5: unsupported coordinate shapes lat{lat_arr.shape} lon{lon_arr.shape}; "
            "expected 1-D vectors (GFS) or 2-D curvilinear arrays (HRRR/NAM/NBM)"
        )

    dist = np.sqrt((mesh_lat - lat) ** 2 + (mesh_lon - normalize_lon(lon)) ** 2)
    index = tuple(int(i) for i in np.unravel_index(int(np.argmin(dist)), dist.shape))
    return index, float(mesh_lat[index]), float(mesh_lon[index]), float(dist[index])


# --- decode ------------------------------------------------------------------------------


def decode_point(grib_path: Path, lat: float = KOMA_LAT, lon: float = KOMA_LON) -> dict:
    """Decode one GRIB message and return the nearest-cell temperature in degrees F.

    Returns `{"temp_f", "grid_lat", "grid_lon", "distance_deg"}`.

    Asserts the decoded variable is 2 m temperature. Note (Stream 1 finding): cfgrib
    names the data variable `t2m`, but eccodes' `GRIB_shortName` attribute on it is
    `"2t"` — comparing GRIB_shortName to "t2m" fails on valid data, so the guard is on
    the data-variable name and `GRIB_cfVarName`, plus an explicit rejection of `aptmp`
    (APTMP is NBM message 1; the unanchored needle silently returns it — spike F9).
    """
    path = Path(grib_path)
    # indexpath="" is mandatory: cfgrib must not drop a sidecar index next to a fixture.
    with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as ds:
        data_vars = list(ds.data_vars)
        if "aptmp" in data_vars:
            raise AssertionError(
                f"spike F9: apparent temperature (aptmp) decoded from {path.name}; the "
                f"anchored needle ':TMP:2 m above ground:' selected the wrong message. "
                f"data_vars={data_vars}"
            )
        if "t2m" not in data_vars:
            raise AssertionError(
                f"SPEC §3 / spike F9: the decoded variable must be 't2m' (2 m temperature), "
                f"never 'aptmp'; got data_vars={data_vars} in {path.name}"
            )
        da = ds["t2m"]
        cf_var = da.attrs.get("GRIB_cfVarName")
        if cf_var is not None and cf_var != "t2m":
            raise AssertionError(
                f"SPEC §3 / spike F9: GRIB_cfVarName must be 't2m', got {cf_var!r} in "
                f"{path.name} (GRIB_shortName is '2t' on valid data and is not checked)"
            )

        index, grid_lat, grid_lon, distance_deg = nearest_cell(
            ds["latitude"].values, ds["longitude"].values, lat, lon
        )

        values = np.asarray(da.values, dtype=float)
        if len(index) != values.ndim or any(
            i >= n for i, n in zip(index, values.shape, strict=True)
        ):
            raise AssertionError(
                f"SPEC §5: grid index {index} does not address the value array of shape "
                f"{values.shape} in {path.name} — coordinate and data shapes disagree"
            )

        if distance_deg > _SANITY_DEG:
            raise AssertionError(
                f"SPEC §5: nearest cell ({grid_lat:.4f}, {grid_lon:.4f}) is "
                f"{distance_deg:.4f} deg from ({lat}, {lon}), beyond the {_SANITY_DEG} deg "
                f"sanity floor, in {path.name}"
            )

        return {
            "temp_f": kelvin_to_f(float(values[index])),
            "grid_lat": grid_lat,
            "grid_lon": grid_lon,
            "distance_deg": distance_deg,
        }


# --- http --------------------------------------------------------------------------------


class ArchiveMissing(RuntimeError):
    """The requested key is absent from the NOAA archive (HTTP 404/403).

    **SPEC §11 R2: an archive hole is an expected result, not a hard stop.** Runs go
    missing from the public buckets — HRRR especially — and a backfill must *record*
    the gap, count it into the coverage denominator, and carry on. It must never abort.

    Subclasses `RuntimeError` deliberately: every pre-existing caller that catches
    `RuntimeError` keeps working unchanged, so this addition is purely additive.

    A 404/403 is **never retried** — a key that does not exist will not exist five
    seconds later. Every *other* non-200 status still raises a plain `RuntimeError`
    citing SPEC §9, because that genuinely is a hard stop.
    """


def _get(url: str, headers: dict | None = None) -> requests.Response:
    """One GET with at most ONE retry. No shared session — `fetch_point` is pure per-call."""
    last_exc: Exception | None = None
    for _ in range(2):  # initial attempt + at most one retry
        try:
            return requests.get(url, headers=headers, timeout=_TIMEOUT)
        except requests.RequestException as exc:  # transient socket/DNS failure
            last_exc = exc
    raise RuntimeError(
        f"SPEC §9 hard stop: GET {url} failed twice ({last_exc}). NOAA is the only source; "
        "Open-Meteo (SPEC §11 R1) is RETIRED and FORBIDDEN."
    ) from last_exc


# --- the T4 primitive ----------------------------------------------------------------------


def fetch_point(model: str, init_time: datetime, lead_h: int) -> dict:
    """Fetch, decode and point-extract one forecast. Pure per-call; safe to thread-pool.

    Returns `{"model", "init_time", "lead_h", "valid_time", "temp_f", "grid_lat",
    "grid_lon", "distance_deg"}`.
    """
    grib_url, idx_url = build_urls(model, init_time, lead_h)

    idx_resp = _get(idx_url)
    if idx_resp.status_code in (403, 404):
        raise ArchiveMissing(
            f"SPEC §11 R2: GET {idx_url} returned HTTP {idx_resp.status_code} — the run is "
            "absent from the archive. An archive hole is an expected result, not a hard stop."
        )
    if idx_resp.status_code != 200:
        raise RuntimeError(
            f"SPEC §9 hard stop: GET {idx_url} returned HTTP {idx_resp.status_code}. "
            "Open-Meteo (SPEC §11 R1) is RETIRED and FORBIDDEN."
        )

    records = parse_idx(idx_resp.text)
    chosen = select_tmp_2m(records)
    start, end = byte_range(records, chosen)
    header = range_header(start, end)

    resp = _get(grib_url, headers={"Range": header})
    if resp.status_code in (403, 404):
        raise ArchiveMissing(
            f"SPEC §11 R2: ranged GET {grib_url} [{header}] returned HTTP "
            f"{resp.status_code} — the object is absent from the archive. An archive hole "
            "is an expected result, not a hard stop."
        )
    if resp.status_code not in (206, 200):
        raise RuntimeError(
            f"SPEC §9 hard stop: ranged GET {grib_url} [{header}] returned HTTP "
            f"{resp.status_code} (expected 206 or 200)."
        )
    body = resp.content
    if not body.startswith(b"GRIB"):
        raise RuntimeError(
            f"ranged GET {grib_url} [{header}] did not return a GRIB message: body starts "
            f"with {body[:8]!r} ({len(body)} bytes). The .idx byte range is wrong."
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        scratch = Path(tmpdir) / f"{model}_{lead_h:03d}.bin"
        scratch.write_bytes(body)
        point = decode_point(scratch)

    init_utc = _as_utc(init_time)
    return {
        "model": model,
        "init_time": init_utc,
        "lead_h": lead_h,
        "valid_time": valid_time(init_utc, lead_h),
        **point,
    }
