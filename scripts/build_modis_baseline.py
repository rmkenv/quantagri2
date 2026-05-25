"""
QuantAgri v2 — MODIS Baseline Builder
=======================================
NEW SCRIPT (no equivalent in v1).

Pulls MOD13Q1 (250m, 16-day NDVI composites) from Planetary Computer
for 2000-2015, computes per-region per-DOY-bin velocity statistics
(mean + std), and saves as baseline/{commodity}_{region}_baseline.json.

These baselines are consumed by compute_zscore.py to convert raw
Sentinel-2 velocity values into anomaly z-scores.

Run once (or annually to refresh):
    python scripts/build_modis_baseline.py

Notes:
  - 16-year × 23 composites/year = 368 observations per DOY bin per region.
  - DOY bins are 16-day windows (matching MOD13Q1 compositing period).
  - Regions are spatially averaged over the same bbox as NODES in config.py.
  - MODIS NDVI is scale-factor 0.0001 (values stored as int16 × 0.0001).
"""

import json
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np

warnings.filterwarnings("ignore")

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    NODES, BASELINE_DIR, PC_STAC_URL,
    MODIS_COLLECTION, MODIS_BASELINE_START, MODIS_BASELINE_END,
)

try:
    import planetary_computer as pc
    import pystac_client
    import stackstac
    PC_AVAILABLE = True
except ImportError:
    PC_AVAILABLE = False
    print("[WARN] PC libs not available — generating synthetic baseline (dev mode)")


# ── DOY bin centres for MOD13Q1 (16-day composites, 23/year) ─────────
DOY_BINS = [int(datetime(2001, 1, 1).strftime("%j"))]
d = datetime(2001, 1, 1)
from datetime import timedelta
while True:
    d = d + timedelta(days=16)
    if d.year > 2001:
        break
    DOY_BINS.append(int(d.strftime("%j")))
# DOY_BINS ≈ [1, 17, 33, 49, 65, 81, 97, 113, 129, 145, 161, 177,
#              193, 209, 225, 241, 257, 273, 289, 305, 321, 337, 353]


def synthetic_baseline(node: dict) -> dict:
    """Generate a plausible baseline when MODIS/PC is unavailable."""
    commodity = node["commodity"]
    peak_doy  = {"Corn": 196, "Soybeans": 230, "Wheat": 130,
                 "Sugar": 250, "Cotton": 210}.get(commodity, 196)
    rng = np.random.default_rng(abs(hash(node["region"])) % 2**31)

    bins = []
    doys = DOY_BINS
    ndvi_curve = [
        float(np.clip(0.75 * np.exp(-0.0002 * (d - peak_doy)**2) + 0.12, 0.05, 0.90))
        for d in doys
    ]
    vel_curve = [0.0] + [
        (ndvi_curve[i+1] - ndvi_curve[i-1]) / 2.0
        for i in range(1, len(ndvi_curve) - 1)
    ] + [0.0]

    for doy, ndvi_mean, vel_mean in zip(doys, ndvi_curve, vel_curve):
        bins.append({
            "doy_bin":   doy,
            "ndvi_mean": round(ndvi_mean, 4),
            "ndvi_std":  round(float(rng.uniform(0.02, 0.06)), 4),
            "vel_mean":  round(vel_mean, 5),
            "vel_std":   round(float(rng.uniform(0.010, 0.030)), 5),
            "n_obs":     0,
            "source":    "synthetic",
        })
    return {"commodity": commodity, "region": node["region"],
            "baseline_period": f"{MODIS_BASELINE_START}/{MODIS_BASELINE_END}",
            "doy_bins": bins}


def build_modis_baseline(node: dict) -> dict:
    """Pull MODIS MOD13Q1 for 2000-2015, compute velocity stats per DOY bin."""
    if not PC_AVAILABLE:
        return synthetic_baseline(node)

    commodity = node["commodity"]
    region    = node["region"]
    bbox      = node["bbox"]
    print(f"  [MODIS] {commodity}/{region}")

    try:
        catalog = pystac_client.Client.open(PC_STAC_URL, modifier=pc.sign_inplace)
        items   = catalog.search(
            collections=[MODIS_COLLECTION],
            bbox=bbox,
            datetime=f"{MODIS_BASELINE_START}/{MODIS_BASELINE_END}",
        ).item_collection()

        if len(items) == 0:
            print(f"    [WARN] No MODIS scenes — synthetic baseline")
            return synthetic_baseline(node)

        # MODIS MOD13Q1 NDVI band name in PC STAC
        stack = stackstac.stack(
            items, assets=["250m_16_days_NDVI"],
            resolution=250, bounds_latlon=bbox,
        )

        # Scale factor: MODIS NDVI is stored × 10000
        ndvi = (stack.sel(band="250m_16_days_NDVI").astype("float32") * 0.0001
                ).clip(-0.2, 1.0)

        # Spatial mean per composite
        ndvi_ts  = ndvi.mean(dim=["x", "y"])
        ndvi_vals = [float(v) for v in ndvi_ts.values]
        times     = [str(t)[:10] for t in ndvi_ts.time.values]
        doys      = [int(datetime.strptime(t, "%Y-%m-%d").strftime("%j")) for t in times]

        # Velocity (central diff, 16-day units)
        vel_vals = [0.0] + [
            (ndvi_vals[i+1] - ndvi_vals[i-1]) / 2.0
            for i in range(1, len(ndvi_vals) - 1)
        ] + [0.0]

        # Bin by DOY (±8 days around each 16-day centre)
        from collections import defaultdict
        bin_ndvi = defaultdict(list)
        bin_vel  = defaultdict(list)

        for doy, ndvi_v, vel_v in zip(doys, ndvi_vals, vel_vals):
            # Find nearest DOY_BINS centre
            nearest = min(DOY_BINS, key=lambda b: min(abs(doy - b), abs(doy - b + 365), abs(doy - b - 365)))
            bin_ndvi[nearest].append(ndvi_v)
            bin_vel[nearest].append(vel_v)

        doy_bins_out = []
        for doy_bin in DOY_BINS:
            nv = bin_ndvi.get(doy_bin, [])
            vv = bin_vel.get(doy_bin, [])
            doy_bins_out.append({
                "doy_bin":   doy_bin,
                "ndvi_mean": round(float(np.mean(nv)) if nv else 0.0, 4),
                "ndvi_std":  round(float(np.std(nv))  if len(nv) > 1 else 0.05, 4),
                "vel_mean":  round(float(np.mean(vv)) if vv else 0.0, 5),
                "vel_std":   round(float(np.std(vv))  if len(vv) > 1 else 0.02, 5),
                "n_obs":     len(nv),
                "source":    "modis_mod13q1",
            })

        return {
            "commodity": commodity, "region": region,
            "baseline_period": f"{MODIS_BASELINE_START}/{MODIS_BASELINE_END}",
            "scene_count": len(items),
            "doy_bins": doy_bins_out,
        }

    except Exception as e:
        print(f"    [ERR] {e} — synthetic baseline")
        return synthetic_baseline(node)


def run():
    print(f"\n[MODIS BASELINE] Building for {len(NODES)} nodes\n")
    for node in NODES:
        key    = f"{node['commodity']}_{node['region']}"
        outpath = BASELINE_DIR / f"{key}_baseline.json"
        if outpath.exists():
            print(f"  [SKIP] {key} — baseline exists (delete to refresh)")
            continue
        result = build_modis_baseline(node)
        outpath.write_text(json.dumps(result, indent=2))
        print(f"  [OUT ] {key}_baseline.json")
    print(f"\n[MODIS BASELINE] Done\n")


if __name__ == "__main__":
    run()
