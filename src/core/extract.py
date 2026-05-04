"""
core/extract.py — shared SerpAPI Google News fetch + regex pre-filter.
Each wire passes its own queries and exclusion patterns.

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import re
import time
import logging
import requests
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fetch_serpapi(query: str, api_key: str, lookback_days: int = 1) -> List[dict]:
    """Hit SerpAPI Google News endpoint and return raw article dicts."""
    params = {
        "engine": "google_news",
        "q": query,
        "api_key": api_key,
        "num": 100,
        "tbs": "qdr:d{}".format(lookback_days),
    }
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        results = data.get("news_results", [])
        logger.debug("SerpAPI returned %d results for: %s", len(results), query[:80])
        return results
    except requests.exceptions.HTTPError as e:
        logger.error("SerpAPI HTTP error %s for query '%s': %s",
                     e.response.status_code if e.response else "?", query, e)
        return []
    except requests.exceptions.Timeout:
        logger.error("SerpAPI timeout for query '%s'", query)
        return []
    except Exception as e:
        logger.error("SerpAPI unexpected error for query '%s': %s", query, e)
        return []


def _deduplicate(articles: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for a in articles:
        uid = a.get("link", "") or a.get("title", "")
        if uid and uid not in seen:
            seen.add(uid)
            out.append(a)
    return out


def _apply_exclusions(articles: List[dict], exclusion_patterns: List[str]) -> List[dict]:
    """Drop articles whose title or snippet matches any exclusion regex."""
    if not exclusion_patterns:
        return articles
    compiled = [re.compile(p, re.IGNORECASE) for p in exclusion_patterns]
    out = []
    dropped = 0
    for a in articles:
        text = "{} {}".format(a.get("title", ""), a.get("snippet", ""))
        if any(p.search(text) for p in compiled):
            logger.debug("Exclusion dropped: %s", a.get("title", "")[:80])
            dropped += 1
        else:
            out.append(a)
    if dropped:
        logger.debug("Exclusion filter dropped %d articles", dropped)
    return out


def _normalise(raw: List[dict], wire: str) -> List[dict]:
    """Flatten SerpAPI article dict into our standard shape."""
    now = datetime.now(timezone.utc).isoformat()
    results = []
    for a in raw:
        source = a.get("source", {})
        source_name = source.get("name", "") if isinstance(source, dict) else str(source)
        results.append({
            "article_id":   a.get("link", ""),
            "title":        a.get("title", ""),
            "snippet":      a.get("snippet", ""),
            "url":          a.get("link", ""),
            "source":       source_name,
            "published_at": a.get("date", ""),
            "wire":         wire,
            "fetched_at":   now,
        })
    return results


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def fetch_articles(
    queries: List[str],
    api_key: str,
    wire: str,
    lookback_days: int = 1,
    exclusion_patterns: Optional[List[str]] = None,
    rate_limit_sec: float = 1.0,
) -> List[dict]:
    """
    Fetch news articles for a wire.

    Parameters
    ----------
    queries           : list of SerpAPI query strings (2 per wire recommended)
    api_key           : SerpAPI key
    wire              : wire name used to tag output rows
    lookback_days     : how many days back to search
    exclusion_patterns: list of regex strings to drop irrelevant articles
    rate_limit_sec    : pause between SerpAPI calls
    """
    exclusion_patterns = exclusion_patterns or []
    raw = []
    for q in queries:
        logger.info("[%s] fetching: %s", wire, q[:100])
        results = _fetch_serpapi(q, api_key, lookback_days)
        raw.extend(results)
        if len(queries) > 1:
            time.sleep(rate_limit_sec)

    before_dedup = len(raw)
    raw = _deduplicate(raw)
    logger.debug("[%s] dedup: %d → %d", wire, before_dedup, len(raw))

    raw = _apply_exclusions(raw, exclusion_patterns)
    articles = _normalise(raw, wire)
    logger.info("[%s] %d articles after fetch + dedup + exclusions", wire, len(articles))
    return articles
