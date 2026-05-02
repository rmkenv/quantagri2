"""
QuantAgri — Monthly Podcast Script Generator
=============================================
Loads ALL weekly newsletters from the target month, summarises them,
combines with monthly signal aggregates and live prices, then generates
a professional single-host podcast script via Ollama Cloud.

The podcast is explicitly a RECAP of what the newsletters covered —
key calls made, what played out, what surprised, and the outlook.

Output:
    data/podcast/{YYYY-MM}.md
    data/podcast/latest.md

Schedule: 1st of each month 07:30 UTC (after newsletter has run)
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import SIG_DIR, POD_DIR, NEWS_DIR, COMMODITIES
from ollama_client import chat
from fetch_prices import PRICE_DIR, format_price_summary


# ── Load monthly newsletters ──────────────────────────────────────────
def load_monthly_newsletters(year: int, month: int) -> list[dict]:
    """
    Load all weekly newsletter .md files from the target month.
    Returns list of dicts: {date, content, word_count}
    """
    newsletters = []
    for path in sorted(NEWS_DIR.glob("*.md")):
        if path.name == "latest.md":
            continue
        try:
            date = datetime.strptime(path.stem, "%Y-%m-%d")
            if date.year == year and date.month == month:
                content = path.read_text().strip()
                newsletters.append({
                    "date":       path.stem,
                    "content":    content,
                    "word_count": len(content.split()),
                })
        except ValueError:
            continue
    return newsletters


def summarise_newsletters(newsletters: list[dict]) -> str:
    """
    Build a structured summary of the month's newsletters for injection
    into the podcast prompt. Truncates each to stay within token budget.
    """
    if not newsletters:
        return "No newsletter issues found for this month."

    lines = [f"NEWSLETTERS PUBLISHED THIS MONTH: {len(newsletters)} issues\n"]

    for i, nl in enumerate(newsletters, 1):
        lines.append(f"--- ISSUE {i}: {nl['date']} ({nl['word_count']} words) ---")
        # Take the first 1,200 chars of each newsletter — enough to capture
        # the teaser, executive overview, and key commodity calls
        excerpt = nl["content"][:1200]
        # If truncated, note it
        if len(nl["content"]) > 1200:
            excerpt += f"\n[... truncated — {nl['word_count']} words total]"
        lines.append(excerpt)
        lines.append("")

    return "\n".join(lines)


# ── Load monthly signals ──────────────────────────────────────────────
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


def aggregate_monthly_signals(signals: list[dict]) -> str:
    if not signals:
        return "No signal data available for this month."
    by_commodity: dict[str, list] = {}
    for s in signals:
        by_commodity.setdefault(s.get("commodity", "Unknown"), []).append(s)
    lines = []
    for commodity, sigs in by_commodity.items():
        sentiments  = [s.get("sentiment") for s in sigs]
        avg_conf    = sum(s.get("confidence", 0) for s in sigs) / len(sigs)
        peak_ndvis  = [s.get("peakNdvi") for s in sigs if s.get("peakNdvi")]
        avg_ndvi    = round(sum(peak_ndvis) / len(peak_ndvis), 3) if peak_ndvis else "N/A"
        velocities  = [s.get("spectralVelocity") for s in sigs if s.get("spectralVelocity")]
        regimes     = list({s.get("macroRegime", "") for s in sigs if s.get("macroRegime")})
        lines.append(
            f"### {commodity}\n"
            f"- Signal dist: {sentiments.count('Bullish')}B / {sentiments.count('Bearish')}Br / {sentiments.count('Neutral')}N\n"
            f"- Avg confidence: {avg_conf:.0%} | Avg peak NDVI: {avg_ndvi}\n"
            f"- Velocities seen: {', '.join(velocities[:4]) or 'N/A'}\n"
            f"- Macro regimes: {', '.join(regimes[:3]) or 'N/A'}\n"
            f"- Final rationale: {sigs[-1].get('rationale', 'N/A')[:200]}"
        )
    return "\n\n".join(lines)


# ── Build prompt ──────────────────────────────────────────────────────
def build_podcast_prompt(
    month_name: str,
    year: int,
    newsletter_summary: str,
    signal_summary: str,
    prices: dict,
) -> str:
    price_date = prices.get("date", "unknown")
    cp         = prices.get("commodityPrices", {})

    cplines = []
    for commodity in COMMODITIES:
        if commodity in cp:
            d = cp[commodity]
            pct = round((d['price'] / d['high52w']) * 100, 1) if d.get('high52w') else 0
            cplines.append(
                f"  {commodity}: {d['ticker']} ${d['price']:,.4f} | "
                f"Week: {d['weekChg']:+.2f}% | "
                f"52wk: ${d['low52w']:,.2f}--${d['high52w']:,.2f} | "
                f"{pct:.1f}% of 52w high"
            )
        else:
            cplines.append(f"  {commodity}: price data unavailable")

    return f"""You are the host of "Spectral Alpha" — QuantAgri's monthly agricultural markets podcast.
This episode recaps {month_name} {year}.

YOUR PRIMARY SOURCE MATERIAL is the weekly newsletters published during {month_name} —
these are what your listeners read each Monday. The podcast is your monthly audio debrief:
what did the newsletters call, what played out, what surprised, and where do we go next.

CRITICAL RULES:
1. Reference the newsletters specifically and directly — mention what was said in specific issues
2. Use ONLY the real prices provided — never fabricate
3. Velocity sign: + = improving crops, − = declining crops
4. TONE: "The Daily" meets "Bloomberg Surveillance" — institutional, narrative-driven
5. LENGTH: 900-1,200 words of continuous spoken prose — no bullet points, no stage directions

== WEEKLY NEWSLETTERS FROM {month_name.upper()} {year} ==
(These are your source material — recap what they said)

{newsletter_summary}

== MONTHLY NDVI SIGNAL AGGREGATES (Planetary Computer Sentinel-2) ==
{signal_summary}

== CURRENT MARKET PRICES (Yahoo Finance, {price_date}) ==
{chr(10).join(cplines)}

{format_price_summary(prices)}

== PODCAST SCRIPT STRUCTURE ==

## THE HOOK
Open by referencing the most striking call the newsletters made this month —
name the specific issue date, the commodity, and what the signal said vs what
the market was doing. Was the newsletter right?

## {month_name.upper()} IN REVIEW — WHAT THE NEWSLETTERS SAID
Walk through each weekly issue chronologically. For each one:
- What was the lead call (commodity, direction, spectral velocity figure)?
- What price level was flagged?
- Did the market move in that direction by the next issue?
Be specific — quote the newsletter dates and their exact calls.

## SIGNAL SCORECARD
Which calls from the month's newsletters were confirmed by subsequent price action?
Which were early, wrong, or still open? Be honest — credibility comes from accountability.

## THE MACRO PICTURE
How did {month_name}'s NDVI signals fit into the broader supply/demand narrative?
La Nina/El Nino regime, WASDE context, basis levels. Reference specific price levels.

## SPECTRAL ALPHA
The month's sharpest satellite-to-price divergence — name the node, the velocity,
the z-score, and what price did relative to what Sentinel-2 implied.

## THE OUTLOOK
3-4 specific things to watch next month. Reference current price levels and
which NDVI nodes are entering key phenological windows.

---
*QuantAgri Spectral Alpha · {month_name} {year}*
*Source: QuantAgri Intelligence Weekly issues. Prices: Yahoo Finance ({price_date}).*
*Spectral data: Planetary Computer Sentinel-2 L2A. Not investment advice.*
"""


# ── Main ──────────────────────────────────────────────────────────────
def run():
    today  = datetime.now(timezone.utc)

    # On the 1st, recap last month. Otherwise recap current month.
    if today.day == 1:
        last_month   = today.replace(day=1) - timedelta(days=1)
        target_year  = last_month.year
        target_month = last_month.month
    else:
        target_year  = today.year
        target_month = today.month

    month_name = datetime(target_year, target_month, 1).strftime("%B")
    month_str  = f"{target_year}-{target_month:02d}"

    print(f"\n[PODCAST] {month_name} {target_year}\n")

    # ── Load newsletters ──────────────────────────────────────────────
    newsletters = load_monthly_newsletters(target_year, target_month)
    if newsletters:
        print(f"  [NEWS] {len(newsletters)} newsletters loaded for {month_name}")
        for nl in newsletters:
            print(f"         {nl['date']} — {nl['word_count']} words")
    else:
        print(f"  [WARN] No newsletters found for {month_name} — "
              f"podcast will rely on signal data only")

    # ── Load signals ──────────────────────────────────────────────────
    signals = load_monthly_signals(target_year, target_month)
    if not signals:
        latest = SIG_DIR / "latest.json"
        if latest.exists():
            signals = json.loads(latest.read_text()).get("signals", [])
            print(f"  [FALL] No archived signals — using latest.json ({len(signals)} signals)")
    else:
        print(f"  [SIG ] {len(signals)} signal records for {month_name}")

    # ── Load prices ───────────────────────────────────────────────────
    prices = load_latest_prices()
    print(f"  [PX  ] {len(prices.get('etfs',{}))} ETFs + "
          f"{len(prices.get('futures',{}))} futures ({prices.get('date','?')})")

    # ── Build prompt and call LLM ─────────────────────────────────────
    newsletter_summary = summarise_newsletters(newsletters)
    signal_summary     = aggregate_monthly_signals(signals)
    prompt             = build_podcast_prompt(
        month_name, target_year,
        newsletter_summary, signal_summary, prices,
    )

    print(f"  [LLM ] {len(prompt):,} char prompt — calling Ollama Cloud...")
    script = chat(prompt, as_json=False, temperature=0.5)

    # ── Write outputs ─────────────────────────────────────────────────
    out_path    = POD_DIR / f"{month_str}.md"
    latest_path = POD_DIR / "latest.md"
    out_path.write_text(script)
    latest_path.write_text(script)

    print(f"  [OUT ] {out_path}")
    print(f"  [OUT ] {latest_path}")
    print(f"\n[PODCAST] Done — {len(script):,} chars\n")


if __name__ == "__main__":
    run()
