"""CLI entry point: ``uv run python -m score.run`` — the only I/O in ``score/``.

Reads ``data/forecasts.parquet``, ``data/obs.parquet`` and ``data/coverage.json``; joins,
pairs, splits, scores and searches the weight simplex; then writes ``data/results.json``.

Two safety properties, both mirroring GREEN code elsewhere in the repo:

* **Validate before writing.**  ``backend.contract.validate_results`` runs on the finished
  document *before* a single byte reaches disk — the same discipline as
  ``fetch/schema.py::write_parquet_checked``.  A contract violation must never reach the
  demo path.  ``backend.contract`` is imported read-only; ``backend.make_fixture`` is
  never imported here or anywhere else in ``score/`` (it writes *both* results files and
  would clobber a real result with fake data).
* **Atomic write.**  Temp file then ``os.replace``, so a crash mid-write cannot leave
  truncated JSON where the 16:00 demo will read it.  If everything else fails,
  ``cp data/results.synthetic.json data/results.json`` restores the insurance fixture.

The printed diagnostics block is not decoration.  A join that matched nothing scores
perfectly, so the match rate, the mean offset and the sample sizes are read out loud
every run — and shipped in the document (SPEC §10: diagnostics are displayed, not buried).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

from backend.contract import validate_results
from score.build import build_document
from score.join import join_forecasts_to_obs

__all__ = ["main"]

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
FORECASTS_PATH = DATA_DIR / "forecasts.parquet"
OBS_PATH = DATA_DIR / "obs.parquet"
COVERAGE_PATH = DATA_DIR / "coverage.json"
RESULTS_PATH = DATA_DIR / "results.json"
TMP_PATH = DATA_DIR / ".results.json.tmp"


def _require(path: Path, produced_by: str) -> Path:
    """A fresh clone has no parquet data (gitignored). Say so, do not traceback."""
    if not path.exists():
        raise SystemExit(
            f"missing input {path}\n"
            f"  It is produced by: {produced_by}\n"
            "  The data files are gitignored, so a fresh clone has none. Run the backfill "
            "first; score/run.py never touches the network itself (SPEC §6)."
        )
    return path


def write_atomic(document: dict, path: Path = RESULTS_PATH, tmp: Path = TMP_PATH) -> None:
    """Validate, then write via temp file + ``os.replace``. Nothing is written on failure."""
    validate_results(document)  # belt and braces: build_document already validated
    payload = json.dumps(document, indent=2, sort_keys=False) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    forecasts = pd.read_parquet(
        _require(FORECASTS_PATH, "uv run python -m fetch.backfill (T4)")
    )
    obs = pd.read_parquet(_require(OBS_PATH, "uv run python -m fetch.backfill (T4)"))
    coverage = json.loads(
        _require(COVERAGE_PATH, "uv run python -m fetch.backfill (T4)").read_text("utf-8")
    )

    print(f"forecasts: {len(forecasts)} rows   obs: {len(obs)} rows")
    matched, stats = join_forecasts_to_obs(forecasts, obs)
    print(f"matched:   {len(matched)} rows (SPEC §4 join, nearest within ±30 min)\n")

    print("join by (model, lead):")
    for _, row in stats.sort_values(["lead_h", "model"]).iterrows():
        print(
            f"  {row['model']:>4} {int(row['lead_h']):>3}h  "
            f"{int(row['n_matched']):>4}/{int(row['n_forecast']):<4} = "
            f"{row['matched_pct']:6.2f}%   mean |offset| {row['mean_abs_offset_min']:5.2f} min"
        )

    document, diagnostics = build_document(matched, stats, coverage)
    meta = document["meta"]
    print(
        f"\nmodels included: {meta['models_included']}   "
        f"excluded: {[e['model'] for e in meta['models_excluded']] or 'none'}"
    )
    print(f"window: {meta['window']['start']} .. {meta['window']['end']}  (UTC)\n")

    for diag in diagnostics:
        lead = diag["lead_h"]
        block = document["results"][str(lead)]
        print(f"--- lead {lead}h " + "-" * 52)
        print(
            f"  paired valid times {diag['n_paired_valid_times']} "
            f"(dropped to pairing: {diag['n_dropped_to_pairing']})   "
            f"train/test {block['n_samples']['train']}/{block['n_samples']['test']}"
        )
        print(
            f"  matched {block['join_diagnostics']['matched_pct']:.2f}%   "
            f"mean |offset| {block['join_diagnostics']['mean_abs_offset_min']:.2f} min   "
            f"max |offset| {diag['max_abs_offset_min']:.2f} min"
        )
        print("  per-model TEST-SPLIT (out-of-sample) metrics:")
        for entry in block["models"]:
            print(
                f"    {entry['model']:>4}  MAE {entry['mae']:7.4f}  "
                f"RMSE {entry['rmse']:7.4f}  bias {entry['bias']:+8.4f}  "
                f"coverage {entry['coverage_pct']:.2f}%"
            )
        best = block["best_single_model"]
        winner = block["winner"]
        print(
            f"  best single model (lowest OOS corner): {best['model']} "
            f"MAE {best['mae_out_of_sample']:.4f}"
        )
        print(
            f"  winner (in-sample argmin, reported OOS): {winner['label']!r} "
            f"MAE {winner['mae_out_of_sample']:.4f}  "
            f"improvement {winner['improvement_pct_vs_best_single']:+.4f}%  "
            f"(OOS leaderboard rank {diag['winner_oos_rank']} of {len(block['blends'])})"
        )

    write_atomic(document)
    print(f"\nwrote {RESULTS_PATH} (validated against backend/contract.py before writing)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
