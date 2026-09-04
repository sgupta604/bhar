"""Scaffold regression tests — SPEC §8 T1's acceptance floor, made permanent.

These four tests carry no marker: they are the default always-run set, and they
must stay green for every later ticket.
"""

import sys
from pathlib import Path


def test_python_is_312() -> None:
    """The venv is pinned to 3.12 (`.python-version`, `requires-python`)."""
    assert sys.version_info[:2] == (3, 12), (
        f"expected Python 3.12, got {sys.version_info.major}.{sys.version_info.minor} "
        f"from {sys.executable}; the venv is pinned via .python-version and uv.lock"
    )


def test_grib_stack_imports() -> None:
    """T1's acceptance floor (SPEC §8) as a permanent regression test of spike F12.

    F12 verified the environment is provisioned and the GRIB stack imports. This
    keeps that verified, so a broken eccodes/cfgrib install fails here loudly
    rather than deep inside T2's decoder.
    """
    try:
        import cfgrib
        import fastapi
        import pandas
        import pyarrow
        import xarray
    except ImportError as exc:
        raise AssertionError(
            f"GRIB/API stack failed to import: {exc}. SPEC §8 T1 acceptance floor requires "
            "`import cfgrib, xarray, pandas, pyarrow, fastapi` to succeed in the venv"
        ) from exc

    for name, mod in (
        ("cfgrib", cfgrib),
        ("xarray", xarray),
        ("pandas", pandas),
        ("pyarrow", pyarrow),
        ("fastapi", fastapi),
    ):
        assert mod is not None, f"{name} imported as None"


def test_repo_packages_importable() -> None:
    """`pythonpath = ["."]` in pyproject makes the repo packages importable from tests."""
    try:
        import backend
        import fetch
        import score
    except ImportError as exc:
        raise AssertionError(
            f"repo package failed to import: {exc}. This means pytest's "
            '`pythonpath = ["."]` setting is not taking effect'
        ) from exc

    for name, mod in (("fetch", fetch), ("score", score), ("backend", backend)):
        assert mod is not None, f"{name} imported as None"


def test_layout_exists(REPO_ROOT: Path) -> None:
    """The directories later tickets write into are present and are directories."""
    for relative in ("data", "frontend", "tests/fixtures"):
        path = REPO_ROOT / relative
        assert path.exists(), f"expected {relative}/ to exist at {path}"
        assert path.is_dir(), f"expected {relative}/ to be a directory, but {path} is a file"
