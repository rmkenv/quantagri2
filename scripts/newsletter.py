"""
QuantAgri — Weekly Intelligence Newsletter
Reads live prices (yfinance) + NDVI signals, generates newsletter via Ollama Cloud.
Output: data/newsletter/latest.md + data/newsletter/{YYYY-MM-DD}.md
"""

import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import SIG_DIR, NEWS_DIR, COMMODITIES, ETFS
from ollama_client import chat
from fetch_prices import PRICE_DIR, format_price_summary


def load_latest_signals() -> dict:
    path = SIG_DIR / "latest.json"
    if not path.exists():
        raise FileNotFoundError("data/signals/latest.json not found — run generate_signals.py first")
    return json.loads(path.read_text())


def load_latest_prices() -> dict:
    path = PRICE_DIR / "latest.json"
    if not path.exists():
        print("  [WARN] No price data — run fetch_prices.py first")
        return {"etfs": {}, "futures": {}, "commodityPrices": {}, "date": "unknown"}
    return json.loads(path.read_text())


def summarise_signals(snapshot: dict) -> str:
    lines = []
    for s in snapshot.get("signals", []):
        fb_pass  = sum(1 for f in s.get("featureBlocks", []) if f.get("status") == "Pass")
        fb_total = len(s.get("featureBlocks", []))
        lines.append(
            f"- {s.get('commodity')} / {s.get('region','').replace('_',' ')}: "
            f"{s.get('sentiment')} ({s.get('confidence',0):.0%} conf) | "
            f"Action: {s.get('strategy',{}).get('action','N/A')} | "
            f"NDVI peak: {s.get('peakNdvi','N/A')} | Velocity: {s.get('spectralVelocity','N/A')} | "
            f"Z-score: {s.get('divergenceZScore','N/A')} | Macro: {s.get('macroRegime','N/A')} | "
            f"Audit: {fb_pass}/{fb_total} Pass | {s.get('rationale','')[:140]}"
        )
    return "\n".join(lines) if lines else "No signal data available."


def build_etf_table(prices: dict) -> str:
    etfs = prices.get("etfs", {})
    if not etfs:
        return "| Ticker | Price | Day | Week | 52w Range |\n|---|---|---|---|---|\n| No data | — | — | — | — |"
    rows = ["| Ticker | Name | Price | Day | Week | 52w Low | 52w High | % of High |",
            "|--------|------|------:|----:|-----:|--------:|---------:|----------:|"]
    for ticker, d in etfs.items():
        rows.append(f"| {ticker} | {d['name']} | ${d['price']:.4f} | {d['dayChg']:+.2f}% | "
                    f"{d['weekChg']:+.2f}% | ${d['low52w']:.2f} | ${d['high52w']:.2f} | {d['pctOf52wH']:.0f}% |")
    return "\n".join(rows)


def build_futures_table(prices: dict) -> str:
    futures = prices.get("futures", {})
    if not futures:
        return "| Contract | Price | Day | Week | 52w Range |\n|---|---|---|---|---|\n| No data | — | — | — | — |"
    rows = ["| Contract | Name | Price | Day | Week | 52w Low | 52w High |",
            "|----------|------|------:|----:|-----:|--------:|---------:|"]
    for ticker, d in futures.items():
        rows.append(f"| {ticker} | {d['name']} | ${d['price']:,.4f} | {d['dayChg']:+.2f}% | "
                    f"{d['weekChg']:+.2f}% | ${d['low52w']:,.2f} | ${d['high52w']:,.2f} |")
    return "\n".join(rows)


def build_newsletter_prompt(today_str: str, signal_summary: str, prices: dict) -> str:
    etf_table     = build_etf_table(prices)
    futures_table = build_futures_table(prices)
    price_date    = prices.get("date", "unknown")
    cp            = prices.get("commodityPrices", {})

    cplines = []
    for commodity in COMMODITIES:
        if commodity in cp:
            d = cp[commodity]
            cplines.append(f"  {commodity}: {d['ticker']} ${d['price']:,.4f} | "
                           f"Day: {d['dayChg']:+.2f}% | Week: {d['weekChg']:+.2f}% | "
                           f"52wk: ${d['low52w']:,.2f}--${d['high52w']:,.2f}")
        else:
            cplines.append(f"  {commodity}: price data unavailable this week")

    return f"""You are the lead analyst at QuantAgri writing "The QuantAgri Intelligence Weekly".
Today is {today_str}. Write a complete institutional newsletter in Markdown.
CRITICAL: Use ONLY the real prices below. Never fabricate prices.

== LIVE MARKET DATA (Yahoo Finance, {price_date}) ==
COMMODITY FUTURES:
{chr(10).join(cplines)}

FUTURES TABLE:
{futures_table}

ETF TABLE:
{etf_table}

== PLANETARY COMPUTER NDVI SIGNALS ==
{signal_summary}

== INSTRUCTIONS ==
TONE: Bloomberg Surveillance meets institutional Substack. Data-dense, precise.
LENGTH: Minimum 1,200 words. PRICES: Quote exact prices. Connect to NDVI signals.

# The QuantAgri Intelligence Weekly
## {today_str}
---
**TEASER:** [biggest gap between NDVI signal and current price this week]
---
## Executive Overview
[Min 150 words — NDVI vs futures pricing, specific numbers]
## Live Market Snapshot
### Commodity Futures
[Reproduce futures table verbatim, then 2-3 sentences on biggest weekly mover]
### Agricultural ETFs
[Reproduce ETF table verbatim, then best/worst performer + 52w positioning]
## Commodity Deep Dives
### Soybeans
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [Iowa/Mato Grosso NDVI data]
**Signal vs Price Divergence:** [analysis]
**Investor Implications:** [levels, target, rationale]
### Corn
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail] **Signal vs Price Divergence:** [detail] **Investor Implications:** [detail]
### Wheat
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail] **Signal vs Price Divergence:** [detail] **Investor Implications:** [detail]
### Sugar
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail] **Signal vs Price Divergence:** [detail] **Investor Implications:** [detail]
### Cotton
**Current Price:** [exact] | **Weekly Change:** [exact %]
**Spectral Velocity Analysis:** [detail] **Signal vs Price Divergence:** [detail] **Investor Implications:** [detail]
## ETF Technical Audit
[Each ETF: exact price, weekly change, 52w positioning, link to NDVI signal. Min 2 sentences each.]
## Spectral Alpha This Week
[Min 150 words — where NDVI led pricing, specific nodes, Z-scores, price levels]
## What to Watch Next Week
- [3-5 bullets: price levels, WASDE dates, NDVI thresholds]
---
*The QuantAgri Intelligence Weekly · {today_str}*
*Prices: Yahoo Finance ({price_date}). Data: Planetary Computer Sentinel-2. Not investment advice.*"""


def run():
    today     = datetime.now(timezone.utc)
    today_str = today.strftime("%B %d, %Y")
    date_str  = today.strftime("%Y-%m-%d")
    print(f"\n[NEWSLETTER] {today_str}\n")

    try:
        snapshot = load_latest_signals()
        print(f"  [SIG ] {snapshot.get('signalCount',0)} signals loaded")
    except FileNotFoundError as e:
        print(f"  [ERR ] {e}"); return

    prices = load_latest_prices()
    print(f"  [PX  ] {len(prices.get('etfs',{}))} ETFs + {len(prices.get('futures',{}))} futures ({prices.get('date','?')})")

    prompt   = build_newsletter_prompt(today_str, summarise_signals(snapshot), prices)
    print(f"  [LLM ] {len(prompt):,} chars — calling Ollama Cloud...")
    markdown = chat(prompt, as_json=False, temperature=0.35)

    (NEWS_DIR / f"{date_str}.md").write_text(markdown)
    (NEWS_DIR / "latest.md").write_text(markdown)
    print(f"  [OUT ] {NEWS_DIR}/latest.md")
    print(f"\n[NEWSLETTER] Done — {len(markdown):,} chars\n")


if __name__ == "__main__":
    run()
