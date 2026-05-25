"""
QuantAgri v2 — Yield Correlation & LOOCV Analysis
===================================================
NEW SCRIPT (no equivalent in v1).

Reads z-score signal files + an official yield CSV, runs:
  1. Pearson r (in-sample) per region
  2. Pooled cross-region correlation (z-scored signals enable pooling)
  3. LOOCV MAE/RMSE per region
  4. Yield trend detrending before correlation
  5. Writes data/signals/correlation_summary.json

Usage:
    python scripts/correlation_analysis.py --yields path/to/yields.csv --years 2016 2017 ... 2024
    
Yield CSV format:
    commodity,region_id,year,official_yield
    corn,illinois_us,2016,197.0
    ...
"""

import argparse
import csv
import json
import math
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import SIG_DIR
from compute_zscore import detrend, pearson_loocv


def load_yields(yield_csv: str) -> dict:
    """Load official yields into {(commodity, region_id, year): yield} dict."""
    yields = {}
    with open(yield_csv) as f:
        for row in csv.DictReader(f):
            y = float(row["official_yield"])
            if y > 0:
                # Normalise region_id: lowercase, spaces→underscore
                reg = row["region_id"].lower().replace(" ", "_")
                comm = row["commodity"].lower()
                yields[(comm, reg, int(row["year"]))] = y
    return yields


def load_zscore_records(years: list[int]) -> list[dict]:
    """Load all z-score JSON files for the given years."""
    records = []
    for year in years:
        for path in SIG_DIR.glob(f"*_{year}_zscore.json"):
            records.append(json.loads(path.read_text()))
    return records


def region_key(commodity: str, region: str) -> str:
    """Normalise to match yield CSV format."""
    return region.lower().replace(" ", "_")


def run(yield_csv: str, years: list[int]):
    yields  = load_yields(yield_csv)
    records = load_zscore_records(years)

    if not records:
        print("[ERROR] No z-score records found. Run compute_zscore.py first.")
        return

    print(f"\n[CORRELATION] {len(records)} z-score records, {len(yields)} yield entries\n")

    # ── Match records to official yields ─────────────────────────────
    matched = []
    for rec in records:
        comm = rec["commodity"].lower()
        reg  = region_key(rec["commodity"], rec["region"])
        yr   = rec["year"]
        off  = yields.get((comm, reg, yr))
        if off is None:
            continue
        matched.append({**rec, "official_yield": off})

    print(f"  Matched {len(matched)} season-records to official yields\n")

    # ── Per region/commodity group ────────────────────────────────────
    groups = defaultdict(list)
    for m in matched:
        groups[(m["commodity"], m["region"])].append(m)

    summary_rows = []
    for (comm, reg), recs in sorted(groups.items()):
        recs = sorted(recs, key=lambda r: r["year"])
        years_g  = [r["year"]           for r in recs]
        yields_g = [r["official_yield"] for r in recs]
        vel_z_g  = [r["season_vel_z_mean"]  for r in recs]
        lswi_z_g = [r["season_lswi_z_mean"] for r in recs]

        # Detrend yields
        yields_dt = detrend(years_g, yields_g)
        # Detrend signals (remove any secular trend in satellite record)
        vel_z_dt  = detrend(years_g, [v if v is not None else 0.0 for v in vel_z_g])
        lswi_z_dt = detrend(years_g, [v if v is not None else 0.0 for v in lswi_z_g])

        # Raw correlations
        raw_vel  = pearson_loocv(
            [v for v in vel_z_g  if v is not None],
            [yields_g[i] for i, v in enumerate(vel_z_g) if v is not None]
        )
        raw_lswi = pearson_loocv(
            [v for v in lswi_z_g if v is not None],
            [yields_g[i] for i, v in enumerate(lswi_z_g) if v is not None]
        )

        # Detrended correlations
        dt_vel  = pearson_loocv(vel_z_dt,  yields_dt)
        dt_lswi = pearson_loocv(lswi_z_dt, yields_dt)

        row = {
            "commodity": comm, "region": reg, "n": len(recs),
            "years": years_g,
            "vel_z_raw":    raw_vel,
            "lswi_z_raw":   raw_lswi,
            "vel_z_detrend":  dt_vel,
            "lswi_z_detrend": dt_lswi,
            "dominant_quads": [r["dominant_quadrant"] for r in recs],
            "year_records": [
                {"year": r["year"], "vel_z": r["season_vel_z_mean"],
                 "lswi_z": r["season_lswi_z_mean"], "quad": r["dominant_quadrant"],
                 "official_yield": r["official_yield"]}
                for r in recs
            ],
        }
        summary_rows.append(row)

        sig_v = "**" if (raw_vel["p"] or 1) < 0.05 else "*" if (raw_vel["p"] or 1) < 0.10 else ""
        sig_l = "**" if (raw_lswi["p"] or 1) < 0.05 else "*" if (raw_lswi["p"] or 1) < 0.10 else ""
        print(f"  {comm}/{reg} (n={len(recs)})")
        print(f"    vel_z  → yield: r={raw_vel['r']:+.3f}  p={raw_vel['p']:.3f}{sig_v}  "
              f"LOOCV MAE={raw_vel['loocv_mae']}  | detrended r={dt_vel['r']:+.3f}")
        print(f"    lswi_z → yield: r={raw_lswi['r']:+.3f}  p={raw_lswi['p']:.3f}{sig_l}  "
              f"LOOCV MAE={raw_lswi['loocv_mae']}  | detrended r={dt_lswi['r']:+.3f}")

    # ── Pooled cross-region (z-scores allow pooling) ──────────────────
    print("\n  --- POOLED (all regions, detrended) ---")
    all_vel_z   = []
    all_lswi_z  = []
    all_yields_dt = []

    for (comm, reg), recs in groups.items():
        recs = sorted(recs, key=lambda r: r["year"])
        yrs  = [r["year"] for r in recs]
        ys   = [r["official_yield"] for r in recs]
        vs   = [r["season_vel_z_mean"]  or 0.0 for r in recs]
        ls   = [r["season_lswi_z_mean"] or 0.0 for r in recs]
        ys_dt = detrend(yrs, ys)
        vs_dt = detrend(yrs, vs)
        ls_dt = detrend(yrs, ls)
        all_vel_z.extend(vs_dt)
        all_lswi_z.extend(ls_dt)
        all_yields_dt.extend(ys_dt)

    pool_vel  = pearson_loocv(all_vel_z,  all_yields_dt)
    pool_lswi = pearson_loocv(all_lswi_z, all_yields_dt)
    print(f"  vel_z  pooled: r={pool_vel['r']:+.3f}  p={pool_vel['p']:.3f}  "
          f"n={pool_vel['n']}  LOOCV MAE={pool_vel['loocv_mae']}")
    print(f"  lswi_z pooled: r={pool_lswi['r']:+.3f}  p={pool_lswi['p']:.3f}  "
          f"n={pool_lswi['n']}  LOOCV MAE={pool_lswi['loocv_mae']}")

    # ── Write summary ─────────────────────────────────────────────────
    out = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
        "n_records": len(matched),
        "pooled_vel_z_detrended":  pool_vel,
        "pooled_lswi_z_detrended": pool_lswi,
        "by_region": summary_rows,
    }
    outpath = SIG_DIR / "correlation_summary.json"
    outpath.write_text(json.dumps(out, indent=2))
    print(f"\n[CORRELATION] Written → {outpath}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yields", required=True,
                        help="Path to official yields CSV")
    parser.add_argument("--years", nargs="+", type=int,
                        default=list(range(2016, 2025)))
    args = parser.parse_args()
    run(args.yields, args.years)
