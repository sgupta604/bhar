"""D1 chronological split tests: 80/40, inclusive-left, and no empty side."""

from __future__ import annotations

import pandas as pd
import pytest

from score.split import TRAIN_DAYS, chronological_split, split_boundary

START = pd.Timestamp("2026-08-04T12:00:00Z")


def _series(n: int = 120, step_h: int = 6) -> pd.DataFrame:
    """A 6-hourly series of ``n`` valid times — 120 points is exactly 30 days."""
    times = pd.to_datetime(
        [START + pd.Timedelta(hours=step_h * k) for k in range(n)], utc=True
    ).as_unit("us")
    return pd.DataFrame({"valid_time": times, "temp_f": [70.0 + k % 7 for k in range(n)]})


def test_120_six_hourly_points_split_exactly_80_40():
    """SPEC §7's own worked example. A normalised boundary gives 78/42 — rejected in D1."""
    train, test = chronological_split(_series())
    assert len(train) == 80
    assert len(test) == 40


def test_boundary_is_first_valid_time_plus_20_days_and_is_not_normalised():
    boundary = split_boundary(_series())
    assert boundary == START + pd.Timedelta(days=TRAIN_DAYS)
    assert boundary == pd.Timestamp("2026-08-24T12:00:00Z")
    assert boundary != boundary.normalize()  # the rejected day-normalised variant


def test_boundary_is_inclusive_left_a_row_exactly_on_it_is_test():
    frame = _series()
    boundary = split_boundary(frame)
    train, test = chronological_split(frame)
    assert train["valid_time"].max() < boundary
    assert test["valid_time"].min() == boundary
    assert boundary in set(test["valid_time"])
    assert boundary not in set(train["valid_time"])


def test_split_is_a_partition_no_row_is_lost_or_duplicated():
    frame = _series()
    train, test = chronological_split(frame)
    assert len(train) + len(test) == len(frame)
    assert set(train["valid_time"]).isdisjoint(set(test["valid_time"]))


def test_split_uses_valid_time_not_init_time():
    """init_time is deliberately shuffled; the split must ignore it entirely."""
    frame = _series()
    frame["init_time"] = list(reversed(frame["valid_time"].tolist()))
    train, test = chronological_split(frame)
    assert len(train) == 80 and len(test) == 40


def test_an_empty_test_side_raises_rather_than_scoring_nothing():
    short = _series(n=10)  # 60 hours; everything lands before the +20 day boundary
    with pytest.raises(RuntimeError, match="both sides must be non-empty"):
        chronological_split(short)


def test_an_empty_frame_raises():
    with pytest.raises(ValueError, match="nothing to split"):
        chronological_split(_series(n=0))
