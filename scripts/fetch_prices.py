"""
QuantAgri — Price Fetcher
Fetches live ETF + futures prices via yfinance (free, no API key).
Output: data/prices/latest.json + data/prices/{YYYY-MM-DD}.json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

PRICE_DIR = DATA_DIR / "prices"
PRICE_DIR.mkdir(parents=True, exist_ok=True)

ETF_TICKERS = {
    "CORN": "Teucrium Corn Fund",
    "SOYB": "Teucrium Soybean Fund",
    "WEAT": "Teucrium Wheat Fund",
    "CANE": "Teucrium Sugar Fund",
    "TAGS": "Teucrium Agricultural Fund",
    "DBA":  "Invesco DB Agriculture Fund",
}

FUTURES_TICKERS = {
    "ZS=F": "Soybeans (CBOT)",
    "ZC=F": "Corn (CBOT)",
    "ZW=F": "Wheat (CBOT)",
    "SB=F": "Sugar #11 (ICE)",
    "CT=F": "Cotton #2 (ICE)",
    "ZL=F": "Soybean Oil (CBOT)",
    "ZM=F": "Soybean Meal (CBOT)",
    "KE=F": "KC HRW Wheat (CBOT)",
}

COMMODITY_FUTURES = {
    "Soybeans": "ZS=F",
    "Corn":     "ZC=F",
    "Wheat":    "ZW=F",
    "Sugar":    "SB=F",
    "Cotton":   "CT=F",
}


def _empty_prices() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "fetchedAt": now.isoformat(), "date": now.strftime("%Y-%m-%d"),
        "etfs": {}, "futures": {}, "commodityPrices": {},
        "error": "Price fetch failed — check yfinance / network",
    }


def fetch_prices() -> dict:
    try:
        import yfinance as yf
    except ImportError:
        print("  [WARN] yfinance not installed — pip install yfinance")
        return _empty_prices()

    all_tickers = list(ETF_TICKERS.keys()) + list(FUTURES_TICKERS.keys())
    print(f"  [YF  ] Downloading {len(all_tickers)} tickers...")

    try:
        raw = yf.download(all_tickers, period="1y", interval="1d",
                          progress=False, auto_adjust=True, threads=True)
    except Exception as e:
        print(f"  [ERR ] yfinance download failed: {e}")
        return _empty_prices()

    close = raw.get("Close", raw if "Close" not in raw else raw["Close"])
    if close is None or close.empty:
        print("  [WARN] No price data returned")
        return _empty_prices()

    now = datetime.now(timezone.utc)
    etf_data, futures_data = {}, {}

    def parse_ticker(ticker, label):
        if ticker not in close.columns:
            return None
        series = close[ticker].dropna()
        if len(series) < 2:
            return None
        current   = float(series.iloc[-1])
        prev_week = float(series.iloc[-6]) if len(series) >= 6 else float(series.iloc[0])
        prev_day  = float(series.iloc[-2])
        return {
            "ticker":    ticker,
            "name":      label,
            "price":     round(current, 4),
            "dayChg":    round(((current - prev_day)  / prev_day)  * 100, 2),
            "weekChg":   round(((current - prev_week) / prev_week) * 100, 2),
            "high52w":   round(float(series.max()), 4),
            "low52w":    round(float(series.min()), 4),
            "pctOf52wH": round((current / float(series.max())) * 100, 1),
            "lastDate":  str(series.index[-1])[:10],
        }

    for ticker, name in ETF_TICKERS.items():
        r = parse_ticker(ticker, name)
        if r:
            etf_data[ticker] = r
        else:
            print(f"  [SKIP] {ticker} — no data")

    for ticker, name in FUTURES_TICKERS.items():
        r = parse_ticker(ticker, name)
        if r:
            futures_data[ticker] = r
        else:
            print(f"  [SKIP] {ticker} — no data")

    commodity_prices = {
        c: futures_data[t]
        for c, t in COMMODITY_FUTURES.items()
        if t in futures_data
    }

    return {
        "fetchedAt": now.isoformat(), "date": now.strftime("%Y-%m-%d"),
        "etfs": etf_data, "futures": futures_data,
        "commodityPrices": commodity_prices,
    }


def format_price_summary(prices: dict) -> str:
    lines = [f"COMMODITY FUTURES PRICES ({prices.get('date','?')}):"]
    futures = prices.get("futures", {})
    if futures:
        for ticker, d in futures.items():
            sym = "▲" if d["weekChg"] > 0 else "▼" if d["weekChg"] < 0 else "→"
            lines.ap
