"""
QuantAgri — Weekly Intelligence Newsletter
==========================================
Reads live price data (ETFs + futures) AND the latest signal snapshot,
then calls Ollama Cloud to generate "The QuantAgri Intelligence Weekly".

Price data comes from fetch_prices.py (yfinance / Yahoo Finance — free).
Signal data comes from generate_signals.py (Planetary Computer NDVI).

Output:
    data/newsletter/{YYYY-MM-DD}.md   <- weekly report
    data/newsletter/latest.md         <- always most recent

Schedule: Every Monday 07:00 UTC (after prices + signals have run)

Run manually:
    python scripts/fetch_prices.py    # get prices first
    python scripts/newsletter.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import SIG_DIR, NEWS_DIR, COMMODITIES, ETFS
from ollama_client import chat
from fetch_prices import PRICE_DIR, format_price_summary


def load_latest_signals() -> dict:
    path = SIG_DIR / "latest.json"
    if not path.exists():
        raise FileNotFoundError(
            "data/signals/latest.json not found — run generate_signals.py first"
        )
    return json.loads(path.read_text())


def load_latest_prices() -> dict:
    path = PRICE_DIR / "latest.json"
    if not path.exists():
        print("  [WARN] No price data found — run fetch_prices.py first")
        return {"etfs": {}, "futures": {}, "commodityPrices": {}, "date": "unknown"}
    return json.loads(path.read_text())


def summarise_signals(snapshot: dict) -> str:
    lines = []
    for s in snapshot.get("signals", []):
        fb_pass  = sum(1 for f in s.get("featureBlocks", []) if f.get("status") == "Pass")
        fb_total = len(s.get("featureBlocks", []))
        lines.append(
            f"- {s.get('commodity')} / {s.get('region', '').replace('_', ' ')}: "
            f"{s.get('sentiment')} ({s.get('confidence', 0):.0%} conf) | "
            f"Action: {s.get('strategy', {}).get('action', 'N/A')} | "
            f"NDVI peak: {s.get('peakNdvi', 'N/A')} | "
            f"Velocity: {s.get('spectralVelocity', 'N/A')} | "
            f"Z-score: {s.get('divergenceZScore', 'N/A')} | "
            f"Macro: {s.get('macroRegime', 'N/A')} | "
            f"Feature audit: {fb_pass}/{fb_total} Pass | "
            f"{s.get('rationale', '')[:140]}"
        )
    return "\n".join(lines) if lines else "No signal data available."


def build_etf_table(prices: dict) -> str:
    etfs = prices.get("etfs", {})
    if not etfs:
        return "| Ticker | Price | Day | Week | 52w Range |\n|---|---|---|---|---|\n| No data | — | — | — | — |"
    rows = [
        "| Ticker | Name | Price | Day | Week | 52w Low | 52w High | % of High |",
        "|--------|------|------:|----:|-----:|--------:|---------:|----------:|",
    ]
    for ticker, d in etfs.items():
        rows.append(
            f"| {ticker} | {d['name']} | ${d['price']:.4f} | {d['dayChg']:+.2f}% | "
            f"{d['weekChg']:+.2f}% | ${d['low52w']:.2f} | ${d['high52w']:.2f} | {d['pctOf52wH']:.0f}% |"
        )
    return "\n".join(rows)


def build_futures_table(prices: dict) -> str:
    futures = prices.get("futures", {})
    if not futures:
        return "| Contract | Price | Day | Week | 52w Range |\n|---|---|---|---|---|\n| No data | — | — | — | — |"
    rows = [
        "| Contract | Name | Price | Day | Week | 52w Low | 52w High |",
        "|----------|------|------:|----:|-----:|--------:|---------:|",
    ]
    for ticker, d in futures.items():
        rows.append(
            f"| {ticker} | {d['name']} | ${d['price']:,.4f} | {d['dayChg']:+.2f}% | "
            f"{d['weekChg']:+.2f}% | ${d['low52w']:,.2f} | ${d['high52w']:,.2f} |"
        )
    return "\n".join(rows)


def build_newsletter_prompt(today_str: str, signal_summary: str, prices: dict) -> str:
    etf_table     = build_etf_table(prices)
    futures_table = build_futures_table(prices)
    price_date    = prices.get("date", "unknown")

    cp = prices.get("commodityPrices", {})
    commodity_price_lines = []
    for commodity in COMMODITIES:
        if commodity in cp:
            d = cp[commodity]
            commodity_price_lines.append(
                f"  {commodity}: {d['ticker']} ${d['price']:,.4f} | "
                f"Day: {d['dayChg']:+.2f}% | Week: {d['weekChg']:+.2f}% | "
                f"52wk: ${d['low52w']:,.2f}--${d['high52w']:,.2f}"
            )
        else:
            commodity_price_lines.append(f"  {commodity}: price data unavailable this week")
    commodity_prices_block = "\n".join(commodity_price_lines)

    return f"""You are the lead analyst at QuantAgri writing "The QuantAgri Intelligence Weekly".
Today is {today_str}. Write a complete institutional-quality weekly newsletter in Markdown.
CRITICAL: Use ONLY the real prices provided below. Never fabricate or estimate prices.

== LIVE MARKET DATA (Yahoo Finance, {price_date}) ==

COMMODITY FUTURES:
{commodity_prices_block}

FUTURES TABLE:
{futures_table}

ETF TABLE:
{etf_table}

== PLANETARY COMPUTER NDVI SIGNALS (Sentinel-2 L2A) ==
{signal_summary}

== WRITING INSTRUCTIONS ==
TONE: Bloomberg Surveillance meets institutional Substack research. Data-dense, precise.
LENGTH: Minimum 1,200 words across all sections.
PRICES: Quote exact prices from the tables above. Connect price action to NDVI signals.
The core insight: where does satellite spectral velocity DIVERGE from current futures pricing?

Write this exact structure:

# The QuantAgri Intelligence Weekly
## {today_str}

---

**TEASER:** [1-2 sentence hook — the biggest gap between NDVI signal and current price this week]

---

## Executive Overview
[Min 150 words. What do NDVI signals say vs what futures prices currently imply?
Be specific: quote actual prices, z-scores, NDVI velocity figures.]

## Live Market Snapshot

### Commodity Futures
[Include the full futures markdown table from the data above, verbatim.
Then 2-3 sentences on the biggest weekly mover and why it matters.]

### Agricultural ETFs
[Include the full ETF markdown table from the data above, verbatim.
Then note best/worst performer and any noteworthy 52-week positioning.]

## Commodity Deep Dives

### Soybeans
**Current Price:** [exact futures price from data] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [Reference Iowa/Mato Grosso node NDVI data]
**Signal vs Price Divergence:** [Does current price reflect what NDVI implies?]
**Investor Implications:** [Specific level, target, rationale]

### Corn
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail]
**Signal vs Price Divergence:** [detail]
**Investor Implications:** [detail]

### Wheat
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail]
**Signal vs Price Divergence:** [detail]
**Investor Implications:** [detail]

### Sugar
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail]
**Signal vs Price Divergence:** [detail]
**Investor Implications:** [detail]

### Cotton
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail]
**Signal vs Price Divergence:** [detail]
**Investor Implications:** [detail]

## ETF Technical Audit
[For each ETF (CORN, SOYB, WEAT, CANE, TAGS, DBA): quote exact price and weekly change,
comment on 52-week positioning (pctOf52wH), and link to underlying commodity NDVI signal.
Min 2 sentences per ETF.]

## Spectral Alpha This Week
[Min 150 words. Where did NDVI/LSWI signals lead current pricing?
Name specific nodes, Z-scores, and how they compare to current futures levels.]

## What to Watch Next Week
- [Specific price levels / WASDE dates / NDVI thresholds to monitor]
- [3-5 bullets total]

---
*The QuantAgri Intelligence Weekly · {today_str}*
*Prices: Yahoo Finance (live, {price_date}). Spectral data: Planetary Computer Sentinel-2.*
*LLM: Ollama Cloud qwen2.5. Not investment advice.*
"""


def run():
    today     = datetime.now(timezone.utc)
    today_str = today.strftime("%B %d, %Y")
    date_str  = today.strftime("%Y-%m-%d")

    print(f"\n[NEWSLETTER] {today_str}\n")

    try:
        snapshot = load_latest_signals()
        print(f"  [SIG ] {snapshot.get('signalCount', 0)} signals loaded")
    except FileNotFoundError as e:
        print(f"  [ERR ] {e}")
        return

    prices = load_latest_prices()
    print(f"  [PX  ] {len(prices.get('etfs',{}))} ETFs + {len(prices.get('futures',{}))} futures ({prices.get('date','?')})")

    signal_summary = summarise_signals(snapshot)
    prompt         = build_newsletter_prompt(today_str, signal_summary, prices)

    print(f"  [LLM ] {len(prompt):,} char prompt — calling Ollama Cloud...")
    markdown = chat(prompt, as_json=False, temperature=0.35)

    out_path    = NEWS_DIR / f"{date_str}.md"
    latest_path = NEWS_DIR / "latest.md"
    out_path.write_text(markdown)
    latest_path.write_text(markdown)

    print(f"  [OUT ] {out_path}")
    print(f"  [OUT ] {latest_path}")
    print(f"\n[NEWSLETTER] Done — {len(markdown):,} chars\n")


if __name__ == "__main__":
    run()
