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
        # Include velocity sign explicitly so LLM doesn't mislabel direction
        velocity = s.get('spectralVelocity', 'N/A')
        sentiment = s.get('sentiment', 'N/A')
        lines.append(
            f"- {s.get('commodity')} / {s.get('region','').replace('_',' ')}: "
            f"Sentiment={sentiment} ({s.get('confidence',0):.0%} conf) | "
            f"Action: {s.get('strategy',{}).get('action','N/A')} | "
            f"NDVI peak: {s.get('peakNdvi','N/A')} | "
            f"Velocity: {velocity} (POSITIVE=improving crop, NEGATIVE=declining) | "
            f"Z-score: {s.get('divergenceZScore','N/A')} | "
            f"Macro: {s.get('macroRegime','N/A')} | "
            f"Audit: {fb_pass}/{fb_total} Pass | "
            f"{s.get('rationale','')[:140]}"
        )
    return "\n".join(lines) if lines else "No signal data available."


def build_etf_table(prices: dict) -> str:
    etfs = prices.get("etfs", {})
    if not etfs:
        return "| Ticker | Price | Day | Week | 52w Low | 52w High | % of High |\n|---|---|---|---|---|---|---|\n| No data | — | — | — | — | — | — |"
    rows = ["| Ticker | Name | Price | Day | Week | 52w Low | 52w High | % of High |",
            "|--------|------|------:|----:|-----:|--------:|---------:|----------:|"]
    for ticker, d in etfs.items():
        # Compute % of high precisely from the actual numbers
        pct = round((d['price'] / d['high52w']) * 100, 1) if d['high52w'] else 0
        day_str = f"{d['dayChg']:+.2f}%" if d.get('dayChg') is not None else "n/a"
        rows.append(
            f"| {ticker} | {d['name']} | ${d['price']:.4f} | {day_str} | "
            f"{d['weekChg']:+.2f}% | ${d['low52w']:.2f} | ${d['high52w']:.2f} | {pct:.1f}% |"
        )
    return "\n".join(rows)


def build_futures_table(prices: dict) -> str:
    futures = prices.get("futures", {})
    if not futures:
        return "| Contract | Price | Day | Week | 52w Low | 52w High | % of High |\n|---|---|---|---|---|---|---|\n| No data | — | — | — | — | — | — |"
    rows = ["| Contract | Name | Price | Day | Week | 52w Low | 52w High | % of High |",
            "|----------|------|------:|----:|-----:|--------:|---------:|----------:|"]
    for ticker, d in futures.items():
        pct = round((d['price'] / d['high52w']) * 100, 1) if d['high52w'] else 0
        day_str = f"{d['dayChg']:+.2f}%" if d.get('dayChg') is not None else "n/a"
        rows.append(
            f"| {ticker} | {d['name']} | ${d['price']:,.4f} | {day_str} | "
            f"{d['weekChg']:+.2f}% | ${d['low52w']:,.2f} | ${d['high52w']:,.2f} | {pct:.1f}% |"
        )
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
            pct = round((d['price'] / d['high52w']) * 100, 1) if d.get('high52w') else 0
            day_str = f"{d['dayChg']:+.2f}%" if d.get('dayChg') is not None else "n/a"
            cplines.append(
                f"  {commodity}: {d['ticker']} ${d['price']:,.4f} | "
                f"Day: {day_str} | Week: {d['weekChg']:+.2f}% | "
                f"52wk: ${d['low52w']:,.2f}--${d['high52w']:,.2f} | "
                f"% of 52w high: {pct:.1f}%"
            )
        else:
            cplines.append(f"  {commodity}: price data unavailable this week")

    return f"""You are the lead analyst at QuantAgri writing "The QuantAgri Intelligence Weekly".
Today is {today_str}. Write a complete institutional newsletter in Markdown.

== ACCURACY RULES — FOLLOW PRECISELY ==
1. PRICES: Use ONLY the exact prices from the tables below. Never fabricate or round differently.
   NOTE: If a Day Change cell shows "n/a", omit that figure from the newsletter or note it as unavailable
   rather than inventing a percentage. This occurs when the data gap between sessions exceeds one trading day.
2. PERCENT OF 52-WEEK HIGH: The % of 52w high is pre-calculated in the tables. Use those exact
   figures. Do not recalculate or round — quote them verbatim (e.g. 99.1%, not 100% if the
   table says 99.1%).
3. NDVI VELOCITY DIRECTION: A POSITIVE velocity (+0.042/16d) means crops are IMPROVING.
   A NEGATIVE velocity (−0.114/16d) means crops are DECLINING. Never label a positive
   velocity as "bearish" or a negative velocity as "bullish" without explicit justification.
4. VELOCITY vs ABSOLUTE NDVI: "Bearish" signals derive from DECLINING velocity (trend),
   not low absolute NDVI. A node with high absolute NDVI but negative velocity is BEARISH
   (momentum turning). Clarify this distinction in deep dives.
5. SUGAR VELOCITY LABELING: If São Paulo shows a positive but decelerating velocity, label
   it explicitly as "positive but decelerating" — not simply "bearish". Bearish label applies
   only when velocity is negative.
6. DATA SOURCE DISCLOSURE: Include a footnote that NDVI velocity and z-scores are computed
   from Planetary Computer Sentinel-2 time series via the QuantAgri internal pipeline and
   may differ from third-party vegetation indices.
7. LENGTH: Minimum 1,200 words across all sections.
8. NORTHERN HEMISPHERE SEASONAL CALENDAR (today = May, early growing season):
   - U.S. CORN (Iowa, Illinois, etc.): May = PLANTING SEASON. Negative NDVI velocity means
     pre-emergent or slow emergence — NOT late-season senescence. Never use "senescence"
     for Northern Hemisphere corn in April–June.
   - U.S. SOYBEANS (Iowa, Illinois): May = PRE-PLANTING to early emergence. Positive NDVI
     velocity means early greening post-planting.
   - U.S. WHEAT (Kansas): May = grain-filling to early ripening. Positive velocity = healthy fill.
   - XINJIANG COTTON (China): Planting April–May, harvest SEPTEMBER–OCTOBER. A negative
     NDVI velocity in May signals slow emergence or poor establishment — NOT harvest-ready
     or post-harvest decline. Never describe May Xinjiang cotton as "harvest-ready."
9. SOUTHERN HEMISPHERE SEASONAL CALENDAR (today = May, post-harvest):
   - BRAZIL CORN (Mato Grosso): May = safrinha (second crop) HARVEST COMPLETION.
     Negative NDVI velocity is expected and bearish.
   - BRAZIL SOYBEANS (Mato Grosso): May = post-harvest decline. Negative velocity is normal.
   - ARGENTINA SOYBEANS (Buenos Aires): May = post-harvest. Positive velocity may indicate
     late-harvest holdovers or cover crops.

== LIVE MARKET DATA (Yahoo Finance, {price_date}) ==

COMMODITY FUTURES (% of 52w high pre-calculated — use verbatim):
{chr(10).join(cplines)}

FUTURES TABLE (reproduce verbatim in newsletter):
{futures_table}

ETF TABLE (reproduce verbatim in newsletter):
{etf_table}

== PLANETARY COMPUTER NDVI SIGNALS ==
(Velocity sign: + = improving vegetation, − = declining vegetation)
{signal_summary}

== NEWSLETTER STRUCTURE ==

# The QuantAgri Intelligence Weekly
## {today_str}

---

**TEASER:** [The single sharpest divergence between satellite signal and current pricing —
be specific: name the commodity, exact price, and velocity figure]

---

## Executive Overview
[Min 150 words. Quote exact prices and % of 52w high. Connect NDVI velocity direction
to price positioning. Where is the market mispriced vs what Sentinel-2 shows?]

## Live Market Snapshot

### Commodity Futures
[Reproduce futures table verbatim. 2-3 sentences on biggest weekly mover.]

### Agricultural ETFs
[Reproduce ETF table verbatim. Note best/worst performer, 52w positioning.
If any ETF is at exactly 100% of 52w high, verify the table says so — if table
shows 99.x%, use that exact figure, not "100%".]

## Commodity Deep Dives

### Soybeans
**Current Price:** [exact from table] | **Weekly Change:** [exact %] | **52w Position:** [exact % of high]
**Spectral Velocity Analysis:** [Iowa/Mato Grosso nodes — state velocity with sign and units e.g. +0.039/16d]
**Signal vs Price Divergence:** [Is the price consistent with what NDVI trend implies?]
**Investor Implications:** [Specific level, target, rationale]

### Corn
**Current Price:** [exact] | **Weekly Change:** [exact %] | **52w Position:** [exact %]
**Spectral Velocity Analysis:** [velocity with sign and units]
**Signal vs Price Divergence:** [analysis]
**Investor Implications:** [detail]

### Wheat
**Current Price:** [exact] | **Weekly Change:** [exact %] | **52w Position:** [exact %]
**Spectral Velocity Analysis:** [velocity with sign and units]
**Signal vs Price Divergence:** [analysis]
**Investor Implications:** [detail]

### Sugar
**Current Price:** [exact] | **Weekly Change:** [exact %] | **52w Position:** [exact %]
**Spectral Velocity Analysis:** [If São Paulo velocity is positive, label as "positive (+X/16d),
decelerating" NOT "bearish". Only use bearish if velocity is negative.]
**Signal vs Price Divergence:** [analysis]
**Investor Implications:** [detail]

### Cotton
**Current Price:** [exact] | **Weekly Change:** [exact %] | **52w Position:** [exact % — use table value, not 100% unless table confirms]
**Spectral Velocity Analysis:** [Xinjiang velocity — if negative, explain this signals declining
crop condition, not just low absolute greenness]
**Signal vs Price Divergence:** [analysis]
**Investor Implications:** [detail]

## ETF Technical Audit
[Each ETF: exact price, exact weekly %, exact % of 52w high from table.
2+ sentences per ETF linking to underlying commodity signal.]

## Spectral Alpha This Week
[Min 150 words. Specific nodes, exact velocity figures with sign, z-scores,
price levels. The core thesis: where does NDVI trend diverge most sharply from price?]

## What to Watch Next Week
- [3-5 bullets: specific price levels, WASDE dates, NDVI inflection points to monitor]

---
*The QuantAgri Intelligence Weekly · {today_str}*
*Prices: Yahoo Finance (live, {price_date}). Spectral data: Planetary Computer Sentinel-2 L2A.*
*NDVI velocity and z-scores computed by QuantAgri internal pipeline from Sentinel-2 time series;*
*figures may differ from third-party vegetation indices.*
*Futures prices: Yahoo Finance continuous front-month (=F) contracts; 52-week ranges span rolled contracts*
*and may differ from specific expiry-contract ranges (e.g., Jul-2026). Not investment advice.*
"""


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
