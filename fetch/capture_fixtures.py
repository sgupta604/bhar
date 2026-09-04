"""Live NOAA probe + one-pass offline fixture capture (T2, Task 1.1).

Dev-only script. It is **never** imported by pytest and it deliberately imports neither
``fetch.idx`` nor ``fetch.grib``: it is the independent witness those modules are checked
against. If the probe and the implementation shared code, a shared bug would prove itself
correct.

Run:  uv run python -m fetch.capture_fixtures

It fetches the `.idx` and the anchored ``:TMP:2 m above ground:`` GRIB message for
HRRR/GFS/NAM/NBM at 2026-08-05 12z f006, writes the offline corpus under tests/fixtures/,
decodes each message, prints the nearest-cell temperature in degrees F, and refuses to
finish if any written fixture is gitignored.

Acceptance floor (SPEC 8): HRRR 68.24 | GFS 71.65 | NAM 69.53 | NBM 70.61, abs(diff) < 0.01.
That tolerance is NEVER widened (SPEC 10).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import requests
import xarray as xr

# --- constants -------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
IDX_DIR = FIXTURES / "idx"
GRIB_DIR = FIXTURES / "grib"
SCRATCH = REPO_ROOT / "data" / "raw"

KOMA_LAT, KOMA_LON = 41.3032, -95.8941

NEEDLE = ":TMP:2 m above ground:"  # the leading colon is load-bearing (spike F9)
REJECT = "ens std dev"

DATE = "20260805"
INIT_HH = "12"

# model -> (bucket, key template). {d}=YYYYMMDD {h}=init HH {ff}=2-digit lead {fff}=3-digit lead
KEYS = {
    "hrrr": ("noaa-hrrr-bdp-pds", "hrrr.{d}/conus/hrrr.t{h}z.wrfsfcf{ff}.grib2"),
    "gfs": ("noaa-gfs-bdp-pds", "gfs.{d}/{h}/atmos/gfs.t{h}z.pgrb2.0p25.f{fff}"),
    "nam": ("noaa-nam-pds", "nam.{d}/nam.t{h}z.awphys{ff}.tm00.grib2"),
    "nbm": ("noaa-nbm-grib2-pds", "blend.{d}/{h}/core/blend.t{h}z.core.f{fff}.co.grib2"),
}

EXPECTED_F = {"hrrr": 68.24, "gfs": 71.65, "nam": 69.53, "nbm": 70.61}
TOLERANCE = 0.01  # SPEC 10: NEVER widen this.

TIMEOUT = 120


# --- url building ----------------------------------------------------------------------


def build_urls(model: str, lead_h: int) -> tuple[str, str]:
    """Return (grib_url, idx_url) for a model at 2026-08-05 12z and the given lead."""
    bucket, tmpl = KEYS[model]
    key = tmpl.format(d=DATE, h=INIT_HH, ff=f"{lead_h:02d}", fff=f"{lead_h:03d}")
    grib_url = f"https://{bucket}.s3.amazonaws.com/{key}"
    return grib_url, grib_url + ".idx"


# --- idx handling (self-contained; NOT imported from fetch.idx) --------------------------


def parse_idx(text: str) -> list[dict]:
    """Parse `.idx` text into records. Message numbers stay STRINGS (NAM has 284.1/284.2)."""
    records: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        fields = line.split(":")
        if len(fields) < 6:
            raise ValueError(f"malformed .idx line (expected >=6 colon fields): {line!r}")
        records.append(
            {
                "msg": fields[0],  # str, never int() (spike/research D6)
                "start": int(fields[1]),
                "date": fields[2],
                "var": fields[3],
                "level": fields[4],
                "fcst": fields[5],
                "extra": ":".join(fields[6:]),
                "raw": line,
            }
        )
    if not records:
        raise ValueError("empty .idx")
    return records


def select_tmp_2m(records: list[dict]) -> dict:
    """Anchored selection (spike F9). Exactly one line must survive, else raise."""
    hits = [r for r in records if NEEDLE in r["raw"] and REJECT not in r["raw"]]
    if len(hits) != 1:
        raise ValueError(
            f"SPEC 3 / spike F9: expected exactly 1 line matching {NEEDLE!r} without "
            f"{REJECT!r}, got {len(hits)}: {[h['raw'] for h in hits]}"
        )
    return hits[0]


def byte_range(records: list[dict], chosen: dict) -> tuple[int, int | None]:
    """End = next entry with a STRICTLY GREATER start offset, minus 1; else open-ended."""
    start = chosen["start"]
    later = [r["start"] for r in records if r["start"] > start]
    if not later:
        return start, None
    return start, min(later) - 1


def range_header(start: int, end: int | None) -> str:
    return f"bytes={start}-" if end is None else f"bytes={start}-{end}"


# --- decode ----------------------------------------------------------------------------


def normalize_lon(lon):
    """GFS is 0-360; fold everything into [-180, 180) before any distance math."""
    return ((lon + 180.0) % 360.0) - 180.0


def decode_point(path: Path, lat: float = KOMA_LAT, lon: float = KOMA_LON) -> dict:
    """Decode one captured GRIB message; nearest cell to (lat, lon); K -> F. No interpolation."""
    # indexpath="" is mandatory: no cfgrib sidecar may land next to a fixture.
    with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as ds:
        if "t2m" not in ds.data_vars:
            raise AssertionError(
                f"SPEC 3 / spike F9: decoded short name must be 't2m', never 'aptmp'; "
                f"got data_vars={list(ds.data_vars)} in {path.name}"
            )
        if "aptmp" in ds.data_vars:
            raise AssertionError(
                f"SPEC 3 / spike F9: apparent temperature decoded from {path.name}; "
                "the anchored needle failed"
            )
        da = ds["t2m"]
        # cfgrib names the variable 't2m'; eccodes' own shortName for 2 m temperature is '2t'
        # and its cfVarName is 't2m'. Accept both spellings of the same message, reject aptmp.
        grib_short = da.attrs.get("GRIB_shortName")
        grib_cfvar = da.attrs.get("GRIB_cfVarName")
        if grib_short is not None and grib_short not in ("t2m", "2t"):
            raise AssertionError(
                f"SPEC 3 / spike F9: GRIB_shortName must be 2 m temperature ('t2m'/'2t'), "
                f"got {grib_short!r}"
            )
        if grib_cfvar is not None and grib_cfvar != "t2m":
            raise AssertionError(
                f"SPEC 3 / spike F9: GRIB_cfVarName must be 't2m', got {grib_cfvar!r}"
            )

        lats = np.asarray(ds["latitude"].values, dtype=float)
        lons = normalize_lon(np.asarray(ds["longitude"].values, dtype=float))
        values = np.asarray(da.values, dtype=float)

        if lats.ndim == 1 and lons.ndim == 1:
            # GFS: 1-D coordinate vectors -> broadcast to a mesh.
            mesh_lat, mesh_lon = np.meshgrid(lats, lons, indexing="ij")
        elif lats.ndim == 2 and lons.ndim == 2:
            # HRRR / NAM / NBM: 2-D curvilinear grids.
            mesh_lat, mesh_lon = lats, lons
        else:
            raise AssertionError(
                f"unsupported coordinate shapes lat{lats.shape} lon{lons.shape} in {path.name}"
            )

        if values.shape != mesh_lat.shape:
            raise AssertionError(
                f"value shape {values.shape} does not match grid shape {mesh_lat.shape} "
                f"in {path.name}"
            )

        # Plain euclidean degrees (research D7) - reproduces spike F11's printed distances.
        dist = np.sqrt((mesh_lat - lat) ** 2 + (mesh_lon - normalize_lon(lon)) ** 2)
        flat = int(np.argmin(dist))
        idx = np.unravel_index(flat, dist.shape)

        distance_deg = float(dist[idx])
        if distance_deg > 0.5:
            raise AssertionError(
                f"SPEC 5: nearest cell is {distance_deg:.4f} deg from KOMA, > 0.5 deg floor "
                f"in {path.name}"
            )

        kelvin = float(values[idx])
        return {
            "temp_f": (kelvin - 273.15) * 9.0 / 5.0 + 32.0,
            "grid_lat": float(mesh_lat[idx]),
            "grid_lon": float(mesh_lon[idx]),
            "distance_deg": distance_deg,
        }


# --- http ------------------------------------------------------------------------------


def get_idx_text(idx_url: str) -> str:
    resp = requests.get(idx_url, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(
            f"SPEC 9 hard stop: GET {idx_url} returned HTTP {resp.status_code}. "
            "NOAA archive unreachable. Open-Meteo (SPEC 11 R1) is RETIRED and FORBIDDEN."
        )
    return resp.text


def get_message_bytes(grib_url: str, header: str) -> bytes:
    resp = requests.get(grib_url, headers={"Range": header}, timeout=TIMEOUT)
    if resp.status_code not in (206, 200):
        raise RuntimeError(
            f"SPEC 9 hard stop: ranged GET {grib_url} [{header}] returned "
            f"HTTP {resp.status_code} (expected 206 or 200)."
        )
    body = resp.content
    if not body.startswith(b"GRIB"):
        raise RuntimeError(
            f"ranged GET {grib_url} [{header}] did not return a GRIB message: "
            f"body starts with {body[:8]!r}"
        )
    return body


# --- trackability gate ------------------------------------------------------------------


def assert_trackable(paths: list[Path]) -> None:
    """Fail loudly if any written fixture is gitignored (.gitignore:24 is *.grib2)."""
    ignored = []
    for p in paths:
        rel = p.relative_to(REPO_ROOT)
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if result.returncode == 0:
            ignored.append(str(rel))
    if ignored:
        print("\nFAIL: fixture files are GITIGNORED and would vanish on a clean clone:")
        for name in ignored:
            print(f"  - {name}")
        sys.exit(1)
    print(f"\ngit check-ignore gate: OK - all {len(paths)} fixture files are trackable.")


# --- main ------------------------------------------------------------------------------


def capture_idx(model: str, lead_h: int) -> tuple[Path, list[dict], dict]:
    """Fetch and save one `.idx` verbatim; return (path, records, chosen record)."""
    grib_url, idx_url = build_urls(model, lead_h)
    text = get_idx_text(idx_url)
    path = IDX_DIR / f"{model}_{DATE}_{INIT_HH}z_f{lead_h:03d}.idx"
    path.write_text(text, encoding="utf-8")
    records = parse_idx(text)
    chosen = select_tmp_2m(records)
    return path, records, chosen


def main() -> int:
    IDX_DIR.mkdir(parents=True, exist_ok=True)
    GRIB_DIR.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    results: dict[str, dict] = {}

    print("=" * 88)
    print("LIVE PROBE + FIXTURE CAPTURE - 2026-08-05 12z f006 - nearest cell to KOMA "
          f"({KOMA_LAT}, {KOMA_LON})")
    print("=" * 88)

    for model in ("hrrr", "gfs", "nam", "nbm"):
        grib_url, _ = build_urls(model, 6)
        idx_path, records, chosen = capture_idx(model, 6)
        written.append(idx_path)

        start, end = byte_range(records, chosen)
        header = range_header(start, end)
        body = get_message_bytes(grib_url, header)

        bin_path = GRIB_DIR / f"{model}_{DATE}_{INIT_HH}z_f006_t2m.bin"
        bin_path.write_bytes(body)
        written.append(bin_path)

        # Decode from a scratch copy so nothing cfgrib may touch sits in tests/fixtures/.
        scratch = SCRATCH / bin_path.name
        scratch.write_bytes(body)
        point = decode_point(scratch)

        results[model] = {
            "msg": chosen["msg"],
            "range": header,
            "bytes": len(body),
            "url": grib_url,
            "idx_url": grib_url + ".idx",
            **point,
        }

        print(
            f"{model.upper():5s} msg={chosen['msg']:>7s}  range={header:<28s} "
            f"size={len(body):>9,d}B  cell=({point['grid_lat']:.4f}, {point['grid_lon']:.4f})  "
            f"dist={point['distance_deg']:.3f} deg  temp_f={point['temp_f']:.2f}"
        )

    # NBM index text only for the extra leads - proves the index moves (187 / 192 / 195).
    nbm_extra: dict[int, dict] = {}
    print("-" * 88)
    for lead_h in (12, 24):
        grib_url, _ = build_urls("nbm", lead_h)
        idx_path, records, chosen = capture_idx("nbm", lead_h)
        written.append(idx_path)
        start, end = byte_range(records, chosen)
        nbm_extra[lead_h] = {
            "msg": chosen["msg"],
            "range": range_header(start, end),
            "url": grib_url,
            "idx_url": grib_url + ".idx",
        }
        print(
            f"NBM   f{lead_h:03d} .idx only  msg={chosen['msg']:>7s}  "
            f"range={nbm_extra[lead_h]['range']}  -> {idx_path.name}"
        )

    assert_trackable(written)

    print()
    print("=" * 88)
    print("SUMMARY - acceptance floor (SPEC 8), tolerance abs(diff) < 0.01 - NEVER widened")
    print("=" * 88)
    print(f"{'MODEL':6s} {'ACTUAL F':>10s} {'EXPECTED F':>11s} {'DIFF':>9s}  RESULT")
    failures = []
    for model in ("hrrr", "gfs", "nam", "nbm"):
        actual = results[model]["temp_f"]
        expected = EXPECTED_F[model]
        diff = actual - expected
        ok = abs(diff) < TOLERANCE
        if not ok:
            failures.append(model)
        print(
            f"{model.upper():6s} {actual:10.2f} {expected:11.2f} {diff:9.4f}  "
            f"{'PASS' if ok else 'FAIL'}"
        )
    print("-" * 88)
    print(
        "temp_f: HRRR {hrrr:.2f} F | GFS {gfs:.2f} F | NAM {nam:.2f} F | NBM {nbm:.2f} F".format(
            **{m: results[m]["temp_f"] for m in results}
        )
    )
    print(
        f"NBM .idx message numbers: f006={results['nbm']['msg']} "
        f"f012={nbm_extra[12]['msg']} f024={nbm_extra[24]['msg']}"
    )
    print(f"Fixtures written: {len(written)} files under tests/fixtures/")
    print("=" * 88)

    if failures:
        print(f"\nFAIL: {', '.join(f.upper() for f in failures)} outside tolerance. "
              "This is a finding to REPORT (SPEC 10), not a number to adjust.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
