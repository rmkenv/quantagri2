"""
QuantAgri v2 — Z-Score Normalizer
===================================
NEW SCRIPT (no equivalent in v1).

Reads Sentinel-2 NDVI/LSWI composites from data/ndvi/ and MODIS baselines
from data/baseline/, then produces z-scored velocity and LSWI anomalies
for each composite within the phenological gate window.

Also applies:
  - Yield trend detrending (linear, per-region) before correlation
  - Dual-axis quadrant classification
  - Leave-one-out cross-validation (LOOCV) for yield correlation

Writes: data/signals/{commodity}_{region}_{year}_zscore.json

Usage:
    python scripts/compute_zscore.py --years 2016 2017 2018 2019 2020 2021 2022 2023 2024
    python scripts/compute_zscore.py  # current year only
"""

import argparse
import json
import math
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import NODES, BASELINE_DIR, NDVI_DIR, SIG_DIR, PHENO_GATES


# ── Helpers ───────────────────────────────────────────────────────────
def load_baseline(commodity: str, region: str) -> dict | None:
    path = BASELINE_DIR / f"{commodity}_{region}_baseline.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_ndvi(commodity: str, region: str, year: int) -> dict | None:
    """Find the NDVI file for a given commodity/region/year."""
    # Try year-specific filename first (historical backfill format)
    candidates = sorted(NDVI_DIR.glob(f"{commodity}_{region}_{year}-*.json"))
    if not candidates:
        # Fall back to latest daily file for current year
        candidates = sorted(NDVI_DIR.glob(f"{commodity}_{region}_*.json"))
    if not candidates:
        return None
    data = json.loads(candidates[-1].read_text())
    # Filter to composites that belong to requested year
    data["composites"] = [c for c in data.get("composites", [])
                          if str(c.get("date", ""))[:4] == str(year)
                          or c.get("month") is not None]  # simulated has no date
    return data


def nearest_baseline_bin(doy: int, doy_bins: list[dict]) -> dict | None:
    """Return the baseline bin whose doy_bin is closest to doy."""
    if not doy_bins:
        return None
    return min(doy_bins, key=lambda b: min(
        abs(doy - b["doy_bin"]),
        abs(doy - b["doy_bin"] + 365),
        abs(doy - b["doy_bin"] - 365),
    ))


def zscore(value: float, mean: float, std: float) -> float | None:
    if std < 1e-6:
        return None
    return round((value - mean) / std, 3)


def quadrant(vel_z: float | None, lswi_z: float | None) -> str:
    """
    Dual-axis quadrant from z-scores (not raw values).
    I:  +vel, +lswi  — acceleration, adequate moisture
    II: +vel, -lswi  — acceleration under moisture stress
    III:-vel, +lswi  — deceleration, heat/nutrient (not drought)
    IV: -vel, -lswi  — co-decline: drought collapse (highest signal)
    """
    if vel_z is None or lswi_z is None:
        return "?"
    if vel_z >= 0 and lswi_z >= 0:   return "I"
    if vel_z >= 0 and lswi_z < 0:    return "II"
    if vel_z < 0  and lswi_z >= 0:   return "III"
    return "IV"


def detrend(years: list[int], values: list[float]) -> list[float]:
    """
    Remove linear year trend from a yield or signal series.
    Returns residuals (anomalies around the trend line).
    """
    if len(years) < 3:
        return values
    x = np.array(years, dtype=float)
    y = np.array(values, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    trend = slope * x + intercept
    return list(y - trend)


def pearson_loocv(x: list[float], y: list[float]) -> dict:
    """
    Pearson r (in-sample) + LOOCV MAE for small-n robustness.
    Returns dict with r, p, loocv_mae, loocv_rmse.
    """
    n = len(x)
    if n < 4:
        return {"r": None, "p": None, "loocv_mae": None, "loocv_rmse": None, "n": n}

    # In-sample Pearson
    mx, my = np.mean(x), np.mean(y)
    num  = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx   = math.sqrt(sum((a - mx)**2 for a in x))
    sy   = math.sqrt(sum((b - my)**2 for b in y))
    r    = num / (sx * sy + 1e-12)
    t    = r * math.sqrt(n - 2) / math.sqrt(1 - r**2 + 1e-12)
    from scipy.stats import t as tdist
    p    = float(2 * tdist.sf(abs(t), df=n - 2))

    # LOOCV: leave one out, fit linear model on remaining n-1, predict held-out
    errors = []
    for i in range(n):
        x_train = [x[j] for j in range(n) if j != i]
        y_train = [y[j] for j in range(n) if j != i]
        if len(set(x_train)) < 2:
            continue
        slope_cv, intercept_cv = np.polyfit(x_train, y_train, 1)
        pred  = slope_cv * x[i] + intercept_cv
        errors.append(abs(pred - y[i]))

    loocv_mae  = round(float(np.mean(errors)), 3) if errors else None
    loocv_rmse = round(float(np.sqrt(np.mean([e**2 for e in errors]))), 3) if errors else None

    return {
        "r":          round(r, 4),
        "p":          round(p, 4),
        "n":          n,
        "loocv_mae":  loocv_mae,
        "loocv_rmse": loocv_rmse,
    }


# ── Main per-node processor ───────────────────────────────────────────
def process_node(node: dict, year: int) -> dict | None:
    commodity = node["commodity"]
    region    = node["region"]
    gate      = PHENO_GATES.get(commodity, {"months": [6, 7]})
    gate_months = gate["months"]

    ndvi_data = load_ndvi(commodity, region, year)
    if ndvi_data is None:
        return None

    baseline  = load_baseline(commodity, region)
    doy_bins  = baseline["doy_bins"] if baseline else []

    composites_out = []
    for comp in ndvi_data.get("composites", []):
        month = comp.get("month") or int(comp.get("date", "2000-01-01")[5:7])
        if month not in gate_months:
            continue

        # DOY: use stored value or approximate from date
        if "doy" in comp:
            doy = comp["doy"]
        else:
            try:
                doy = int(datetime.strptime(comp["date"], "%Y-%m-%d").strftime("%j"))
            except Exception:
                doy = (month - 1) * 30 + 15

        vel  = comp.get("velocity")
        lswi = comp.get("lswi")
        ndvi = comp.get("ndvi")

        # Z-scores against MODIS baseline
        bin_  = nearest_baseline_bin(doy, doy_bins) if doy_bins else None
        vel_z  = zscore(vel,  bin_["vel_mean"],  bin_["vel_std"])   if (bin_ and vel  is not None) else None
        # Use lswi_mean/lswi_std if available (self-baseline), else fall back to ndvi stats
        if bin_ and lswi is not None:
            lswi_mean = bin_.get("lswi_mean", bin_.get("ndvi_mean", 0.0))
            lswi_std  = bin_.get("lswi_std",  bin_.get("ndvi_std",  0.05))
            lswi_z    = zscore(lswi, lswi_mean, lswi_std)
        else:
            lswi_z = None

        composites_out.append({
            "date":   comp.get("date", f"{year}-{month:02d}-01"),
            "month":  month,
            "doy":    doy,
            "ndvi":   ndvi,
            "lswi":   lswi,
            "velocity":      vel,
            "vel_zscore":    vel_z,
            "lswi_zscore":   lswi_z,
            "quadrant":      quadrant(vel_z, lswi_z),
            "baseline_doy":  bin_["doy_bin"] if bin_ else None,
        })

    if not composites_out:
        return None

    # Season-level aggregates (for correlation analysis)
    vel_zscores  = [c["vel_zscore"]  for c in composites_out if c["vel_zscore"]  is not None]
    lswi_zscores = [c["lswi_zscore"] for c in composites_out if c["lswi_zscore"] is not None]
    quads        = [c["quadrant"]    for c in composites_out]
    dominant_q   = max(set(quads), key=quads.count) if quads else "?"

    return {
        "commodity":      commodity,
        "region":         region,
        "year":           year,
        "gate_months":    gate_months,
        "composites":     composites_out,
        "season_vel_z_mean":  round(float(np.mean(vel_zscores)),  3) if vel_zscores  else None,
        "season_vel_z_max":   round(float(np.max(vel_zscores)),   3) if vel_zscores  else None,
        "season_vel_z_min":   round(float(np.min(vel_zscores)),   3) if vel_zscores  else None,
        "season_lswi_z_mean": round(float(np.mean(lswi_zscores)), 3) if lswi_zscores else None,
        "dominant_quadrant":  dominant_q,
        "baseline_source":    baseline.get("doy_bins", [{}])[0].get("source", "none") if baseline else "none",
    }


def run(years: list[int]):
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n[ZSCORE v2] {date_str} — {len(NODES)} nodes × {len(years)} years\n")

    all_records = []  # flat list for correlation analysis

    for year in years:
        for node in NODES:
            result = process_node(node, year)
            if result is None:
                print(f"  [SKIP] {node['commodity']}/{node['region']} {year}")
                continue

            # Write individual z-score file
            key     = f"{node['commodity']}_{node['region']}_{year}"
            outpath = SIG_DIR / f"{key}_zscore.json"
            outpath.write_text(json.dumps(result, indent=2))
            print(f"  [OUT ] {key}_zscore.json  quad={result['dominant_quadrant']}  "
                  f"vel_z={result['season_vel_z_mean']}")
            all_records.append(result)

    print(f"\n[ZSCORE v2] {len(all_records)} season-records written\n")
    return all_records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int,
                        default=[datetime.now(timezone.utc).year])
    args = parser.parse_args()
    run(args.years)
