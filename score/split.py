"""SPEC §5 — the chronological train/test split (D1).

Weights are fitted on the first 20 days and evaluated on the last 10.  The out-of-sample
number is the headline; the in-sample number sits beside it, labelled.  A random split
would leak tomorrow's weather into today's fit and make every number optimistic.

The boundary rule, and why it is **not** day-normalised
------------------------------------------------------
``boundary = (first paired valid_time for that lead) + 20 days``, ``train`` is
``valid_time < boundary`` and ``test`` is ``valid_time >= boundary``.

A ``.normalize()``d midnight boundary was tried during research and **rejected**: it
gives 78/42, 77/43 and 79/41 across the three leads.  The rule above gives exactly
**80/40 at every lead**, matching SPEC §7's own worked example.  This note is here so
that nobody later "fixes" the missing ``.normalize()`` and quietly changes every number
on the page.

The split is on **``valid_time``**, never ``init_time`` — the paired sample is keyed on
valid time — and it is computed **per lead, independently**, because the weights are
optimised per lead (FR8).
"""

from __future__ import annotations

import pandas as pd

__all__ = ["TRAIN_DAYS", "TEST_DAYS", "split_boundary", "chronological_split"]

#: SPEC §5: fit on days 1-20, evaluate on days 21-30.
TRAIN_DAYS = 20
TEST_DAYS = 10


def split_boundary(frame: pd.DataFrame, train_days: int = TRAIN_DAYS) -> pd.Timestamp:
    """First paired ``valid_time`` plus ``train_days``. Deliberately not normalised (D1)."""
    if frame.empty:
        raise ValueError("split_boundary: empty frame; there is nothing to split")
    first = frame["valid_time"].min()
    if pd.isna(first):
        raise ValueError("split_boundary: the first valid_time is NaT")
    return first + pd.Timedelta(days=train_days)


def chronological_split(
    frame: pd.DataFrame, train_days: int = TRAIN_DAYS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split one lead's paired frame into ``(train, test)`` at the D1 boundary.

    ``train`` is strictly before the boundary; ``test`` is on or after it
    (inclusive-left).  Raises if either side is empty — a zero-length split would score
    perfectly on nothing.
    """
    if "valid_time" not in frame.columns:
        raise ValueError(
            f"chronological_split: frame is missing 'valid_time'; got {list(frame.columns)}"
        )
    boundary = split_boundary(frame, train_days)
    train = frame.loc[frame["valid_time"] < boundary].copy()
    test = frame.loc[frame["valid_time"] >= boundary].copy()
    if train.empty or test.empty:
        raise RuntimeError(
            f"chronological_split: boundary {boundary.isoformat()} leaves "
            f"{len(train)} train and {len(test)} rows; both sides must be non-empty. The "
            "window is fixed by SPEC §3 and must not be changed to produce a usable split"
        )
    return train.reset_index(drop=True), test.reset_index(drop=True)
