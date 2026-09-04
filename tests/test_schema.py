"""T4 Stream 1 tests — pinned parquet schemas and the anti-fake write guard.

Two failure modes are pinned here, and both of them are silent in production:

* **A tz mismatch.** T5 joins with `merge_asof`; a naive timestamp on either side
  raises at 06:00 or matches nothing. The round-trip test proves
  `timestamp[us, tz=UTC]` survives pandas → parquet → pandas unchanged.
* **An empty parquet.** It passes a schema check perfectly and scores perfectly —
  the T4 analogue of SPEC §10's empty-join fake.

SPEC §13: offline only.
"""

import socket
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fetch.schema import FORECAST_SCHEMA, OBS_SCHEMA, write_parquet_checked

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC §13: no test in this module may open a socket."""

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "SPEC §13 violation: tests/test_schema.py tried to open a network socket."
        )

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def forecast_frame(n: int = 3) -> pd.DataFrame:
    inits = pd.to_datetime(
        [datetime(2026, 8, 5, 12, tzinfo=UTC)] * n, utc=True
    )
    return pd.DataFrame(
        {
            "model": ["hrrr", "gfs", "nam"][:n],
            "init_time": inits,
            "lead_h": pd.array([6] * n, dtype="int32"),
            "valid_time": pd.to_datetime([datetime(2026, 8, 5, 18, tzinfo=UTC)] * n, utc=True),
            "temp_f": [68.24, 71.65, 69.53][:n],
        }
    )


def obs_frame(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "valid_time": pd.to_datetime(
                ["2026-08-05 17:53", "2026-08-05 18:05", "2026-08-05 18:53"][:n], utc=True
            ),
            "temp_f": [67.1, 68.0, 69.8][:n],
        }
    )


# --- schema declarations -----------------------------------------------------------------


def test_forecast_schema_matches_spec_6_exactly() -> None:
    assert FORECAST_SCHEMA.names == ["model", "init_time", "lead_h", "valid_time", "temp_f"]
    assert FORECAST_SCHEMA.field("model").type == pa.string(), (
        "model must be pa.string(), never a dictionary/categorical type — a pandas "
        "Categorical round-trips as a pyarrow dictionary and surprises T5"
    )
    assert FORECAST_SCHEMA.field("lead_h").type == pa.int32()
    assert FORECAST_SCHEMA.field("temp_f").type == pa.float64()
    for column in ("init_time", "valid_time"):
        assert FORECAST_SCHEMA.field(column).type == pa.timestamp("us", tz="UTC")


def test_obs_schema_matches_spec_6_exactly() -> None:
    assert OBS_SCHEMA.names == ["valid_time", "temp_f"]
    assert OBS_SCHEMA.field("valid_time").type == pa.timestamp("us", tz="UTC")
    assert OBS_SCHEMA.field("temp_f").type == pa.float64()


# --- round trip --------------------------------------------------------------------------


def test_forecast_round_trip_preserves_schema_order_and_utc(tmp_path: Path) -> None:
    """The test that stops T5's merge_asof breaking at 06:00 on a tz mismatch."""
    path = tmp_path / "forecasts.parquet"
    write_parquet_checked(forecast_frame(), path, FORECAST_SCHEMA, min_rows=1, label="forecasts")

    table = pq.read_table(path)
    assert table.schema.remove_metadata() == FORECAST_SCHEMA, (
        f"re-read schema drifted from the declared one:\n{table.schema}"
    )
    for column in ("init_time", "valid_time"):
        assert table.schema.field(column).type.tz == "UTC"

    back = table.to_pandas()
    assert list(back.columns) == FORECAST_SCHEMA.names
    assert str(back["init_time"].dt.tz) == "UTC"
    assert str(back["valid_time"].dt.tz) == "UTC"
    assert back["lead_h"].dtype == "int32"
    assert back["temp_f"].dtype == "float64"
    assert back["model"].tolist() == ["hrrr", "gfs", "nam"]


def test_obs_round_trip_preserves_schema_and_off_hour_minutes(tmp_path: Path) -> None:
    path = tmp_path / "obs.parquet"
    write_parquet_checked(obs_frame(), path, OBS_SCHEMA, min_rows=1, label="obs")

    table = pq.read_table(path)
    assert table.schema.remove_metadata() == OBS_SCHEMA
    back = table.to_pandas()
    assert str(back["valid_time"].dt.tz) == "UTC"
    minutes = set(back["valid_time"].dt.minute)
    assert minutes != {0}, (
        "off-hour minutes were lost in the round trip — spike F5: an on-the-hour join "
        "matches ZERO rows and scores perfectly"
    )


def test_model_column_is_not_written_as_a_dictionary(tmp_path: Path) -> None:
    """Even a pandas Categorical input must land as plain UTF-8 in the file."""
    df = forecast_frame()
    df["model"] = pd.Categorical(df["model"])
    path = tmp_path / "forecasts.parquet"
    write_parquet_checked(df, path, FORECAST_SCHEMA, min_rows=1, label="forecasts")
    assert pq.read_table(path).schema.field("model").type == pa.string()


# --- the guards --------------------------------------------------------------------------


def test_empty_frame_raises_and_writes_nothing(tmp_path: Path) -> None:
    """SPEC §10: an empty parquet passes a schema check perfectly. Refuse to write it."""
    path = tmp_path / "forecasts.parquet"
    empty = forecast_frame().iloc[0:0]
    with pytest.raises(AssertionError) as excinfo:
        write_parquet_checked(empty, path, FORECAST_SCHEMA, min_rows=1, label="forecasts")
    assert "§10" in str(excinfo.value)
    assert not path.exists(), "no file may be written when the row guard fires"


def test_below_min_rows_raises_naming_the_actual_count(tmp_path: Path) -> None:
    with pytest.raises(AssertionError) as excinfo:
        write_parquet_checked(
            obs_frame(3), tmp_path / "obs.parquet", OBS_SCHEMA, min_rows=700, label="obs"
        )
    message = str(excinfo.value)
    assert "3 rows" in message and "700" in message, message


def test_naive_timestamps_raise(tmp_path: Path) -> None:
    df = obs_frame()
    df["valid_time"] = df["valid_time"].dt.tz_localize(None)
    with pytest.raises(AssertionError) as excinfo:
        write_parquet_checked(df, tmp_path / "obs.parquet", OBS_SCHEMA, min_rows=1, label="obs")
    assert "UTC" in str(excinfo.value)


def test_reordered_columns_raise(tmp_path: Path) -> None:
    df = forecast_frame()[["init_time", "model", "lead_h", "valid_time", "temp_f"]]
    with pytest.raises(AssertionError) as excinfo:
        write_parquet_checked(
            df, tmp_path / "forecasts.parquet", FORECAST_SCHEMA, min_rows=1, label="forecasts"
        )
    assert "§6" in str(excinfo.value)


def test_missing_column_raises(tmp_path: Path) -> None:
    df = forecast_frame().drop(columns=["temp_f"])
    with pytest.raises(AssertionError):
        write_parquet_checked(
            df, tmp_path / "forecasts.parquet", FORECAST_SCHEMA, min_rows=1, label="forecasts"
        )


def test_write_creates_the_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "obs.parquet"
    written = write_parquet_checked(obs_frame(), path, OBS_SCHEMA, min_rows=1, label="obs")
    assert written == path and path.exists()
