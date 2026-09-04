"""Shared pytest fixtures for the Bhar test suite.

Path fixtures only. No network, no application logic, no imports of
fetch/score/backend — those belong in the tests themselves.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def REPO_ROOT() -> Path:
    """Absolute path to the repository root.

    Derived from this file's location, never from the current working
    directory, so tests behave the same however pytest is invoked.
    """
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def FIXTURES(REPO_ROOT: Path) -> Path:
    """Absolute path to `tests/fixtures/` — see its README for provenance rules."""
    return REPO_ROOT / "tests" / "fixtures"
