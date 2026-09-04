"""T2 Stream 3 tests — S3 key building, cfgrib point decode, K→F, nearest cell.

SPEC §13: **no live network in pytest.** Every byte read here comes from
`tests/fixtures/` (see its README for provenance). An autouse fixture below makes
that structural: any attempt to open a socket inside this module fails the test.

SPEC §8 acceptance floor (2026-08-05 12z f006, valid 18:00Z, nearest cell to KOMA):
HRRR 68.24 | GFS 71.65 | NAM 69.53 | NBM 70.61 at ``abs(diff) < 0.01``.
SPEC §10: that tolerance is NEVER widened. A miss means the wrong cell or the wrong
variable — stop and report, do not turn the knob.
"""

import inspect
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from fetch import grib

INIT_2026_08_05_12Z = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)

# SPEC §8 acceptance floor. Fourth column is spike F11's nearest cell + distance.
# temp tolerance 0.01 (SPEC §10, never widened); lat/lon/distance are quoted to
# 4/3 decimals in tests/fixtures/README.md, hence 0.001.
ACCEPTANCE = {
    "hrrr": {"temp_f": 68.24, "grid_lat": 41.2914, "grid_lon": -95.8923, "distance_deg": 0.012},
    "gfs": {"temp_f": 71.65, "grid_lat": 41.2500, "grid_lon": -96.0000, "distance_deg": 0.119},
    "nam": {"temp_f": 69.53, "grid_lat": 41.2864, "grid_lon": -95.9305, "distance_deg": 0.040},
    "nbm": {"temp_f": 70.61, "grid_lat": 41.3034, "grid_lon": -95.9029, "distance_deg": 0.009},
}

TEMP_TOLERANCE = 0.01  # SPEC §10: NEVER widen this.
CELL_TOLERANCE = 0.001
SANITY_DEG = 0.5  # SPEC §5 sanity floor on the nearest-cell search.

EXPECTED_URLS = {
    "hrrr": (
        "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/"
        "hrrr.20260805/conus/hrrr.t12z.wrfsfcf06.grib2"
    ),
    "gfs": (
        "https://noaa-gfs-bdp-pds.s3.amazonaws.com/"
        "gfs.20260805/12/atmos/gfs.t12z.pgrb2.0p25.f006"
    ),
    "nam": (
        "https://noaa-nam-pds.s3.amazonaws.com/nam.20260805/nam.t12z.awphys06.tm00.grib2"
    ),
    "nbm": (
        "https://noaa-nbm-grib2-pds.s3.amazonaws.com/"
        "blend.20260805/12/core/blend.t12z.core.f006.co.grib2"
    ),
}


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §13: no test in this module may open a socket.

    Structural, not a promise in a docstring — if a decode path ever grows a live
    fetch, the tests turn red instead of silently going to the network.
    """

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "SPEC §13 violation: a test in tests/test_grib.py tried to open a network "
            "socket. Every byte must come from tests/fixtures/."
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def grib_fixture(fixtures: Path, model: str) -> Path:
    path = fixtures / "grib" / f"{model}_20260805_12z_f006_t2m.bin"
    assert path.exists(), (
        f"missing captured fixture for {model.upper()} at {path}; SPEC §13 forbids "
        "falling back to a live fetch — re-run fetch/capture_fixtures.py"
    )
    size = path.stat().st_size
    assert size > 0, f"captured fixture {path} is 0 bytes; a zero-byte fixture scores fake"
    return path


# --- build_urls (pure strings, no network) ----------------------------------------------


@pytest.mark.parametrize("model", sorted(EXPECTED_URLS))
def test_build_urls_matches_verified_key_pattern(model: str) -> None:
    """Spike F2/F10 verified S3 keys for 2026-08-05 12z f006."""
    grib_url, idx_url = grib.build_urls(model, INIT_2026_08_05_12Z, 6)
    assert grib_url == EXPECTED_URLS[model], (
        f"spike F2/F10 verified key for {model.upper()} 2026-08-05 12z f006 is\n"
        f"  {EXPECTED_URLS[model]}\nbuild_urls returned\n  {grib_url}"
    )
    assert idx_url == EXPECTED_URLS[model] + ".idx", (
        f"spike F2: the .idx URL is the GRIB URL plus '.idx'; for {model.upper()} got {idx_url}"
    )


def test_build_urls_lead_digit_widths() -> None:
    """GFS/NBM take a 3-digit lead; HRRR/NAM take 2 (spike F2)."""
    two_digit = {"hrrr": "wrfsfcf06", "nam": "awphys06"}
    for model, token in two_digit.items():
        url, _ = grib.build_urls(model, INIT_2026_08_05_12Z, 6)
        assert token in url, (
            f"spike F2: {model.upper()} uses a 2-digit lead ('{token}'); got {url}"
        )
    three_digit = {"gfs": "0p25.f006", "nbm": "core.f006"}
    for model, token in three_digit.items():
        url, _ = grib.build_urls(model, INIT_2026_08_05_12Z, 6)
        assert token in url, (
            f"spike F2: {model.upper()} uses a 3-digit lead ('{token}'); got {url}"
        )


def test_build_urls_lead_widths_hold_at_two_and_three_digits() -> None:
    """f012/f024 must keep the same zero padding — no `f12`/`f1200` drift."""
    for lead, hrrr_token, gfs_token in ((12, "wrfsfcf12", "0p25.f012"), (24, "wrfsfcf24", "0p25.f024")):
        hrrr_url, _ = grib.build_urls("hrrr", INIT_2026_08_05_12Z, lead)
        gfs_url, _ = grib.build_urls("gfs", INIT_2026_08_05_12Z, lead)
        assert hrrr_token in hrrr_url, f"spike F2: HRRR f{lead:03d} key wrong: {hrrr_url}"
        assert gfs_token in gfs_url, f"spike F2: GFS f{lead:03d} key wrong: {gfs_url}"


def test_build_urls_nbm_is_conus_not_ak_hi_pr_gu() -> None:
    """Spike F10: NBM ships ak/hi/pr/gu domains; only `.co` covers KOMA."""
    url, _ = grib.build_urls("nbm", INIT_2026_08_05_12Z, 6)
    assert ".co.grib2" in url, (
        f"spike F10: NBM must use the '.co' CONUS domain for KOMA; got {url}"
    )
    for wrong in (".ak.", ".hi.", ".pr.", ".gu."):
        assert wrong not in url, (
            f"spike F10: NBM URL uses the {wrong!r} domain, which is not CONUS: {url}"
        )


def test_build_urls_uses_the_init_time_it_is_given() -> None:
    """Date and init hour come from `init_time`, never from a module constant."""
    url, _ = grib.build_urls("hrrr", datetime(2026, 8, 6, 18, 0, tzinfo=timezone.utc), 6)
    assert "hrrr.20260806/" in url and "t18z" in url, (
        f"build_urls ignored its init_time argument (expected 20260806 / t18z): {url}"
    )


def test_build_urls_rejects_unknown_model() -> None:
    with pytest.raises((KeyError, ValueError)):
        grib.build_urls("ecmwf", INIT_2026_08_05_12Z, 6)


def test_models_tuple_is_the_four_spec_models() -> None:
    assert grib.MODELS == ("hrrr", "gfs", "nam", "nbm"), (
        f"SPEC §3 names exactly four models; fetch.grib.MODELS is {grib.MODELS!r}"
    )


def test_koma_coordinates() -> None:
    assert (grib.KOMA_LAT, grib.KOMA_LON) == (41.3032, -95.8941), (
        f"SPEC §5: KOMA is (41.3032, -95.8941); got ({grib.KOMA_LAT}, {grib.KOMA_LON})"
    )


# --- valid_time -------------------------------------------------------------------------


@pytest.mark.parametrize("lead_h", [0, 1, 6, 12, 24, 48])
def test_valid_time_is_init_plus_lead_utc(lead_h: int) -> None:
    """SPEC §2: valid_time = init_time + lead, timezone-aware UTC."""
    got = grib.valid_time(INIT_2026_08_05_12Z, lead_h)
    expected = INIT_2026_08_05_12Z + timedelta(hours=lead_h)
    assert got == expected, f"SPEC §2: expected valid_time {expected}, got {got}"
    assert got.tzinfo is not None, f"SPEC §2 (UTC everywhere): valid_time {got} is naive"
    assert got.utcoffset() == timedelta(0), (
        f"SPEC §2 (UTC everywhere): valid_time {got} has offset {got.utcoffset()}, expected UTC"
    )


def test_valid_time_f006_is_1800z() -> None:
    """The acceptance-floor case: 2026-08-05 12z + 6 h = 2026-08-05 18:00Z."""
    got = grib.valid_time(INIT_2026_08_05_12Z, 6)
    assert got == datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc), (
        f"SPEC §8: 12z f006 is valid 2026-08-05 18:00Z; got {got.isoformat()}"
    )


def test_valid_time_treats_a_naive_init_as_utc() -> None:
    """SPEC §2 UTC everywhere: a naive init_time is UTC, never local time."""
    got = grib.valid_time(datetime(2026, 8, 5, 12, 0), 6)
    assert got == datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc), (
        f"SPEC §2: a naive init_time must be read as UTC; got {got.isoformat()}"
    )


# --- kelvin -> fahrenheit ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("kelvin", "expected_f"),
    [(273.15, 32.0), (300.0, 80.33), (255.372222222222, -0.0), (310.9277777777778, 100.0)],
)
def test_kelvin_to_f(kelvin: float, expected_f: float) -> None:
    """SPEC §2: F = (K - 273.15) * 9/5 + 32. Kelvin never escapes the decoder."""
    got = grib.kelvin_to_f(kelvin)
    assert abs(got - expected_f) < 1e-9, (
        f"SPEC §2 unit conversion: {kelvin} K should be {expected_f} F, got {got!r}"
    )


# --- longitude normalization ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(264.1059, -95.8941), (-95.8941, -95.8941), (0.0, 0.0), (359.75, -0.25), (180.0, -180.0)],
)
def test_normalize_lon(raw: float, expected: float) -> None:
    """GFS is 0-360; fold to [-180, 180) with ((lon + 180) % 360) - 180 before distance math."""
    got = float(grib.normalize_lon(raw))
    assert abs(got - expected) < 1e-9, (
        f"SPEC §5 / plan note: normalize_lon({raw}) should be {expected}, got {got}"
    )


def test_normalize_lon_is_vectorized() -> None:
    got = grib.normalize_lon(np.array([264.1059, 0.0, 359.75]))
    assert np.allclose(got, np.array([-95.8941, 0.0, -0.25])), (
        f"normalize_lon must work on numpy arrays (GFS/HRRR grids); got {got!r}"
    )


# --- nearest cell -----------------------------------------------------------------------


def test_nearest_cell_handles_1d_coords_and_normalizes_lon() -> None:
    """GFS decodes 1-D lat/lon vectors in 0-360; broadcast to a mesh, then argmin."""
    lats = np.array([40.0, 41.0, 42.0])
    lons = np.array([264.0, 95.0])  # 264 -> -96.0 (near KOMA); 95 stays 95 (far)
    idx, grid_lat, grid_lon, distance = grib.nearest_cell(lats, lons)
    assert (grid_lat, grid_lon) == (41.0, -96.0), (
        "SPEC §5: 1-D GFS coords must be meshed and longitudes normalized with "
        f"((lon + 180) % 360) - 180 before distance math; got cell ({grid_lat}, {grid_lon}) "
        f"at index {idx}"
    )
    expected_d = ((41.0 - grib.KOMA_LAT) ** 2 + (-96.0 - grib.KOMA_LON) ** 2) ** 0.5
    assert abs(distance - expected_d) < 1e-9, (
        f"plain euclidean degrees expected {expected_d}, got {distance}"
    )


def test_nearest_cell_handles_2d_curvilinear_coords() -> None:
    """HRRR / NAM / NBM decode to 2-D curvilinear grids."""
    lats = np.array([[41.0, 41.0], [41.3, 41.3]])
    lons = np.array([[-96.5, -95.9], [-96.5, -95.9]])
    idx, grid_lat, grid_lon, distance = grib.nearest_cell(lats, lons)
    assert (grid_lat, grid_lon) == (41.3, -95.9), (
        "SPEC §5: 2-D curvilinear coords must be searched cell-by-cell; got "
        f"({grid_lat}, {grid_lon}) at index {idx}"
    )
    assert idx == (1, 1), f"expected flat argmin to unravel to (1, 1), got {idx}"
    assert distance < 0.05, f"nearest cell distance {distance} deg is implausible for this grid"


def test_nearest_cell_does_not_interpolate() -> None:
    """SPEC §5: pick an actual grid cell. The answer must be a value that is ON the grid."""
    lats = np.array([[41.0, 41.0], [41.9, 41.9]])
    lons = np.array([[-96.4, -95.4], [-96.4, -95.4]])
    _, grid_lat, grid_lon, _ = grib.nearest_cell(lats, lons)
    assert grid_lat in set(lats.ravel().tolist()), (
        f"SPEC §5 forbids interpolation: {grid_lat} is not one of the grid latitudes "
        f"{sorted(set(lats.ravel().tolist()))}"
    )
    assert grid_lon in set(lons.ravel().tolist()), (
        f"SPEC §5 forbids interpolation: {grid_lon} is not one of the grid longitudes "
        f"{sorted(set(lons.ravel().tolist()))}"
    )


# --- the t2m / aptmp guard --------------------------------------------------------------


def test_decode_point_variable_guard_is_live_code() -> None:
    """Spike F9: the anchored needle's failure mode is silently decoding APTMP.

    The guard must be executable code, not a comment saying it was considered.
    """
    source = inspect.getsource(grib.decode_point)
    code = "\n".join(
        line.split("#", 1)[0] for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "aptmp" in code, (
        "spike F9: decode_point must reject 'aptmp' in live code (found only in comments, "
        "or not at all)"
    )
    assert "t2m" in code, "decode_point must assert on the 't2m' data variable in live code"
    assert 'GRIB_shortName"] == "t2m"' not in code and "GRIB_shortName') == 't2m'" not in code, (
        "Stream 1 finding: eccodes reports GRIB_shortName == '2t' for valid 2 m temperature; "
        "asserting it equals 't2m' fails on good data"
    )


# --- acceptance floor, against captured bytes (SPEC §8) ----------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("model", sorted(ACCEPTANCE))
def test_decode_point_hits_acceptance_floor(FIXTURES: Path, model: str) -> None:
    """SPEC §8 acceptance floor at ``abs(diff) < 0.01`` — SPEC §10: never widened."""
    path = grib_fixture(FIXTURES, model)
    expected = ACCEPTANCE[model]
    got = grib.decode_point(path)

    diff = got["temp_f"] - expected["temp_f"]
    assert abs(diff) < TEMP_TOLERANCE, (
        f"SPEC §8 acceptance floor: {model.upper()} 2026-08-05 12z f006 (valid 18:00Z) must "
        f"decode to {expected['temp_f']} F at KOMA; got {got['temp_f']!r} "
        f"(diff {diff:+.5f}, tolerance {TEMP_TOLERANCE}). SPEC §10: a miss means the wrong "
        f"cell or the wrong variable — do NOT widen the tolerance. Cell chosen was "
        f"({got['grid_lat']:.4f}, {got['grid_lon']:.4f}) at {got['distance_deg']:.4f} deg."
    )

    for field in ("grid_lat", "grid_lon", "distance_deg"):
        delta = got[field] - expected[field]
        assert abs(delta) < CELL_TOLERANCE, (
            f"SPEC §8 / spike F11: {model.upper()} nearest cell {field} should be "
            f"{expected[field]}, got {got[field]!r} (diff {delta:+.5f}). A different cell "
            "means the longitude normalization or the distance metric changed."
        )


@pytest.mark.integration
@pytest.mark.parametrize("model", sorted(ACCEPTANCE))
def test_decode_point_cell_is_within_half_a_degree_of_koma(FIXTURES: Path, model: str) -> None:
    """SPEC §5 sanity floor: a cell further than 0.5 deg away means the search went wrong."""
    got = grib.decode_point(grib_fixture(FIXTURES, model))
    assert got["distance_deg"] < SANITY_DEG, (
        f"SPEC §5: {model.upper()} nearest cell is {got['distance_deg']:.4f} deg from KOMA "
        f"({grib.KOMA_LAT}, {grib.KOMA_LON}), beyond the {SANITY_DEG} deg sanity floor; "
        f"cell was ({got['grid_lat']:.4f}, {got['grid_lon']:.4f})"
    )


@pytest.mark.integration
@pytest.mark.parametrize("model", sorted(ACCEPTANCE))
def test_captured_message_decodes_as_t2m_not_aptmp(FIXTURES: Path, model: str) -> None:
    """Spike F9: the anchored needle must not have selected APTMP (NBM message 1)."""
    path = grib_fixture(FIXTURES, model)
    with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as ds:
        data_vars = list(ds.data_vars)
        assert "t2m" in data_vars, (
            f"spike F9: {model.upper()} captured message must decode to the 't2m' data "
            f"variable; got {data_vars}"
        )
        assert "aptmp" not in data_vars, (
            f"spike F9: {model.upper()} captured message decoded APTMP (apparent temperature) — "
            f"the anchored needle ':TMP:2 m above ground:' failed; data_vars={data_vars}"
        )
        cf_var = ds["t2m"].attrs.get("GRIB_cfVarName")
        assert cf_var == "t2m", (
            f"spike F9: {model.upper()} GRIB_cfVarName should be 't2m', got {cf_var!r} "
            "(note GRIB_shortName is '2t' on valid data and must NOT be compared to 't2m')"
        )


@pytest.mark.integration
@pytest.mark.parametrize("model", sorted(ACCEPTANCE))
def test_decode_point_returns_the_locked_keys(FIXTURES: Path, model: str) -> None:
    got = grib.decode_point(grib_fixture(FIXTURES, model))
    assert set(got) == {"temp_f", "grid_lat", "grid_lon", "distance_deg"}, (
        "plan-locked contract: decode_point returns exactly "
        f"{{temp_f, grid_lat, grid_lon, distance_deg}}; got {sorted(got)}"
    )
    for key, value in got.items():
        assert isinstance(value, float), (
            f"decode_point['{key}'] must be a plain float (T4 writes it to parquet); "
            f"got {type(value).__name__} {value!r}"
        )


@pytest.mark.integration
@pytest.mark.parametrize("model", sorted(ACCEPTANCE))
def test_decode_point_leaves_no_cfgrib_sidecar(FIXTURES: Path, model: str) -> None:
    """`backend_kwargs={"indexpath": ""}` is mandatory — a sidecar goes stale and gets committed."""
    grib_dir = FIXTURES / "grib"
    before = {p.name for p in grib_dir.iterdir()}
    grib.decode_point(grib_fixture(FIXTURES, model))
    after = {p.name for p in grib_dir.iterdir()}
    assert after == before, (
        "cfgrib wrote a sidecar index into tests/fixtures/grib/ — decode_point must pass "
        f'backend_kwargs={{"indexpath": ""}}. New files: {sorted(after - before)}'
    )


# --- ArchiveMissing (T4 Task 1.1, D3) ----------------------------------------------------
#
# A 404/403 from the NOAA archive is an EXPECTED result (SPEC §11 R2), not the SPEC §9
# hard stop the original code reported. T4's backfill counts it into the coverage
# denominator and carries on; every other non-200 status is still a hard stop.


class _StubResponse:
    """Minimal stand-in for `requests.Response` — status and body only, no socket."""

    def __init__(self, status_code: int, text: str = "", content: bytes = b"") -> None:
        self.status_code = status_code
        self.text = text
        self.content = content


def _stub_get(responses: list, calls: list | None = None):
    """Return a `_get` replacement that hands back `responses` in order."""

    queue = list(responses)

    def _fake_get(url: str, headers: dict | None = None):
        if calls is not None:
            calls.append((url, headers))
        return queue.pop(0)

    return _fake_get


def test_archive_missing_subclasses_runtime_error() -> None:
    """Additive by construction: every pre-existing `except RuntimeError` still catches it."""
    assert issubclass(grib.ArchiveMissing, RuntimeError), (
        "ArchiveMissing must subclass RuntimeError so T2's 81 tests and every existing "
        "caller keep working — the D3 change is additive, not a contract break"
    )


@pytest.mark.parametrize("status", [404, 403])
def test_idx_404_and_403_raise_archive_missing(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """SPEC §11 R2: a missing `.idx` is an archive hole, not a hard stop."""
    monkeypatch.setattr(grib, "_get", _stub_get([_StubResponse(status)]))
    with pytest.raises(grib.ArchiveMissing) as excinfo:
        grib.fetch_point("hrrr", INIT_2026_08_05_12Z, 6)
    message = str(excinfo.value)
    assert "§11 R2" in message, f"the 404/403 message must cite SPEC §11 R2; got {message!r}"
    assert "§9" not in message, (
        "a 404/403 must NOT be reported as a SPEC §9 hard stop — that is exactly the "
        f"conflation T4 Task 1.1 exists to fix; got {message!r}"
    )


@pytest.mark.parametrize("status", [404, 403])
def test_ranged_get_404_and_403_raise_archive_missing(
    monkeypatch: pytest.MonkeyPatch, FIXTURES: Path, status: int
) -> None:
    """The object can be missing even when its `.idx` is present — same rule applies."""
    idx_text = (FIXTURES / "idx" / "hrrr_20260805_12z_f006.idx").read_text()
    monkeypatch.setattr(
        grib, "_get", _stub_get([_StubResponse(200, text=idx_text), _StubResponse(status)])
    )
    with pytest.raises(grib.ArchiveMissing) as excinfo:
        grib.fetch_point("hrrr", INIT_2026_08_05_12Z, 6)
    assert "§11 R2" in str(excinfo.value)


@pytest.mark.parametrize("status", [500, 503, 302])
def test_other_idx_statuses_remain_a_hard_stop(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """A 500 is NOT an archive hole. It must stay a plain RuntimeError citing SPEC §9."""
    monkeypatch.setattr(grib, "_get", _stub_get([_StubResponse(status)]))
    with pytest.raises(RuntimeError) as excinfo:
        grib.fetch_point("hrrr", INIT_2026_08_05_12Z, 6)
    assert not isinstance(excinfo.value, grib.ArchiveMissing), (
        f"HTTP {status} was classified as a missing archive entry; only 404/403 may be. "
        "Misclassifying a server error as 'missing' silently deflates the coverage "
        "numerator and fakes a clean run (SPEC §10)."
    )
    assert "§9" in str(excinfo.value)


@pytest.mark.parametrize("status", [500, 416])
def test_other_ranged_get_statuses_remain_a_hard_stop(
    monkeypatch: pytest.MonkeyPatch, FIXTURES: Path, status: int
) -> None:
    idx_text = (FIXTURES / "idx" / "hrrr_20260805_12z_f006.idx").read_text()
    monkeypatch.setattr(
        grib, "_get", _stub_get([_StubResponse(200, text=idx_text), _StubResponse(status)])
    )
    with pytest.raises(RuntimeError) as excinfo:
        grib.fetch_point("hrrr", INIT_2026_08_05_12Z, 6)
    assert not isinstance(excinfo.value, grib.ArchiveMissing)
    assert "§9" in str(excinfo.value)
