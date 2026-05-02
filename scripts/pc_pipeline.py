"""
QuantAgri — Planetary Computer Pipeline
Pulls Sentinel-2 L2A, computes NDVI/LSWI, writes flat JSON.
Output: data/ndvi/{commodity}_{region}_{YYYY-MM-DD}.json
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
import sys
import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
from config import NODES, SEASONS, NDVI_DIR, PC_STAC_URL, COLLECTION, MAX_CLOUD_PCT, RESOLUTION

try:
    import planetary_computer as pc
    import pystac_client
    import stackstac
    PC_AVAILABLE = True
except ImportError:
    PC_AVAILABLE = False
    print("[WARN] planetary-computer / stackstac not installed — using simulated NDVI")


def simulate_node(node: dict, year: int) -> dict:
    commodity = node["commodity"]
    peak_cfg = {
        "Soybeans": dict(peak=7, ndvi_max=0.81, lswi_max=0.44),
        "Corn":     dict(peak=7, ndvi_max=0.85, lswi_max=0.40),
        "Wheat":    dict(peak=5, ndvi_max=0.74, lswi_max=0.38),
        "Sugar":    dict(peak=9, ndvi_max=0.77, lswi_max=0.56),
        "Cotton":   dict(peak=8, ndvi_max=0.68, lswi_max=0.30),
    }.get(commodity, dict(peak=7, ndvi_max=0.75, lswi_max=0.38))

    rng = np.random.default_rng(seed=abs(hash(node["region"])) % 2**31)
    months = list(range(1, 13))
    ndvi_series, lswi_series = [], []

    for m in months:
        dist = abs(m - peak_cfg["peak"])
        f    = np.exp(-0.14 * dist**2)
        ndvi_series.append(float(np.clip(peak_cfg["ndvi_max"] * f + 0.11 + rng.normal(0, 0.02), 0.05, 0.95)))
        lswi_series.append(float(np.clip(peak_cfg["lswi_max"] * f + 0.04 + rng.normal(0, 0.015), 0.02, 0.80)))

    velocity = list(np.gradient(ndvi_series))
    return dict(
        commodity=commodity, region=node["region"], bbox=node["bbox"], year=year,
        source="simulated",
        composites=[
            dict(month=m, ndvi=round(n, 4), lswi=round(l, 4), velocity=round(v, 5))
            for m, n, l, v in zip(months, ndvi_series, lswi_series, velocity)
        ],
        peak_ndvi=round(float(max(ndvi_series)), 4),
        peak_lswi=round(float(max(lswi_series)), 4),
        peak_velocity=round(float(max(velocity)), 5),
        cloud_cover_pct=0.0, scene_count=0,
    )


def fetch_node(node: dict, year: int) -> dict:
    if not PC_AVAILABLE:
        return simulate_node(node, year)

    commodity = node["commodity"]
    region    = node["region"]
    bbox      = node["bbox"]
    m_start, m_end = SEASONS.get(commodity, ("04", "10"))
    date_range = f"{year}-{m_start}-01/{year}-{m_end}-30"
    print(f"  [PC ] {commodity}/{region} · {date_range}")

    try:
        catalog = pystac_client.Client.open(PC_STAC_URL, modifier=pc.sign_inplace)
        items   = catalog.search(
            collections=[COLLECTION], bbox=bbox, datetime=date_range,
            query={"eo:cloud_cover": {"lt": MAX_CLOUD_PCT}},
        ).item_collection()

        if len(items) == 0:
            print(f"  [WARN] No scenes for {region} — simulating")
            return simulate_node(node, year)

        stack = stackstac.stack(items, assets=["B04","B08","B11"],
                                resolution=RESOLUTION, bounds_latlon=bbox)
        eps = 1e-10
        b4  = stack.sel(band="B04").astype("float32") / 10000.0
        b8  = stack.sel(band="B08").astype("float32") / 10000.0
        b11 = stack.sel(band="B11").astype("float32") / 10000.0
        ndvi = ((b8 - b4)  / (b8 + b4  + eps)).clip(-1.0, 1.0)
        lswi = ((b8 - b11) / (b8 + b11 + eps)).clip(-1.0, 1.0)

        ndvi_comp = ndvi.resample(time="16D").median().mean(dim=["x","y"])
        lswi_comp = lswi.resample(time="16D").median().mean(dim=["x","y"])
        ndvi_vals = [float(v) for v in ndvi_comp.values]
        lswi_vals = [float(v) for v in lswi_comp.values]
        times     = [str(t)[:10] for t in ndvi_comp.time.values]
        velocity  = list(np.gradient(ndvi_vals))
        avg_cloud = float(sum(i.properties.get("eo:cloud_cover",0) for i in items)/len(items))

        return dict(
            commodity=commodity, region=region, bbox=bbox, year=year,
            source="planetary_computer",
            composites=[dict(date=t,ndvi=round(n,4),lswi=round(l,4),velocity=round(v,5))
                        for t,n,l,v in zip(times,ndvi_vals,lswi_vals,velocity)],
            peak_ndvi=round(float(max(ndvi_vals)),4),
            peak_lswi=round(float(max(lswi_vals)),4),
            peak_velocity=round(float(max(velocity)),5),
            cloud_cover_pct=round(avg_cloud,1), scene_count=len(items),
        )
    except Exception as e:
        print(f"  [ERR ] {region}: {e} — simulating")
        return simulate_node(node, year)


def run():
    today    = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")
    print(f"\n[PC PIPELINE] {date_str} — {len(NODES)} nodes\n")
    for node in NODES:
        result  = fetch_node(node, today.year)
        fname   = f"{node['commodity']}_{node['region']}_{date_str}.json"
        (NDVI_DIR / fname).write_text(json.dumps(result, indent=2))
        print(f"  [OUT] {fname}")
    print(f"\n[PC PIPELINE] Done\n")


if __name__ == "__main__":
    run()
