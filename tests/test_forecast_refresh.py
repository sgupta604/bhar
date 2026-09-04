"""F3 Stream 5 — `forecast/refresh.py`, the one CLI that writes `data/forecast.json`.

Every test in this file is offline and **every write lands under `tmp_path`**. The
repository's own `data/` directory is only ever *read*: `data/live/2026090412/` is copied
into `tmp_path` before a run touches it, and `data/results.json` is opened read-only.

The zero-network proof is F2's, repeated here because it is the one that cannot be argued
with: the injected fetcher raises `NetworkTouched`, which is deliberately **not** a
`RuntimeError` and therefore cannot be mistaken for the `ArchiveMissing` that
`forecast.live.fetch_one` absorbs. If a run still succeeds, every value came off the disk
cache and no socket was opened. A run that consults the archive fails the test loudly
instead of quietly passing with real data.

The other load-bearing tests are the two that prove *nothing is written on failure*:

* `test_an_invalid_document_leaves_the_existing_file_untouched` puts real bytes at the
  target, makes the build produce a document that violates the §9 contract, and requires the
  old bytes to survive byte-for-byte with no temp file left behind.
* `test_a_broken_results_json_writes_nothing_at_all` requires the target **not to exist**
  after a run with no usable backtest output. There is no default vector, no equal-weight
  substitute and no stale-file reuse anywhere on this path (FORECAST-SPEC §16 R3), and a
  test that only checked the exit code would not notice one being added.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fetch.grib import ArchiveMissing
from forecast import make_fixture, refresh
from forecast.contract import load_and_validate_forecast

REPO = Path(__file__).resolve().parent.parent
REAL_CACHE = REPO / "data" / "live" / "2026090412"
REAL_RESULTS = REPO / "data" / "results.json"

#: Frozen. 18:00Z less the FORECAST-SPEC §5.2 four-hour setback floors onto the 12z cycle,
#: which is the init the captured cache holds. It is also after the cache's `fetched_at`
#: (17:30Z) and after `results.json`'s `generated_at` (12:53Z), so neither the §9 ordering
#: rule nor the non-negative weight age is violated by the choice of instant.
NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)

#: Bytes parked at the target so a refused write has something to fail to overwrite.
PRE_EXISTING = '{"this": "was already here"}\n'


class NetworkTouched(Exception):
    """Raised by the injected fetcher. **Not** a `RuntimeError`, on purpose.

    `ArchiveMissing` subclasses `RuntimeError` and `forecast.live.fetch_one` absorbs it into
    a cached `missing` record. An injected fetcher raising a plain `RuntimeError` could
    therefore be confused for an ordinary archive hole by a future reader; this one cannot be
    absorbed by anything and always propagates.
    """


class CountingFetcher:
    """A fetcher that records every call it receives and then refuses to make it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime, int]] = []

    def __call__(self, model: str, init: datetime, lead: int) -> dict:
        self.calls.append((model, init, lead))
        raise NetworkTouched(
            f"SPEC §13 forbids live-network tests, but {model} f{lead:03d} for "
            f"{init.isoformat()} was asked of the archive"
        )


def archive_is_empty(model: str, init: datetime, lead: int) -> dict:
    """Every key is absent — the condition that walks the whole §5.2 ladder off its end."""
    raise ArchiveMissing(f"404 for {model} f{lead:03d} at {init.isoformat()}")


# --------------------------------------------------------------------------- fixtures


@pytest.fixture()
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze the one wall-clock reading. Nothing else in F3 reads a clock at all."""
    monkeypatch.setattr(refresh, "now_utc", lambda: NOW)
    return NOW


@pytest.fixture()
def counting_fetcher(monkeypatch: pytest.MonkeyPatch) -> CountingFetcher:
    """Inject a fetcher that cannot fetch. A cache miss becomes a loud failure."""
    fetcher = CountingFetcher()
    monkeypatch.setattr(refresh, "FETCHER", fetcher)
    return fetcher


@pytest.fixture()
def populated_cache(tmp_path: Path) -> Path:
    """A **copy** of the real 12z cache under `tmp_path`. The original is never written."""
    if not REAL_CACHE.is_dir():
        pytest.skip(
            f"the real live cache {REAL_CACHE} is absent, so the zero-network run cannot be "
            "exercised against real data here; skipped rather than silently passed"
        )
    root = tmp_path / "live"
    shutil.copytree(REAL_CACHE, root / REAL_CACHE.name)
    return root


@pytest.fixture()
def real_results() -> Path:
    """The backtest output, read-only. Skips with a reason rather than passing vacuously."""
    if not REAL_RESULTS.is_file():
        pytest.skip(
            f"{REAL_RESULTS} is absent; run `uv run --no-sync python -m score.run` first. "
            "Skipped rather than silently passed"
        )
    return REAL_RESULTS


@pytest.fixture()
def out_path(tmp_path: Path) -> Path:
    """The target every run in this file writes to. Under `tmp_path`, never under `data/`."""
    return tmp_path / "served" / "forecast.json"


# --------------------------------------------------------------------------- the real path


@pytest.mark.usefixtures("real_results")
def test_a_cached_run_writes_a_document_that_revalidates(
    out_path: Path,
    populated_cache: Path,
    frozen_now: datetime,
    counting_fetcher: CountingFetcher,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The success case: exit 0, the bytes on disk pass the §9 contract, no temp file left."""
    code = refresh.main(
        ["--cache-root", str(populated_cache), "--out", str(out_path)]
    )

    captured = capsys.readouterr().out
    assert code == 0, f"refresh failed:\n{captured}"
    assert out_path.is_file(), f"nothing was written to {out_path}"

    scratch = refresh.temp_path_for(out_path)
    assert not scratch.exists(), f"the temp file {scratch} survived a successful write"

    document = load_and_validate_forecast(out_path)  # re-reads and re-validates the BYTES
    assert document["meta"]["is_synthetic"] is False
    assert document["meta"]["cycle"]["init_time"] == "2026-09-04T12:00:00Z"
    assert document["forecast"], "a document with no rows is not a forecast"


@pytest.mark.usefixtures("real_results")
def test_the_cached_run_consults_no_network_at_all(
    out_path: Path,
    populated_cache: Path,
    frozen_now: datetime,
    counting_fetcher: CountingFetcher,
) -> None:
    """FR8's zero-network re-run, at the CLI level: the fetcher is never even called."""
    code = refresh.main(["--cache-root", str(populated_cache), "--out", str(out_path)])

    assert code == 0
    assert counting_fetcher.calls == [], (
        f"the archive was consulted {len(counting_fetcher.calls)} time(s) despite a fully "
        f"populated cache; first was {counting_fetcher.calls[:1]}"
    )


@pytest.mark.usefixtures("real_results")
def test_the_banner_records_the_facts_of_the_run(
    out_path: Path,
    populated_cache: Path,
    frozen_now: datetime,
    counting_fetcher: CountingFetcher,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An operator must be able to read what was served without opening the JSON."""
    code = refresh.main(["--cache-root", str(populated_cache), "--out", str(out_path)])
    printed = capsys.readouterr().out

    assert code == 0
    document = json.loads(out_path.read_text(encoding="utf-8"))
    meta = document["meta"]

    for fragment in (
        str(out_path),
        meta["cycle"]["init_time"],
        f"cycle={meta['cycle']['run_label']}",
        f"rows={len(document['forecast'])}",
        f"gaps={len(document['gaps'])}",
        f"horizon_h={meta['horizon_h']}",
        f"step_h={meta['step_h']}",
        f"is_stale={meta['cycle']['is_stale']}",
        f"weights_age_days={meta['weights_source']['weights_age_days']}",
    ):
        assert fragment in printed, f"the banner never names {fragment!r}:\n{printed}"


# --------------------------------------------------------------------------- atomicity


@pytest.mark.parametrize(
    "target",
    ["data/forecast.json", "forecast.json", "a/deeply/nested/served.json"],
)
def test_the_temp_file_is_a_sibling_of_the_target(tmp_path: Path, target: str) -> None:
    """`os.replace` is atomic only within one filesystem, so the scratch file must be beside
    the target — never in `/tmp`, where the rename would silently become a copy."""
    full = tmp_path / target
    scratch = refresh.temp_path_for(full)

    assert scratch.parent == full.parent
    assert scratch != full
    assert scratch.name.startswith(".")


# --------------------------------------------------------------------------- refused writes


def test_an_invalid_document_leaves_the_existing_file_untouched(
    out_path: Path,
    frozen_now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A contract violation must cost the previously served file nothing.

    The builder is replaced with one that returns a document whose `meta.is_synthetic` is the
    string `"true"` rather than the boolean — a violation the §9 validator names by path.
    `write_atomic` validates before it opens anything, so neither the target nor the temp
    file may change.
    """
    genuine = make_fixture.build_fixture_document

    def broken(generated_at: datetime, init_time: datetime) -> dict:
        document = genuine(generated_at=generated_at, init_time=init_time)
        document["meta"]["is_synthetic"] = "true"
        return document

    monkeypatch.setattr(make_fixture, "build_fixture_document", broken)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(PRE_EXISTING, encoding="utf-8")

    code = refresh.main(["--fixture", "--out", str(out_path)])
    printed = capsys.readouterr().out

    assert code != 0, f"a contract violation exited 0:\n{printed}"
    assert out_path.read_text(encoding="utf-8") == PRE_EXISTING, (
        "the previously served document was overwritten by a document that failed validation"
    )
    assert not refresh.temp_path_for(out_path).exists(), "a temp file survived a refused write"
    assert "REFUSING TO WRITE" in printed, printed
    assert str(out_path) in printed, f"the refusal never names the output path:\n{printed}"
    assert "meta.is_synthetic" in printed, (
        f"the refusal never names the failing JSON path:\n{printed}"
    )
    assert "Traceback" not in printed, f"an expected failure printed a traceback:\n{printed}"


# --------------------------------------------------------------------------- no weights


def _absent(tmp_path: Path) -> Path:
    return tmp_path / "nowhere" / "results.json"


def _not_json(tmp_path: Path) -> Path:
    target = tmp_path / "broken" / "results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{ this is not json", encoding="utf-8")
    return target


def _fails_the_contract(tmp_path: Path) -> Path:
    target = tmp_path / "wrong" / "results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"meta": {}, "results": {}}) + "\n", encoding="utf-8")
    return target


def _unreadable(tmp_path: Path) -> Path:
    """A directory where a file belongs: every read of it raises `IsADirectoryError`."""
    target = tmp_path / "directory" / "results.json"
    target.mkdir(parents=True)
    return target


@pytest.mark.parametrize(
    "make_results",
    [_absent, _not_json, _fails_the_contract, _unreadable],
    ids=["absent", "not-json", "contract-violation", "unreadable"],
)
def test_a_broken_results_json_writes_nothing_at_all(
    tmp_path: Path,
    out_path: Path,
    frozen_now: datetime,
    counting_fetcher: CountingFetcher,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make_results,
) -> None:
    """FORECAST-SPEC §16 R3: no backtest output, no document. No fallback lives on this path.

    The exit code alone would not catch a default vector being added later, so the assertion
    that matters is that **the target does not exist** afterwards.
    """
    results = make_results(tmp_path)
    monkeypatch.setattr(refresh, "RESULTS_PATH", results)
    cache_root = tmp_path / "live"

    code = refresh.main(["--cache-root", str(cache_root), "--out", str(out_path)])
    printed = capsys.readouterr().out

    assert code != 0, f"an unusable results.json exited 0:\n{printed}"
    assert not out_path.exists(), (
        f"{out_path} was written despite there being no fitted weights — a fallback vector "
        "has appeared on this path"
    )
    assert not refresh.temp_path_for(out_path).exists()
    assert str(results) in printed, f"the failure never names the missing path:\n{printed}"
    assert "python -m score.run" in printed, (
        f"the failure never names what produces results.json:\n{printed}"
    )
    assert "Traceback" not in printed, f"an expected failure printed a traceback:\n{printed}"
    assert counting_fetcher.calls == [], (
        "the archive was consulted before the weights were known to be unusable"
    )
    assert not cache_root.exists(), f"{cache_root} was created by a run that produced nothing"


# --------------------------------------------------------------------------- no cycle


@pytest.mark.usefixtures("real_results")
def test_no_cycle_available_reports_the_reason_and_writes_nothing(
    tmp_path: Path,
    out_path: Path,
    frozen_now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every candidate in the §5.2 ladder is absent: say so, write nothing, do not traceback."""
    monkeypatch.setattr(refresh, "FETCHER", archive_is_empty)

    code = refresh.main(
        ["--cache-root", str(tmp_path / "live"), "--out", str(out_path)]
    )
    printed = capsys.readouterr().out

    assert code != 0, f"an unavailable cycle exited 0:\n{printed}"
    assert not out_path.exists(), f"{out_path} was written with no published cycle behind it"
    assert not refresh.temp_path_for(out_path).exists()
    assert "not published" in printed, f"the failure never gives a reason:\n{printed}"
    assert "Traceback" not in printed, f"an expected failure printed a traceback:\n{printed}"


# --------------------------------------------------------------------------- the fixture path


def test_fixture_run_needs_no_results_json_no_cache_and_no_network(
    tmp_path: Path,
    out_path: Path,
    frozen_now: datetime,
    counting_fetcher: CountingFetcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--fixture` is the offline escape hatch, so all three of its inputs are taken away.

    `results.json` becomes a directory (reading it raises), the cache root points at a path
    that does not exist, and the fetcher raises on any call. The document still lands.
    """
    hostile_results = tmp_path / "results.json"
    hostile_results.mkdir()
    monkeypatch.setattr(refresh, "RESULTS_PATH", hostile_results)
    cache_root = tmp_path / "does-not-exist"

    code = refresh.main(
        ["--fixture", "--cache-root", str(cache_root), "--out", str(out_path)]
    )

    assert code == 0
    assert not cache_root.exists(), "the fixture path touched the cache"
    assert counting_fetcher.calls == [], "the fixture path consulted the archive"
    assert not refresh.temp_path_for(out_path).exists()

    document = load_and_validate_forecast(out_path)
    assert document["meta"]["is_synthetic"] is True
    assert document["meta"]["source"] == "synthetic_fixture"
    assert document["gaps"], "the fixture must declare a gap so F5 can render that treatment"
    assert any(row["is_extrapolated_lead"] for row in document["forecast"]), (
        "the fixture must carry an extrapolated row, the other never-exercised branch"
    )


# --------------------------------------------------------------------------- the flag surface


def test_there_is_no_init_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """A regression test against re-adding the cycle-hunting flag.

    Choosing a different init until the numbers look better is the tuning FORECAST-SPEC §15
    bans, and F2 declined the same flag for the same reason. `--init` must stay unrecognised.
    """
    with pytest.raises(SystemExit) as excinfo:
        refresh.main(["--init", "2026-09-04T12:00:00Z"])

    assert excinfo.value.code != 0
    assert "unrecognized arguments" in capsys.readouterr().err


def test_the_flag_surface_is_exactly_the_three_declared_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--fixture`, `--cache-root`, `--out`, and nothing else that steers the result."""
    with pytest.raises(SystemExit):
        refresh.main(["--help"])
    printed = capsys.readouterr().out

    for expected in ("--fixture", "--cache-root", "--out"):
        assert expected in printed, f"{expected} is missing from the CLI:\n{printed}"
    for banned in ("--init", "--refetch-missing", "--workers", "--now"):
        assert banned not in printed, (
            f"{banned} has appeared on the refresh CLI; the flag surface is deliberately "
            f"three flags wide:\n{printed}"
        )


def test_the_default_output_is_the_gitignored_served_payload() -> None:
    """The default target is `data/forecast.json`, which F2 already added to `.gitignore`."""
    assert refresh.DEFAULT_OUTPUT == REPO / "data" / "forecast.json"
    assert refresh.RESULTS_PATH == REPO / "data" / "results.json"

    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "data/forecast.json" in ignored, (
        "data/forecast.json is regenerated on every refresh and must never be committed"
    )


def test_refresh_supersedes_the_live_harness_and_adds_no_third_cli() -> None:
    """The docstring is the contract with the next reader; the module list is the proof."""
    assert "supersede" in (refresh.__doc__ or "").lower()
    assert "forecast/live.py" in (refresh.__doc__ or "")

    entry_points = sorted(
        path.name
        for path in (REPO / "forecast").glob("*.py")
        if "__main__" in path.read_text(encoding="utf-8")
    )
    assert entry_points == ["live.py", "make_fixture.py", "refresh.py"], (
        f"a fourth CLI surface has appeared under forecast/: {entry_points}"
    )
