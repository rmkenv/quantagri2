"""
QuantAgri v2 — Signal Generator
==================================
Changes from v1:
  - Reads z-score files (from compute_zscore.py) in addition to raw NDVI files.
  - LLM prompt now receives vel_zscore and lswi_zscore alongside raw values.
  - Dominant quadrant and season-level z-score means passed to LLM context.
  - LLM prompt explicitly asks for quadrant-aware rationale.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import NDVI_DIR, SIG_DIR, COMMODITIES, NODES
from ollama_client import chat_json


SIGNAL_SYSTEM = """You are QuantAgri Spectral Velocity Engine v2.
You analyze Sentinel-2 NDVI/LSWI time series with MODIS-baseline z-scores
from Planetary Computer and generate institutional-grade agricultural
futures trading signals. Always respond with valid JSON only. No markdown."""


def build_signal_prompt(node_data: dict, zscore_data: dict | None) -> str:
    commodity = node_data["commodity"]
    region    = node_data["region"].replace("_", " ")
    source    = node_data.get("source", "unknown")
    composites = node_data.get("composites", [])

    # Z-score context (if available)
    z_block = ""
    if zscore_data:
        z_block = f"""
ANOMALY Z-SCORES (vs 2000-2015 MODIS baseline):
  Season vel z-score mean:  {zscore_data.get('season_vel_z_mean', 'N/A')}
  Season lswi z-score mean: {zscore_data.get('season_lswi_z_mean', 'N/A')}
  Dominant quadrant:        {zscore_data.get('dominant_quadrant', '?')}
    I=+vel/+lswi (normal growth)  II=+vel/-lswi (stress greenup)
    III=-vel/+lswi (heat senescence)  IV=-vel/-lswi (drought collapse)
"""

    return f"""Analyze {commodity} futures for the {region} production region.

SPECTRAL DATA SOURCE: {source} (Planetary Computer · Sentinel-2 L2A)
PEAK NDVI:     {node_data.get('peak_ndvi', 'N/A')}
PEAK LSWI:     {node_data.get('peak_lswi', 'N/A')}  [B8A-B11 / B8A+B11, true SWIR moisture]
PEAK VELOCITY: {node_data.get('peak_velocity', 'N/A')}
SCENE COUNT:   {node_data.get('scene_count', 0)}
CLOUD COVER:   {node_data.get('cloud_cover_pct', 0)}%
{z_block}
16-DAY COMPOSITES (gate window):
{json.dumps(composites, indent=2)}

Return ONLY this JSON schema:
{{
  "commodity": "{commodity}",
  "region": "{region}",
  "sentiment": "Bullish" | "Bearish" | "Neutral",
  "confidence": <float 0.0-1.0>,
  "rationale": "<2-3 sentences citing velocity z-score, moisture quadrant, seasonal context>",
  "peakNdvi": <float>,
  "peakLswi": <float>,
  "velZscore": <float or null>,
  "lswiZscore": <float or null>,
  "dominantQuadrant": "<I|II|III|IV|?>",
  "spectralVelocity": "<e.g. +0.042/16d>",
  "macroRegime": "<e.g. La Nina tightening | neutral | El Nino drought stress>",
  "strategy": {{
    "action": "LONG" | "SHORT" | "NEUTRAL",
    "entryZone": "<basis or price range>",
    "stopLoss": "<stop level>",
    "takeProfit": "<target level>",
    "riskReward": "<e.g. 2.4:1>"
  }},
  "featureBlocks": [
    {{"name": "NDVI Velocity Z-Score", "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.30}},
    {{"name": "LSWI Moisture Z-Score", "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.25}},
    {{"name": "Quadrant Classification","status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.15}},
    {{"name": "Cloud Cover QA",         "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.10}},
    {{"name": "Macro Regime",            "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.20}}
  ]
}}"""


def load_latest_ndvi(commodity: str, region: str) -> dict | None:
    pattern = f"{commodity}_{region}_*.json"
    files   = [f for f in sorted(NDVI_DIR.glob(pattern))
               if "zscore" not in f.name]
    return json.loads(files[-1].read_text()) if files else None


def load_latest_zscore(commodity: str, region: str) -> dict | None:
    """Load most recent z-score file for this node (current year)."""
    year = datetime.now(timezone.utc).year
    path = SIG_DIR / f"{commodity}_{region}_{year}_zscore.json"
    if path.exists():
        return json.loads(path.read_text())
    # Fall back: find any zscore for this node
    files = sorted(SIG_DIR.glob(f"{commodity}_{region}_*_zscore.json"))
    return json.loads(files[-1].read_text()) if files else None


def run():
    today    = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")
    print(f"\n[SIGNALS v2] {date_str} — {len(NODES)} nodes\n")

    results, errors = [], []

    for node in NODES:
        commodity = node["commodity"]
        region    = node["region"]
        label     = f"{commodity}/{region}"

        ndvi_data   = load_latest_ndvi(commodity, region)
        zscore_data = load_latest_zscore(commodity, region)

        if ndvi_data is None:
            print(f"  [SKIP] {label} — no NDVI data")
            errors.append(label)
            continue

        print(f"  [LLM ] {label}  z={'yes' if zscore_data else 'no'}")
        try:
            signal = chat_json(
                prompt=build_signal_prompt(ndvi_data, zscore_data),
                system=SIGNAL_SYSTEM,
            )
            signal["generatedAt"] = today.isoformat()
            signal["ndviSource"]  = ndvi_data.get("source", "unknown")
            signal["zscoreAvail"] = zscore_data is not None
            results.append(signal)
            print(f"  [OK  ] {label} → {signal.get('sentiment','?')} · "
                  f"{signal.get('confidence',0):.0%}  quad={signal.get('dominantQuadrant','?')}")
        except Exception as e:
            print(f"  [ERR ] {label}: {e}")
            errors.append(label)

    snapshot = {
        "generatedAt": today.isoformat(),
        "date":        date_str,
        "version":     "v2",
        "signalCount": len(results),
        "errors":      errors,
        "signals":     results,
    }

    (SIG_DIR / "latest.json").write_text(json.dumps(snapshot, indent=2))
    (SIG_DIR / f"{date_str}.json").write_text(json.dumps(snapshot, indent=2))

    print(f"\n[SIGNALS v2] {len(results)} signals written")
    if errors:
        print(f"  {len(errors)} nodes skipped: {errors}")


if __name__ == "__main__":
    run()
