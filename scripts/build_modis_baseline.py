"""
QuantAgri v2 — MODIS Baseline Builder
=======================================
Pulls MOD13Q1 (250m, 16-day) from Planetary Computer for 2000-2015.
Computes per-region per-DOY-bin velocity mean + std for z-score normalization.

Usage:
    # Build all nodes (called by GitHub Actions batch jobs)
    python scripts/build_modis_baseline.py --nodes Corn_Iowa_US Corn_Illinois_US

    # Build all nodes (local, sequential)
    python scripts/build_modis_baseline.py

    # Force rebuild even if baseline already exists
    python scripts/build_modis_baseline.py --force

    # Larger sample window (default 0.5 degrees)
    python scripts/build_modis_baseline.py --sample-deg 1.0
"""

import argparse
import json
import logging
import time
import warnings
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
logging.getLogger("rasterio").setLevel(logging.ERROR)
logging.getLogger("rasterio._env").setLevel(logging.ERROR)
logging.getLogger("stackstac").setLevel(logging.ERROR)

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import NODES as ALL_NODES, BASELINE_DIR

try:
    import pystac_client
    import planetary_computer as pc
    import stackstac
    PC_AVAILABLE = True
except ImportError:
    PC_AVAILABLE = False
    print("[WARN] PC libs not installed")

PC_STAC_URL    = "https://planetarycomputer.microsoft.com/api/stac/v1"
MODIS_COLL     = "modis-13Q1-061"
BASELINE_START = "2000-01-01"
BASELINE_END   = "2015-12-31"

# 23 DOY bin centres matching MOD13Q1 16-day compositing schedule
DOY_BINS = []
d = datetime(2001, 1, 1)
while d.year == 2001:
    DOY_BINS.append(int(d.strftime("%j")))
    d += timedelta(days=16)


def centre_sample(bbox, deg):
    """Small square window centred on region — fast to download."""
    lon_mid = (bbox[0] + bbox[2]) / 2
    lat_mid = (bbox[1] + bbox[3]) / 2
    return [lon_mid - deg, lat_mid - deg, lon_mid + deg, lat_mid + deg]


def search_with_retry(bbox, max_retries=4):
    for attempt in range(max_retries):
        try:
            catalog = pystac_client.Client.open(
                PC_STAC_URL,
                modifier=pc.sign_inplace,  # public SAS token, no key needed
            )
            items = catalog.search(
                collections=[MODIS_COLL],
                bbox=bbox,
                datetime=f"{BASELINE_START}/{BASELINE_END}",
            ).item_collection()
            return items
        except Exception as e:
            msg = str(e).lower()
            if "rate limit" in msg or "exceeded" in msg:
                wait = 30 * (2 ** attempt)
                print(f"  [rate limit] sleeping {wait}s...", flush=True)
                time.sleep(wait)
            elif attempt < max_retries - 1:
                time.sleep(10)
            else:
                raise
    return None


def build_baseline(node, sample_deg=0.5):
    commodity   = node["commodity"]
    region      = node["region"]
    full_bbox   = node["bbox"]
    sample_bbox = centre_sample(full_bbox, sample_deg)

    # Try sample bbox first, fall back to full bbox
    items = search_with_retry(sample_bbox)
    if not items or len(items) == 0:
        print(f"  [no scenes at sample, trying full bbox]", flush=True)
        items = search_with_retry(full_bbox)
        sample_bbox = full_bbox
    if not items or len(items) == 0:
        return None

    print(f"  {len(items)} scenes → stacking...", flush=True)

    stack = stackstac.stack(
        items,
        assets=["250m_16_days_NDVI"],
        resolution=250,
        bounds_latlon=sample_bbox,
        dtype="float64",   # compatible with fill_value=nan
        rescale=False,     # apply scale manually
        epsg=4326,         # explicit CRS — MODIS items lack embedded CRS
    )

    # Scale factor 0.0001, clip to valid NDVI range
    ndvi    = (stack.sel(band="250m_16_days_NDVI") * 0.0001).clip(-0.2, 1.0)
    ndvi_ts = ndvi.mean(dim=["x", "y"]).compute()

    ndvi_vals = [float(v) for v in ndvi_ts.values]
    times     = [str(t)[:10] for t in ndvi_ts.time.values]
    doys      = [int(datetime.strptime(t, "%Y-%m-%d").strftime("%j")) for t in times]

    # Central finite difference velocity
    n = len(ndvi_vals)
    vel_vals = [0.0] * n
    if n > 2:
        vel_vals[0]  = ndvi_vals[1]  - ndvi_vals[0]
        vel_vals[-1] = ndvi_vals[-1] - ndvi_vals[-2]
        for i in range(1, n - 1):
            vel_vals[i] = (ndvi_vals[i + 1] - ndvi_vals[i - 1]) / 2.0

    # Bin by nearest DOY centre, filter NaN and invalid
    bin_ndvi = defaultdict(list)
    bin_vel  = defaultdict(list)
    for doy, nv, vv in zip(doys, ndvi_vals, vel_vals):
        if np.isnan(nv) or not (-0.2 < nv < 1.0):
            continue
        nearest = min(DOY_BINS, key=lambda b: min(
            abs(doy - b), abs(doy - b + 365), abs(doy - b - 365)
        ))
        bin_ndvi[nearest].append(nv)
        bin_vel[nearest].append(vv)

    doy_bins_out = []
    for doy_bin in DOY_BINS:
        nv_list = bin_ndvi.get(doy_bin, [])
        vv_list = bin_vel.get(doy_bin, [])
        doy_bins_out.append({
            "doy_bin":   doy_bin,
            "ndvi_mean": round(float(np.mean(nv_list))   if nv_list          else 0.0,  4),
            "ndvi_std":  round(float(np.std(nv_list))    if len(nv_list) > 1 else 0.05, 4),
            "vel_mean":  round(float(np.mean(vv_list))   if vv_list          else 0.0,  5),
            "vel_std":   round(float(np.std(vv_list))    if len(vv_list) > 1 else 0.02, 5),
            "n_obs":     len(nv_list),
            "source":    "modis_mod13q1_pc",
        })

    return {
        "commodity":       commodity,
        "region":          region,
        "baseline_period": f"{BASELINE_START}/{BASELINE_END}",
        "sample_bbox":     sample_bbox,
        "sample_deg":      sample_deg,
        "scene_count":     len(items),
        "n_obs_total":     len(ndvi_vals),
        "doy_bins":        doy_bins_out,
    }


def run(node_keys=None, sample_deg=0.5, force=False):
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    # Filter nodes if specific keys provided
    nodes = ALL_NODES
    if node_keys:
        nodes = [
            n for n in ALL_NODES
            if f"{n['commodity']}_{n['region']}" in node_keys
        ]
        if not nodes:
            print(f"[ERROR] No matching nodes for: {node_keys}")
            sys.exit(1)

    print(f"\n[MODIS BASELINE] {len(nodes)} nodes  sample_deg={sample_deg}  force={force}\n")

    results = {}
    for i, node in enumerate(nodes):
        key     = f"{node['commodity']}_{node['region']}"
        outpath = BASELINE_DIR / f"{key}_baseline.json"

        # Skip if already real and not forcing
        if outpath.exists() and not force:
            existing = json.loads(outpath.read_text())
            src = existing.get("doy_bins", [{}])[0].get("source", "")
            if src == "modis_mod13q1_pc":
                print(f"[{i+1:02d}/{len(nodes)}] {key} — ✓ already real, skip")
                results[key] = "ok"
                continue

        print(f"[{i+1:02d}/{len(nodes)}] {key}")
        try:
            if not PC_AVAILABLE:
                raise RuntimeError("PC libraries not available")

            baseline = build_baseline(node, sample_deg=sample_deg)
            if baseline is None:
                print(f"  ✗ no scenes returned")
                results[key] = "no_data"
                continue

            mid = baseline["doy_bins"][11]
            print(f"  ✓ scenes={baseline['scene_count']}  "
                  f"n_obs={mid['n_obs']}  "
                  f"vel_mean={mid['vel_mean']:+.4f}  "
                  f"vel_std={mid['vel_std']:.4f}")

            outpath.write_text(json.dumps(baseline, indent=2))
            results[key] = "ok"
            time.sleep(5)

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            results[key] = str(e)
            time.sleep(15)

    ok   = [k for k, v in results.items() if v == "ok"]
    fail = [k for k, v in results.items() if v not in ("ok", "no_data")]
    print(f"\n[MODIS BASELINE] {len(ok)}/{len(nodes)} succeeded")
    if fail:
        print("Failed nodes:")
        for k in fail:
            print(f"  {k}: {results[k][:100]}")
        sys.exit(1)  # non-zero exit so GitHub Actions marks step as failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--nodes", nargs="+", default=None,
        help="Specific node keys to build e.g. Corn_Iowa_US Corn_Illinois_US"
    )
    parser.add_argument(
        "--sample-deg", type=float, default=0.5,
        help="Sample window half-width in degrees (default 0.5)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Rebuild even if baseline already exists"
    )
    args = parser.parse_args()
    run(node_keys=args.nodes, sample_deg=args.sample_deg, force=args.force)
