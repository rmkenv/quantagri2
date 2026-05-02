"""
QuantAgri — Signal Generator
==============================
Reads today's NDVI flat files, calls Ollama Cloud (qwen2.5) to generate
structured trading signals for every commodity/region node, and writes:

    data/signals/latest.json          ← full snapshot (all nodes)
    data/signals/{YYYY-MM-DD}.json    ← archived daily copy

Run:
    python scripts/generate_signals.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import NDVI_DIR, SIG_DIR, COMMODITIES, NODES
from ollama_client import chat_json


# ─────────────────────────────────────────────────────────────────────
SIGNAL_SYSTEM = """You are QuantAgri Spectral Velocity Engine v3.
You analyze Sentinel-2 NDVI/LSWI time series from Planetary Computer
and generate institutional-grade agricultural futures trading signals.
Always respond with valid JSON only. No markdown. No preamble."""


def build_signal_prompt(node_data: dict) -> str:
    commodity = node_data["commodity"]
    region    = node_data["region"].replace("_", " ")
    source    = node_data.get("source", "unknown")
    composites = node_data.get("composites", [])

    return f"""Analyze {commodity} futures for the {region} production region.

SPECTRAL DATA SOURCE: {source} (Planetary Computer · Sentinel-2 L2A)
PEAK NDVI:     {node_data.get('peak_ndvi', 'N/A')}
PEAK LSWI:     {node_data.get('peak_lswi', 'N/A')}
PEAK VELOCITY: {node_data.get('peak_velocity', 'N/A')}
SCENE COUNT:   {node_data.get('scene_count', 0)}
CLOUD COVER:   {node_data.get('cloud_cover_pct', 0)}%

16-DAY COMPOSITES:
{json.dumps(composites, indent=2)}

Return ONLY this JSON schema — no extra fields, no markdown:
{{
  "commodity": "{commodity}",
  "region": "{region}",
  "sentiment": "Bullish" | "Bearish" | "Neutral",
  "confidence": <float 0.0-1.0>,
  "rationale": "<2-3 sentences citing NDVI velocity, moisture stress, seasonal context>",
  "peakNdvi": <float>,
  "peakLswi": <float>,
  "spectralVelocity": "<e.g. +0.042/16d>",
  "divergenceZScore": <float>,
  "macroRegime": "<e.g. La Nina tightening | neutral | El Nino drought stress>",
  "strategy": {{
    "action": "LONG" | "SHORT" | "NEUTRAL",
    "entryZone": "<basis or price range>",
    "stopLoss": "<stop level>",
    "takeProfit": "<target level>",
    "riskReward": "<e.g. 2.4:1>"
  }},
  "featureBlocks": [
    {{"name": "NDVI Velocity",      "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.25}},
    {{"name": "LSWI Moisture",      "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.20}},
    {{"name": "Cloud Cover QA",     "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.10}},
    {{"name": "Seasonal Alignment", "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.20}},
    {{"name": "Macro Regime",       "status": "Pass"|"Caution"|"Fail", "signal": "<detail>", "weight": 0.25}}
  ]
}}"""


def load_latest_ndvi(commodity: str, region: str) -> dict | None:
    """Load most recent NDVI JSON for a given node."""
    pattern = f"{commodity}_{region}_*.json"
    files   = sorted(NDVI_DIR.glob(pattern))
    if not files:
        return None
    return json.loads(files[-1].read_text())


def run():
    today    = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")

    print(f"\n[SIGNALS] {date_str} — generating signals for {len(NODES)} nodes\n")

    results  = []
    errors   = []

    for node in NODES:
        commodity = node["commodity"]
        region    = node["region"]
        label     = f"{commodity}/{region}"

        ndvi_data = load_latest_ndvi(commodity, region)
        if ndvi_data is None:
            print(f"  [SKIP] {label} — no NDVI data found (run pc_pipeline.py first)")
            errors.append(label)
            continue

        print(f"  [LLM ] {label}")
        try:
            signal = chat_json(
                prompt = build_signal_prompt(ndvi_data),
                system = SIGNAL_SYSTEM,
            )
            signal["generatedAt"] = today.isoformat()
            signal["ndviSource"]  = ndvi_data.get("source", "unknown")
            results.append(signal)
            print(f"  [OK  ] {label} → {signal.get('sentiment','?')} · {signal.get('confidence',0):.0%}")
        except Exception as e:
            print(f"  [ERR ] {label}: {e}")
            errors.append(label)

    # ── Write outputs ─────────────────────────────────────────────────
    snapshot = {
        "generatedAt": today.isoformat(),
        "date":        date_str,
        "signalCount": len(results),
        "errors":      errors,
        "signals":     results,
    }

    latest_path = SIG_DIR / "latest.json"
    daily_path  = SIG_DIR / f"{date_str}.json"

    latest_path.write_text(json.dumps(snapshot, indent=2))
    daily_path.write_text(json.dumps(snapshot, indent=2))

    print(f"\n[SIGNALS] {len(results)} signals written → {latest_path}")
    if errors:
        print(f"[SIGNALS] {len(errors)} nodes skipped: {errors}")


if __name__ == "__main__":
    run()
