"""
QuantAgri — Price Fetcher
==========================
Fetches live ETF and commodity futures prices using yfinance
(Yahoo Finance — free, no API key required).

Outputs:
    data/prices/latest.json       ← current prices + weekly change
    data/prices/{YYYY-MM-DD}.json ← daily archive

Runs as Step 1.5 in the nightly GitHub Actions pipeline,
between pc_pipeline.py and generate_signals.py.

Run locally:
    python scripts/fetch_prices.py
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

PRICE_DIR = DATA_DIR / "prices"
PRICE_DIR.mkdir(parents=True, exist_ok=True)

# ── Tickers ───────────────────────────────────────────────────────────
ETF_TICKERS = {
    "CORN":  "Teucrium Corn Fund",
    "SOYB":  "Teucrium Soybean Fund",
    "WEAT":  "Teucrium Wheat Fund",
    "CANE":  "Teucrium Sugar Fund",
    "TAGS":  "Teucrium Agricultural Fund",
    "DBA":   "Invesco DB Agriculture Fund",
}

FUTURES_TICKERS = {
    "ZS=F":  "Soybeans (CBOT)",
    "ZC=F":  "Corn (CBOT)",
    "ZW=F":  "Wheat (CBOT)",
    "SB=F":  "Sugar #11 (ICE)",
    "CT=F":  "Cotton #2 (ICE)",
    "ZL=F":  "Soybean Oil (CBOT)",
    "ZM=F":  "Soybean Meal (CBOT)",
    "KE=F":  "KC HRW Wheat (CBOT)",
}

# Map commodity name → primary futures ticker (for signal injection)
COMMODITY_FUTURES = {
    "Soybeans": "ZS=F",
    "Corn":     "ZC=F",
    "Wheat":    "ZW=F",
    "Sugar":    "SB=F",
    "Cotton":   "CT=F",
}


def fetch_prices() -> dict:
    """
    Fetch 10 days of daily OHLCV for all ETFs and futures.
    Returns structured dict with current price, weekly change, 52w range.
    Falls back gracefully if any ticker fails.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  [WARN] yfinance not installed — pip install yfinance")
        return _empty_prices()

    all_tickers = list(ETF_TICKERS.keys()) + list(FUTURES_TICKERS.keys())
    print(f"  [YF  ] Downloading {len(all_tickers)} tickers...")

    try:
        raw = yf.download(
            all_tickers,
            period="1y",          # 1 year for 52-week range + weekly change
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception as e:
        print(f"  [ERR ] yfinance download failed: {e}")
        return _empty_prices()

    close = raw.get("Close", raw if "Close" not in raw else raw["Close"])
    if close is None or close.empty:
        print("  [WARN] No price data returned")
        return _empty_prices()

    etf_data     = {}
    futures_data = {}
    now          = datetime.now(timezone.utc)

    def parse_ticker(ticker: str, label: str) -> dict | None:
        if ticker not in close.columns:
            return None
        series = close[ticker].dropna()
        if len(series) < 2:
            return None

        current   = float(series.iloc[-1])
        prev_week = float(series.iloc[-6]) if len(series) >= 6 else float(series.iloc[0])
        prev_day  = float(series.iloc[-2])
        week_chg  = ((current - prev_week) / prev_week) * 100
        day_chg   = ((current - prev_day)  / prev_day)  * 100
        high_52w  = float(series.max())
        low_52w   = float(series.min())
        last_date = str(series.index[-1])[:10]

        return {
            "ticker":    ticker,
            "name":      label,
            "price":     round(current, 4),
            "dayChg":    round(day_chg, 2),
            "weekChg":   round(week_chg, 2),
            "high52w":   round(high_52w, 4),
            "low52w":    round(low_52w, 4),
            "pctOf52wH": round((current / high_52w) * 100, 1),
            "lastDate":  last_date,
        }

    for ticker, name in ETF_TICKERS.items():
        result = parse_ticker(ticker, name)
        if result:
            etf_data[ticker] = result
        else:
            print(f"  [SKIP] {ticker} — no data")

    for ticker, name in FUTURES_TICKERS.items():
        result = parse_ticker(ticker, name)
        if result:
            futures_data[ticker] = result
        else:
            print(f"  [SKIP] {ticker} — no data")

    # Commodity summary keyed by name for easy newsletter injection
    commodity_prices = {}
    for commodity, fut_ticker in COMMODITY_FUTURES.items():
        if fut_ticker in futures_data:
            commodity_prices[commodity] = futures_data[fut_ticker]

    return {
        "fetchedAt":       now.isoformat(),
        "date":            now.strftime("%Y-%m-%d"),
        "etfs":            etf_data,
        "futures":         futures_data,
        "commodityPrices": commodity_prices,
    }


def _empty_prices() -> dict:
    """Return a well-structured empty dict so downstream code doesn't crash."""
    now = datetime.now(timezone.utc)
    return {
        "fetchedAt":       now.isoformat(),
        "date":            now.strftime("%Y-%m-%d"),
        "etfs":            {},
        "futures":         {},
        "commodityPrices": {},
        "error":           "Price fetch failed — check yfinance / network",
    }


def format_price_summary(prices: dict) -> str:
    """
    Build a compact, human-readable price summary string
    for injection into the newsletter and podcast prompts.
    """
    lines = []
    now_str = prices.get("date", "unknown date")

    # Commodity futures
    lines.append(f"COMMODITY FUTURES PRICES ({now_str}):")
    futures = prices.get("futures", {})
    if futures:
        for ticker, d in futures.items():
            chg_sym = "▲" if d["weekChg"] > 0 else "▼" if d["weekChg"] < 0 else "→"
            lines.append(
                f"  {ticker:<8} {d['name']:<28} "
                f"${d['price']:>10,.4f}  "
                f"Day: {d['dayChg']:+.2f}%  "
                f"Week: {d['weekChg']:+.2f}% {chg_sym}  "
                f"52wk: ${d['low52w']:,.2f}–${d['high52w']:,.2f} "
                f"({d['pctOf52wH']:.0f}% of high)"
            )
    else:
        lines.append("  [No futures data available]")

    lines.append("")
    lines.append("AGRICULTURAL ETF PRICES:")
    etfs = prices.get("etfs", {})
    if etfs:
        for ticker, d in etfs.items():
            chg_sym = "▲" if d["weekChg"] > 0 else "▼" if d["weekChg"] < 0 else "→"
            lines.append(
                f"  {ticker:<6} {d['name']:<35} "
                f"${d['price']:>8.4f}  "
                f"Day: {d['dayChg']:+.2f}%  "
                f"Week: {d['weekChg']:+.2f}% {chg_sym}  "
                f"52wk: ${d['low52w']:,.2f}–${d['high52w']:,.2f}"
            )
    else:
        lines.append("  [No ETF data available]")

    return "\n".join(lines)


def run():
    today = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")
    print(f"\n[PRICES] {date_str} — fetching live prices\n")

    prices = fetch_prices()

    latest_path = PRICE_DIR / "latest.json"
    daily_path  = PRICE_DIR / f"{date_str}.json"

    latest_path.write_text(json.dumps(prices, indent=2))
    daily_path.write_text(json.dumps(prices, indent=2))

    etf_count     = len(prices.get("etfs", {}))
    futures_count = len(prices.get("futures", {}))
    print(f"\n[PRICES] {etf_count} ETFs + {futures_count} futures written → {latest_path}\n")

    # Print summary
    if etf_count > 0 or futures_count > 0:
        print(format_price_summary(prices))


if __name__ == "__main__":
    run()
