"""
QuantAgri — Monthly Podcast Script Generator
=============================================
Aggregates the month's signal data AND price history,
then generates a professional single-host podcast script.

Output:
    data/podcast/{YYYY-MM}.md
    data/podcast/latest.md

Schedule: 1st of each month 07:30 UTC
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import SIG_DIR, POD_DIR, COMMODITIES
from ollama_client import chat
from fetch_prices import PRICE_DIR, format_price_summary


def load_monthly_signals(year: int, month: int) -> list[dict]:
    signals = []
    for path in sorted(SIG_DIR.glob("*.json")):
        if path.name == "latest.json":
            continue
        try:
            date = datetime.strptime(path.stem, "%Y-%m-%d")
            if date.year == year and date.month == month:
                snap = json.loads(path.read_text())
                signals.extend(snap.get("signals", []))
        except ValueError:
            continue
    return signals


def load_latest_prices() -> dict:
    path = PRICE_DIR / "latest.json"
    if not path.exists():
        return {"etfs": {}, "futures": {}, "commodityPrices": {}, "date": "unknown"}
    return json.loads(path.read_text())


def aggregate_monthly(signals: list[dict]) -> str:
    if not signals:
        return "No signal data available for this month."
    by_commodity: dict[str, list] = {}
    for s in signals:
        c = s.get("commodity", "Unknown")
        by_commodity.setdefault(c, []).append(s)
    lines = []
    for commodity, sigs in by_commodity.items():
        sentiments = [s.get("sentiment") for s in sigs]
        bull = sentiments.count("Bullish")
        bear = sentiments.count("Bearish")
        neut = sentiments.count("Neutral")
        avg_conf  = sum(s.get("confidence", 0) for s in sigs) / len(sigs)
        peak_ndvis = [s.get("peakNdvi") for s in sigs if s.get("peakNdvi")]
        avg_ndvi  = round(sum(peak_ndvis) / len(peak_ndvis), 3) if peak_ndvis else "N/A"
        regimes   = list({s.get("macroRegime", "") for s in sigs if s.get("macroRegime")})
        lines.append(
            f"### {commodity}\n"
            f"- Signal distribution: {bull} Bullish / {bear} Bearish / {neut} Neutral\n"
            f"- Avg confidence: {avg_conf:.0%} | Avg peak NDVI: {avg_ndvi}\n"
            f"- Macro regimes: {', '.join(regimes[:3]) or 'N/A'}\n"
            f"- Latest rationale: {sigs[-1].get('rationale', 'N/A')[:200]}"
        )
    return "\n\n".join(lines)


def build_podcast_prompt(month_name: str, year: int, summary: str, prices: dict) -> str:
    price_block = format_price_summary(prices)
    price_date  = prices.get("date", "unknown")

    cp = prices.get("commodityPrices", {})
    commodity_price_lines = []
    for commodity in COMMODITIES:
        if commodity in cp:
            d = cp[commodity]
            commodity_price_lines.append(
                f"  {commodity}: {d['ticker']} ${d['price']:,.4f} | "
                f"Week: {d['weekChg']:+.2f}% | 52wk: ${d['low52w']:,.2f}--${d['high52w']:,.2f}"
            )
        else:
            commodity_price_lines.append(f"  {commodity}: price data unavailable")
    prices_summary = "\n".join(commodity_price_lines)

    return f"""You are the host of "Spectral Alpha" — QuantAgri's monthly agricultural markets podcast.
This episode covers {month_name} {year}. Write a complete, professional single-host script.
CRITICAL: Reference the REAL prices provided below. Never fabricate prices.

== CURRENT MARKET PRICES (Yahoo Finance, {price_date}) ==
{prices_summary}

{price_block}

== MONTHLY NDVI SIGNAL SUMMARY (Planetary Computer) ==
{summary}

TONE: Institutional. "The Daily" meets "Bloomberg Surveillance".
Use: basis risk, spectral velocity, phenological decoupling, WASDE divergence, carry, roll yield.
LENGTH: 900-1,200 words. Continuous spoken narrative — no stage directions.

## THE HOOK
The single biggest gap between NDVI spectral signals and current futures prices in {month_name}.
Open with a specific commodity, price level, and what the satellite data showed vs consensus.

## {month_name.upper()} IN REVIEW
Walk through Soybeans, Corn, Wheat, Sugar, Cotton.
For each: quote the current price, reference NDVI velocity, note any signal vs price divergence.

## THE MACRO PICTURE
How do {month_name}'s spectral signals fit into supply/demand balance?
Reference La Nina/El Nino regime, any WASDE context, basis levels.

## SPECTRAL ALPHA
Where did NDVI/LSWI signals diverge from futures pricing most significantly this month?
Be specific — which nodes, which Z-scores, what the price implication was.

## THE OUTLOOK
3-4 specific things to watch next month: growing season windows, WASDE release dates,
specific price levels to monitor based on current spectral positioning.

---
*QuantAgri Spectral Alpha · {month_name} {year}*
*Prices: Yahoo Finance ({price_date}). Data: Planetary Computer Sentinel-2. Not investment advice.*
"""


def run():
    today  = datetime.now(timezone.utc)
    year   = today.year
    if today.day == 1:
        first_of_month = today.replace(day=1)
        last_month     = first_of_month - timedelta(days=1)
        target_year    = last_month.year
        target_month   = last_month.month
    else:
        target_year  = year
        target_month = today.month

    month_name = datetime(target_year, target_month, 1).strftime("%B")
    month_str  = f"{target_year}-{target_month:02d}"

    print(f"\n[PODCAST] {month_name} {target_year}\n")

    signals = load_monthly_signals(target_year, target_month)
    if not signals:
        latest = SIG_DIR / "latest.json"
        if latest.exists():
            snap    = json.loads(latest.read_text())
            signals = snap.get("signals", [])
            print(f"  [FALL] Using latest.json — {len(signals)} signals")
    else:
        print(f"  [DATA] {len(signals)} signals for {month_name}")

    prices = load_latest_prices()
    print(f"  [PX  ] {len(prices.get('etfs',{}))} ETFs + {len(prices.get('futures',{}))} futures ({prices.get('date','?')})")

    summary = aggregate_monthly(signals)
    prompt  = build_podcast_prompt(month_name, target_year, summary, prices)

    print(f"  [LLM ] {len(prompt):,} char prompt — calling Ollama Cloud...")
    script = chat(prompt, as_json=False, temperature=0.5)

    out_path    = POD_DIR / f"{month_str}.md"
    latest_path = POD_DIR / "latest.md"
    out_path.write_text(script)
    latest_path.write_text(script)

    print(f"  [OUT ] {out_path}")
    print(f"  [OUT ] {latest_path}")
    print(f"\n[PODCAST] Done — {len(script):,} chars\n")


if __name__ == "__main__":
    run()
