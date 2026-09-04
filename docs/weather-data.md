# Weather / Wind Data Handoff

Standalone guide for pulling forecast wind from the three providers Boreas uses. Written to be
copied into another project and read cold; nothing below depends on Boreas code being present.
Every fact was taken from the Boreas adapters, tests, config and ADRs (footer lists where).

## 1. Overview

Three providers, all queried at a **single point** for a **single valid hour**, all returning
10 m AGL wind plus wind at five pressure levels (850/700/500/300/250 hPa) and 2 m temperature:

| Provider | Model / resolution | Coverage | Protocol | Auth | Licensing |
|---|---|---|---|---|---|
| **Folkweather** | NCEP HRRR, 3 km, hourly | CONUS only | OGC EDR (CoverageJSON) | none | no known restriction or quota |
| **Open-Meteo** | NCEP HRRR CONUS, 3 km, hourly | CONUS only | plain JSON GET | none | **FREE TIER IS NON-COMMERCIAL ONLY.** 10,000 calls/day, 5,000/hour, 600/minute. Attribution required: "Weather data by Open-Meteo.com, CC BY 4.0". Commercial use needs a paid plan. |
| **Shyft** (legacy OGC EDR) | GFS, 25 km, 3-hourly | global | OGC EDR (CoverageJSON) | `apikey` query param | commercial key |

Say it again because it is the one that bites at launch: **Open-Meteo's free tier may not be used
in a commercial product, even as a fallback.** Being second in a chain is still commercial use once
the product is live. Boreas' ruling was to keep it and buy a licence before launch.

Live state as of 2026-08-15 (verified against the real services, not inferred): Folkweather and
Open-Meteo both serve real data. **Shyft's legacy EDR serves no 10 m wind at all** — see § 2.1.

## 2. Providers

All three adapters use the same HTTP timeouts and do **no retries**:
`connect=10s, read=30s, write=10s, pool=10s`. A timeout is reported as status 408; an HTTP error as
its status; any other transport error as status 0. A failed provider falls through to the next one.

### 2.1 Shyft (OGC EDR, GFS 25 km)

- **Base URL:** `https://ogc.shyftwx.com/ogc/edr/collections`
- **Auth:** `&apikey=<key>` query parameter. Env var `SHYFT_API_KEY`. Keys look like `owp_...`.
  Redact the `&apikey=` segment before logging any URL.
- **Three GETs per hour** (surface, isobaric, temperature), all `/{collection}/position`:

| Purpose | Collection | `parameter-name` |
|---|---|---|
| 10 m wind | `GFS_height-above-ground_10` | `u-component-of-wind,v-component-of-wind` |
| Pressure-level wind | `GFS_isobaric` | `u-component-of-wind,v-component-of-wind` |
| 2 m temperature | `GFS_height-above-ground` | `temperature` |

```bash
# Surface 10 m wind. Longitude is SIGNED (-180..180). datetime is %Y-%m-%dT%H:%M:%SZ.
curl -sG "https://ogc.shyftwx.com/ogc/edr/collections/GFS_height-above-ground_10/position" \
  --data-urlencode "coords=POINT(-122.25 37.75)" \
  --data-urlencode "parameter-name=u-component-of-wind,v-component-of-wind" \
  --data-urlencode "datetime=2026-03-15T15:00:00Z" \
  --data-urlencode "apikey=$SHYFT_API_KEY"
```

- **Response shape:** a `CoverageCollection` with **one Coverage per parameter** (and, for the
  isobaric request, one per parameter per level). Flatten by merging every `coverages[i].ranges`
  into one dict and taking `domain` from `coverages[0]`. For isobaric, group by
  `domain.axes.z.values[0]` and sort levels descending (850 first).

```json
{"type": "CoverageCollection", "coverages": [
  {"type": "Coverage",
   "domain": {"axes": {"x": {"values": [-122.25]}, "y": {"values": [37.75]},
                       "z": {"values": [10]}, "t": {"values": ["2026-03-15T15:00:00Z"]}}},
   "ranges": {"u-component-of-wind": {"type": "NdArray", "values": [-2.3]}}},
  {"type": "Coverage", "domain": {"...same..."},
   "ranges": {"v-component-of-wind": {"type": "NdArray", "values": [1.8]}}}]}
```

- **Units:** u/v in m/s (used as-is); `temperature` in **Kelvin** → `temp_c = K - 273.15`.
  Valid time is `domain.axes.t.values[0]`; longitude is signed already.
- **Gotchas, verbatim from the code:**
  - `NEVER request 1000 hPa from GFS_isobaric (causes Internal Server Error)`. Use the surface
    (height-above-ground) collection for near-surface wind instead. Levels used: 850,700,500,300,250.
  - `Area queries MUST use f=CoverageJSON_MultiPointSeries` (plain `f=CoverageJSON` → HTTP 400).
    Note: Boreas never sends a bbox or `within`; it only toggles this format flag on a point query.
  - The adapter does **not** send a `z=` parameter; it relies on the collection's default levels.
  - The temperature GET's failure is logged, not raised, but the normalizer **requires** the
    temperature payload, so a missing one drops Shyft for that hour rather than inventing 20 °C.
- **Live verification 2026-08-15 contradicts three of the above — treat them as unverified today:**
  `GFS_height-above-ground_10` and `GFS_height-above-ground` both **404**; across all 51 live
  collections there is **no 10 m AGL wind** (only `GFS_isobaric` and `GFS_single-level`), so the
  legacy EDR currently serves no surface wind. 1000 hPa now returns 200, and the MultiPointSeries
  flag is no longer required. **Do not substitute `GFS_single-level` PBL-mean wind for 10 m wind.**
  Shyft also has a second, newer REST API ("Storm Glass", `api.dev.wxchange.io`, Bearer JWT or
  `sg_live_...` key, models `gfs`/`hrrr`/`mrms`) that Boreas does not use; an `owp_` key does not
  open it.

### 2.2 Folkweather (OGC EDR, HRRR 3 km, CONUS)

- **Base URL:** `https://folkweather.com/edr/collections`. Env var `FOLKWEATHER_BASE_URL`.
- **Auth:** none.
- **Longitude is 0–360.** Convert before building the URL: `lon_folk = lon + 360 if lon < 0 else lon`
  (`-122.25 → 237.75`, `-0.5 → 359.5`). The response echoes 0–360 in `domain.axes.x`; convert back
  with `lon - 360 if lon > 180`.
- **Reject points outside CONUS locally before any HTTP call** (bbox in § 3). Measured live: an
  out-of-domain point returns **HTTP 200 with all-null values** — the worst possible shape, since a
  null coerced to 0 renders as calm wind.
- **Three GETs per hour** — one collection document (cached), then two data requests:

| Purpose | Collection | `parameter-name` |
|---|---|---|
| Horizon check | `hrrr-height-agl` (the collection document itself, no `/position`) | — |
| 10 m wind + 2 m temp + RH | `hrrr-height-agl/position` | `UGRD,VGRD,TMP,RH` |
| Pressure-level wind | `hrrr-isobaric/position` | `UGRD,VGRD` |

```bash
# 1. Collection document -> which hours the provider actually has
curl -s "https://folkweather.com/edr/collections/hrrr-height-agl" | jq .extent.temporal

# 2. Surface (note 0-360 longitude in POINT)
curl -sG "https://folkweather.com/edr/collections/hrrr-height-agl/position" \
  --data-urlencode "coords=POINT(237.75 37.75)" \
  --data-urlencode "parameter-name=UGRD,VGRD,TMP,RH" \
  --data-urlencode "datetime=2026-03-15T15:00:00Z"

# 3. Isobaric (ALWAYS hrrr-isobaric; gfs-isobaric-latest lacks 850 hPa)
curl -sG "https://folkweather.com/edr/collections/hrrr-isobaric/position" \
  --data-urlencode "coords=POINT(237.75 37.75)" \
  --data-urlencode "parameter-name=UGRD,VGRD" \
  --data-urlencode "datetime=2026-03-15T15:00:00Z"
```

- **Response shape:** a flat `Coverage` (not a collection). Isobaric has a multi-valued `z` axis
  with parallel value arrays.

```json
{"type": "Coverage",
 "domain": {"axes": {"x": {"values": [237.75]}, "y": {"values": [37.75]},
                     "t": {"values": ["2026-03-15T15:00:00Z"]}}},
 "parameters": {"UGRD": {"unit": {"symbol": "m/s"}}, "TMP": {"unit": {"symbol": "K"}},
                "RH": {"unit": {"symbol": "%"}}},
 "ranges": {"UGRD": {"values": [-2.1]}, "VGRD": {"values": [1.6]},
            "TMP": {"values": [292.15]}, "RH": {"values": [60.53]}}}
```

Live sample 2026-08-05: `UGRD -2.283682 m/s, VGRD 0.34099704 m/s, TMP 295.5839 K, RH 60.533985 %`.

- **Units:** UGRD/VGRD m/s; TMP **Kelvin** → subtract 273.15; RH percent 0–100. **Verify
  `parameters.RH.unit.symbol == "%"`** and refuse otherwise — a 0–1 fraction looks plausible.
- **Gotchas:**
  - **It answers HTTP 200 for hours it does not have**, echoing your requested `datetime` into its
    own `t` axis and re-serving its last modelled hour. Nothing in the response reveals this. The
    only truth is the collection document's `extent.temporal`. **Check membership in
    `extent.temporal.values` before every data request**; fall back to `interval` only if `values`
    is empty. Measured: `interval` spanned 51 hours while `values` listed 49 — the two missing hours
    were served as byte-identical repeats. If the document cannot be fetched, **refuse** rather than
    ask. Boreas caches the document for 10 min per process (extent moves at most hourly), serves a
    stale copy up to 1 h old if the fetch fails, backs off 1 min after a failure, and single-flights
    concurrent cold misses.
  - Even inside the declared horizon the provider repeats **individual parameters** (each field is
    nearest-neighboured from its own time grid). A series-level backstop drops a **trailing** run of
    ≥3 samples with identical `(u, v, temp_c)`; interior runs are left alone.
  - Surface and isobaric requests carry **different** parameter sets; only read what you asked for.
  - No total-cloud parameter (only `LCDC/MCDC/HCDC`); precipitation would need `hrrr-surface`.
    Boreas does not request either from Folkweather.

### 2.3 Open-Meteo (JSON, NCEP HRRR CONUS 3 km)

- **Base URL:** `https://api.open-meteo.com/v1/forecast`. Env `OPEN_METEO_BASE_URL`, `OPEN_METEO_MODEL`.
- **Auth:** none. **Non-commercial only on the free tier** (see § 1). HTTP 429 = quota hit.
- **One GET per hour** with `start_hour == end_hour`. Pass params as an encoded dict, not f-strings.

```bash
curl -sG "https://api.open-meteo.com/v1/forecast" \
  --data-urlencode "latitude=41.74" --data-urlencode "longitude=-83.34" \
  --data-urlencode "hourly=wind_speed_10m,wind_direction_10m,temperature_2m,relative_humidity_2m,precipitation,cloud_cover,wind_speed_850hPa,wind_speed_700hPa,wind_speed_500hPa,wind_speed_300hPa,wind_speed_250hPa,wind_direction_850hPa,wind_direction_700hPa,wind_direction_500hPa,wind_direction_300hPa,wind_direction_250hPa" \
  --data-urlencode "models=ncep_hrrr_conus" \
  --data-urlencode "wind_speed_unit=ms" \
  --data-urlencode "start_hour=2026-08-05T05:00" --data-urlencode "end_hour=2026-08-05T05:00"
```

- **Response shape** (live probe, Toledo OH):

```json
{"latitude": 41.72963, "longitude": -83.33927, "elevation": 170.0,
 "hourly_units": {"time": "iso8601", "wind_speed_10m": "m/s", "wind_direction_10m": "°",
                  "temperature_2m": "°C", "relative_humidity_2m": "%",
                  "precipitation": "mm", "cloud_cover": "%", "wind_speed_850hPa": "m/s"},
 "hourly": {"time": ["2026-08-05T05:00"], "wind_speed_10m": [3.0], "wind_direction_10m": [150],
            "temperature_2m": [21.4], "relative_humidity_2m": [64],
            "precipitation": [0.3], "cloud_cover": [75], "wind_speed_850hPa": [5.37], "...": []}}
```

- **Units:** wind as **speed + meteorological direction** (not u/v) — request `wind_speed_unit=ms`
  and **verify every `hourly_units.wind_speed*` is `"m/s"`** (a silent km/h switch is 3.6×).
  Also verify `relative_humidity_2m == "%"`, `precipitation == "mm"`, `cloud_cover == "%"`.
  Temperature is already °C. Convert to components: `u = -s·sin(dir)`, `v = -s·cos(dir)`.
- **Gotchas:**
  - Outside CONUS the API returns **400**; precheck the bbox locally to spend no quota.
  - **Beyond HRRR's horizon (~18–48 h) it returns HTTP 200 with every hourly value `null`.** Read
    wind first and reject the whole hour if any required value is null. Never coerce null to 0.
  - `precipitation` is mm **accumulated over the hour ending at** the timestamp, not a rate and not a
    probability. **Do not request `precipitation_probability`**: it is filled from another model and
    never nulls at the horizon, so it outlives HRRR by ~35 h while wearing HRRR's name.
  - Timestamps are naive (`"2026-08-05T05:00"`, no `Z`) and are UTC — stamp UTC explicitly.
  - `latitude`/`longitude` come back **snapped to the grid cell**; report those, not the request.
  - Changing `models=` changes provenance too. Keep a model→resolution table (`ncep_hrrr_conus → 3.0 km`
    is the only verified entry) and refuse to serve an unmapped model rather than labelling it 3 km.

## 3. Source ordering and fallback

Routing is a pure function of `(available, lat, lon, requested_pin, geographic_enabled)`. Four rungs,
first match wins:

1. **Request pin** (`?source=shyft|folkweather|open-meteo-hrrr`): exactly that one source. **Strict —
   never fall back.** If it fails or is not enabled, answer 502 naming it. A pin that silently
   substitutes another provider is a provenance lie next to the numbers.
2. **Env pin**: if `WEATHER_SOURCE_ORDER` differs from the default, use it verbatim at every
   location and disable geographic routing (log once).
3. **Geographic, inside CONUS**: `("folkweather", "open-meteo-hrrr", "shyft")` filtered to what is
   enabled, remaining sources appended. Folkweather leads Open-Meteo **for licensing reasons**, not
   quality — both are HRRR 3 km. Shyft is last because 25 km is coarsest.
4. **Geographic, outside CONUS**: `("shyft",)` only. If Shyft is not enabled, use the configured
   order with a warning — never an empty chain.

```python
CONUS_BBOX = (21.0, 53.0, -134.0, -60.0)   # (lat_min, lat_max, lon_min, lon_max), SIGNED longitude
def in_conus(lat, lon): return 21.0 <= lat <= 53.0 and -134.0 <= lon <= -60.0
```

The box is a generous superset of HRRR's Lambert-conformal footprint (it includes Cuba, most of
Mexico, southern Canada, open ocean). It is a **cheap reject, not a coverage guarantee** — do not
widen it. Test it on the signed longitude *before* Folkweather's 0–360 transform.

Chain walk: for each source in order — check cache, fetch, normalize, cache, return. Any fetch **or
normalize** failure moves to the next source. If all fail, raise one 502 aggregating every detail;
distinguish "no source covers this location" (every failure was a local bbox rejection) from "every
source was broken". **A coverage miss must render as unknown, never as calm.**

Series endpoint (72 h max, 4 concurrent fetches): a trailing block of hours every source refuses ends
the series honestly (`truncated_at` + reason); an **interior** hole is an error, not smoothed over.

## 4. Normalized internal shape

All values SI: m/s, degrees, metres, °C (mm for precipitation, deliberately). Direction is
meteorological (FROM; 0=N, 90=E): `speed = hypot(u,v)`, `dir = (270 - atan2(v,u)·180/π) mod 360`.

```json
{"meta": {"source": "folkweather-hrrr", "source_id": "folkweather", "requested_source": "auto",
          "resolution_km": 3.0, "fetched_at": "...Z", "valid_time": "2026-03-15T15:00:00Z",
          "provides": ["relative_humidity_pct", "temp_c"]},
 "surface": {"wind_u_ms": -2.1, "wind_v_ms": 1.6, "wind_speed_ms": 2.64, "wind_dir_deg": 127.3,
             "temp_c": 19.0, "relative_humidity_pct": 60.53,
             "precip_mm_hr": null, "cloud_cover_pct": null},
 "grid": {"bounds": {"north": 37.75, "south": 37.75, "east": -122.25, "west": -122.25},
          "points": [{"lat": 37.75, "lon": -122.25, "levels": [
             {"altitude": "surface_10m", "height_m": 10,    "u": -2.1, "v": 1.6},
             {"altitude": "850hPa",      "height_m": 1500,  "u": -3.8, "v": 2.9},
             {"altitude": "700hPa",      "height_m": 3000,  "u": -5.9, "v": 4.5},
             {"altitude": "500hPa",      "height_m": 5500,  "u": -8.1, "v": 5.8},
             {"altitude": "300hPa",      "height_m": 9200,  "u": 0.0,  "v": 0.0},
             {"altitude": "250hPa",      "height_m": 10400, "u": 0.0,  "v": 0.0}]}]}}
```

- Pressure-level heights are fixed approximations: 850→1500, 700→3000, 500→5500, 300→9200, 250→10400 m.
- `meta.valid_time` is **the provider's** time axis value, never the requested time, never `now()`.
  If the axis is absent, refuse.
- `provides` lists which optional scalars the provider was **asked for**; a field is in `provides`
  iff its value is non-null (invariant enforced on construction and on cache read). Capabilities:
  `shyft → temp_c`; `folkweather → temp_c, relative_humidity_pct`; `open-meteo-hrrr → all four`.
  `0.0` is a real reading (calm, dry, clear); only `null` means "not measured".
- **Two identifier namespaces — never compare across them.** *Canonical* ids
  (`shyft` / `folkweather` / `open-meteo-hrrr`) are used for config, cache keys, routing, `?source=`,
  `meta.source_id` and `meta.requested_source`; all requested-vs-served comparison is
  `requested_source == source_id`. *Display* names (`shyft-gfs` / `folkweather-hrrr` /
  `open-meteo-hrrr`) appear only in `meta.source`. Two of three differ, so comparing across
  namespaces reports a mismatch on every successful pinned request. Keep exactly one mapping.

## 5. Caching

Cache the normalized grid, not the raw response, in Redis, **TTL 3600 s** (GFS updates 6-hourly,
HRRR hourly; 1 h is safe for planning and bounds upstream traffic).

```
wind:{schema_version}:{source_id}:surface:{lat_r3}:{lon_r3}:r{radius}:{slot}
wind:v4:folkweather:surface:37.754:-122.419:r0.0:2026-03-15T15
```

- `lat_r3`/`lon_r3`: rounded to 3 decimals (~111 m). `radius` as `str(float(...))`; Boreas never
  implements an area query but keys it because Shyft's request changes on it.
- **`slot` is floored (never rounded) to the provider's own cadence** — 3 h for Shyft/GFS, 1 h for
  the HRRR sources — **and the same floored instant is what you send upstream.** Key and request must
  describe one instant; a round-to-nearest key with a `%H:%M:%S` request let one hour answer for
  its neighbours out of Redis for a full TTL.
- Bump the schema version on any change to the grid shape **or the meaning of any key segment**;
  a same-format, different-meaning key is the more dangerous case because validation cannot see it.
- Cache read failures and validation failures are treated as misses; cache write failures are logged
  and ignored. `requested_source` is stamped on the way out, after the cache read — never cached.

## 6. Minimal Python reference (Open-Meteo, `httpx` only)

Matches the Boreas adapter + normalizer: bbox precheck, `wind_speed_unit=ms`, unit verification,
one hour per GET, null rejection, speed/dir → u/v. Swap in Folkweather by following § 2.2.

```python
import math, httpx
from datetime import datetime, timedelta, timezone

BASE = "https://api.open-meteo.com/v1/forecast"
MODEL = "ncep_hrrr_conus"                       # -> 3.0 km; refuse unmapped models
LEVELS = (850, 700, 500, 300, 250)
HEIGHT_M = {850: 1500.0, 700: 3000.0, 500: 5500.0, 300: 9200.0, 250: 10400.0}
HOURLY = ["wind_speed_10m", "wind_direction_10m", "temperature_2m", "relative_humidity_2m",
          "precipitation", "cloud_cover",
          *[f"wind_speed_{p}hPa" for p in LEVELS], *[f"wind_direction_{p}hPa" for p in LEVELS]]
SCALAR_UNITS = {"relative_humidity_2m": "%", "precipitation": "mm", "cloud_cover": "%"}
TIMEOUT = httpx.Timeout(connect=10, read=30, write=10, pool=10)

def in_conus(lat, lon): return 21.0 <= lat <= 53.0 and -134.0 <= lon <= -60.0

def uv(speed, dir_deg):                          # meteorological FROM-direction -> components
    r = math.radians(dir_deg); return -speed * math.sin(r), -speed * math.cos(r)

def require(hourly, key, when):                  # absent/null must never become 0.0
    v = hourly.get(key)
    if not isinstance(v, list) or not v or v[0] is None:
        raise RuntimeError(f"no data at {when} for {key} (beyond HRRR horizon?)")
    return float(v[0])

def fetch_hour(client, lat, lon, when: datetime) -> dict:
    if not in_conus(lat, lon):
        raise RuntimeError(f"({lat}, {lon}) outside CONUS; no request made")
    hour = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")   # floor, naive-UTC form
    r = client.get(BASE, params={"latitude": str(lat), "longitude": str(lon),
                                 "hourly": ",".join(HOURLY), "models": MODEL,
                                 "wind_speed_unit": "ms", "start_hour": hour, "end_hour": hour},
                   timeout=TIMEOUT)
    r.raise_for_status()
    f = r.json(); units = f.get("hourly_units") or {}; hourly = f.get("hourly") or {}
    for k, u in units.items():
        if k.startswith("wind_speed") and u != "m/s":
            raise RuntimeError(f"unexpected unit {k}={u!r}")
    for k, want in SCALAR_UNITS.items():
        if units.get(k) != want:
            raise RuntimeError(f"unexpected/undeclared unit {k}={units.get(k)!r}")
    t = hourly["time"][0]                                             # e.g. "2026-08-05T05:00"
    valid = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
    speed = require(hourly, "wind_speed_10m", t)                      # wind FIRST: it is the horizon guard
    u, v = uv(speed, require(hourly, "wind_direction_10m", t))
    levels = [{"altitude": "surface_10m", "height_m": 10.0, "u": u, "v": v}]
    for p in LEVELS:
        lu, lv = uv(require(hourly, f"wind_speed_{p}hPa", t), require(hourly, f"wind_direction_{p}hPa", t))
        levels.append({"altitude": f"{p}hPa", "height_m": HEIGHT_M[p], "u": lu, "v": lv})
    return {
        "meta": {"source": "open-meteo-hrrr", "source_id": "open-meteo-hrrr", "resolution_km": 3.0,
                 "fetched_at": datetime.now(timezone.utc), "valid_time": valid,
                 "provides": ["cloud_cover_pct", "precip_mm_hr", "relative_humidity_pct", "temp_c"]},
        "surface": {"wind_u_ms": u, "wind_v_ms": v, "wind_speed_ms": round(speed, 2),
                    "wind_dir_deg": round((270 - math.degrees(math.atan2(v, u))) % 360, 1),
                    "temp_c": round(require(hourly, "temperature_2m", t), 2),
                    "relative_humidity_pct": round(require(hourly, "relative_humidity_2m", t), 2),
                    "precip_mm_hr": round(require(hourly, "precipitation", t), 2),
                    "cloud_cover_pct": round(require(hourly, "cloud_cover", t), 2)},
        "grid": {"bounds": {"north": f["latitude"], "south": f["latitude"],
                            "east": f["longitude"], "west": f["longitude"]},
                 "points": [{"lat": f["latitude"], "lon": f["longitude"], "levels": levels}]},
    }

def fetch_series(lat, lon, start: datetime, hours: int) -> list[dict]:
    out = []
    with httpx.Client() as client:
        for i in range(hours):                    # Boreas: max 72 h, 4 concurrent; stop at first refusal
            try: out.append(fetch_hour(client, lat, lon, start + timedelta(hours=i)))
            except RuntimeError as e: print("series ends:", e); break
    return out

if __name__ == "__main__":
    for rec in fetch_series(41.74, -83.34, datetime.now(timezone.utc), 3):
        print(rec["meta"]["valid_time"], rec["surface"]["wind_speed_ms"], "m/s", rec["surface"]["wind_dir_deg"], "deg")
```

## 7. Env var checklist

| Var | Default | Notes |
|---|---|---|
| `SHYFT_API_KEY` | `""` | Required only if Shyft is in the order. `owp_...` opens the legacy EDR, not Storm Glass. Never commit it. |
| `SHYFT_BASE_URL` | `https://ogc.shyftwx.com/ogc/edr/collections` | |
| `FOLKWEATHER_BASE_URL` | `https://folkweather.com/edr/collections` | No key. |
| `OPEN_METEO_BASE_URL` | `https://api.open-meteo.com/v1/forecast` | No key. Non-commercial free tier. |
| `OPEN_METEO_MODEL` | `ncep_hrrr_conus` | Only model with a verified resolution entry. |
| `WEATHER_SOURCE_ORDER` | `shyft,folkweather,open-meteo-hrrr` | Comma-separated **string** (not a list type — a list-typed setting JSON-decodes and crashes at import). Setting it to anything but the default disables geographic routing. Unknown names are skipped with a warning; all-unknown falls back to the default. |
| `REDIS_URL` | `redis://localhost:6379` | Optional; cache disabled if unreachable. |

## 8. Verification

```bash
# 1. Folkweather is up and declares a horizon (expect interval + ~49 hourly values)
curl -s https://folkweather.com/edr/collections/hrrr-height-agl | jq '.extent.temporal | {interval, n: (.values|length)}'

# 2. Folkweather surface data at Kansas (39.8, -98.5 -> lon 261.5), for the first declared hour
T=$(curl -s https://folkweather.com/edr/collections/hrrr-height-agl | jq -r '.extent.temporal.values[0]')
curl -sG https://folkweather.com/edr/collections/hrrr-height-agl/position \
  --data-urlencode "coords=POINT(261.5 39.8)" --data-urlencode "parameter-name=UGRD,VGRD,TMP,RH" \
  --data-urlencode "datetime=$T" | jq '{t: .domain.axes.t.values, ranges: (.ranges|map_values(.values)), rh_unit: .parameters.RH.unit.symbol}'

# 3. Open-Meteo returns m/s and non-null wind for the current hour
curl -sG https://api.open-meteo.com/v1/forecast --data-urlencode latitude=39.8 --data-urlencode longitude=-98.5 \
  --data-urlencode hourly=wind_speed_10m,wind_direction_10m --data-urlencode models=ncep_hrrr_conus \
  --data-urlencode wind_speed_unit=ms --data-urlencode "start_hour=$(date -u +%Y-%m-%dT%H:00)" \
  --data-urlencode "end_hour=$(date -u +%Y-%m-%dT%H:00)" | jq '{units: .hourly_units, hourly}'

# 4. Open-Meteo horizon behaviour: 72 h out should show nulls (200, not an error)
curl -sG https://api.open-meteo.com/v1/forecast --data-urlencode latitude=39.8 --data-urlencode longitude=-98.5 \
  --data-urlencode hourly=wind_speed_10m --data-urlencode models=ncep_hrrr_conus \
  --data-urlencode "start_hour=$(date -u -d '+72 hours' +%Y-%m-%dT%H:00)" \
  --data-urlencode "end_hour=$(date -u -d '+72 hours' +%Y-%m-%dT%H:00)" | jq .hourly

# 5. Reference implementation end to end
pip install httpx && python weather_ref.py     # expect 3 lines: valid_time, speed m/s, direction deg
```

If Shyft is configured, also `curl -s "$SHYFT_BASE_URL?apikey=$SHYFT_API_KEY" | jq '[.collections[].id]'`
and confirm whether a 10 m height-above-ground collection exists before relying on it (as of
2026-08-15 it did not).

---

**Source of truth (Boreas repo):** adapters
`packages/api/boreas_api/domain/weather/adapters/{shyft,folkweather,open_meteo}.py`; routing and bbox
`domain/weather/{routing,geo}.py` + `.claude/decisions/0006-weather-source-routing-precedence.md`;
normalization, units and the WindGrid model `domain/weather/{normalize,models,sources}.py`; horizon
and stale-tail handling `domain/weather/{horizon,series_integrity}.py`; cache key and TTL
`domain/weather/service.py`; env vars `packages/api/config.py`, `packages/api/.env.example`;
response fixtures `packages/api/tests/fixtures/*.json`, `tests/conftest.py`,
`tests/domain/test_open_meteo_adapter.py`; live-verification findings and the Open-Meteo licensing
ruling `.claude/pipeline/STATUS.md` § "Open — needs the user" items 1 and 6; API shape `docs/SPEC.md` § 3.
