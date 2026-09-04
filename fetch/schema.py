"""Pinned parquet schemas and the anti-fake write guard (T4, Stream 1).

Two jobs, both of them about stopping a silent failure downstream:

1. **Pin the dtypes.** T5 joins forecasts to observations with `merge_asof`, which
   raises — or worse, matches nothing — on a timezone mismatch. The schemas here are
   declared explicitly (`timestamp[us, tz=UTC]`), never inferred from a dataframe, so
   the tz can't drift between the two files.

2. **Refuse to write a beautifully-typed file of nothing.** *An empty parquet passes a
   schema check perfectly.* It is the T4 analogue of SPEC §10's empty-join fake: an
   empty join scores flawlessly and is entirely fictional. `write_parquet_checked`
   asserts a non-trivial row count *before* writing, so the failure surfaces here at
   the write rather than as a suspiciously perfect number on the demo page.

Guard messages carry the SPEC clause in the text, matching `fetch/grib.py`'s house style.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# --- schemas (SPEC §6 column order, exactly) ---------------------------------------------

# SPEC §6: `forecasts.parquet`: model, init_time, lead_h, valid_time, temp_f
# `model` is pa.string() and NEVER a dictionary/categorical type — a pandas Categorical
# round-trips through parquet as a pyarrow dictionary and surprises T5.
FORECAST_SCHEMA = pa.schema(
    [
        ("model", pa.string()),
        ("init_time", pa.timestamp("us", tz="UTC")),
        ("lead_h", pa.int32()),
        ("valid_time", pa.timestamp("us", tz="UTC")),
        ("temp_f", pa.float64()),
    ]
)

# SPEC §6: `obs.parquet`: valid_time, temp_f
OBS_SCHEMA = pa.schema(
    [
        ("valid_time", pa.timestamp("us", tz="UTC")),
        ("temp_f", pa.float64()),
    ]
)

_TIMESTAMP_COLUMNS = ("init_time", "valid_time")


def _timestamp_fields(schema: pa.Schema) -> list[str]:
    return [name for name in schema.names if name in _TIMESTAMP_COLUMNS]


def write_parquet_checked(
    df: pd.DataFrame,
    path: str | Path,
    schema: pa.Schema,
    *,
    min_rows: int,
    label: str,
) -> Path:
    """Write `df` to `path` under `schema`, refusing to write a trivial or mistyped frame.

    Raises `AssertionError` (SPEC §13: data guards are assertions in the pipeline) if:

    * fewer than `min_rows` rows — **SPEC §10**, the empty-parquet fake;
    * the column names or their order differ from `schema`;
    * a timestamp column is timezone-naive (T5's `merge_asof` breaks on a tz mismatch).

    Returns the path written.
    """
    out = Path(path)

    if len(df) < min_rows:
        raise AssertionError(
            f"SPEC §10: refusing to write {label} to {out} with {len(df)} rows "
            f"(minimum {min_rows}). An empty parquet passes a schema check perfectly and "
            "scores perfectly downstream — that is the whole failure mode this guard "
            "exists to catch. Report the shortfall; do not lower the minimum."
        )

    expected = list(schema.names)
    actual = list(df.columns)
    if actual != expected:
        raise AssertionError(
            f"SPEC §6: {label} columns must be exactly {expected} in that order; "
            f"got {actual}. T5 reads these by position and name."
        )

    for column in _timestamp_fields(schema):
        series = df[column]
        tz = getattr(getattr(series, "dt", None), "tz", None)
        if tz is None:
            raise AssertionError(
                f"SPEC §2 (UTC everywhere): {label}.{column} is timezone-naive "
                f"(dtype={series.dtype}). T5's merge_asof raises or silently matches "
                "nothing across a tz mismatch — pin it to UTC before writing."
            )

    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out)
    return out
