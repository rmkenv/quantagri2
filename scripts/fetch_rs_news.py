"""
QuantAgri — Remote Sensing News Fetcher
========================================
Pulls articles from curated RSS feeds and the free GNews API
covering remote sensing use cases in:
  agriculture, flooding, drought, wildfires,
  invasive species, and pesticide/herbicide drift & control.

Outputs:
    data/rs_news/latest.json          <- structured article list
    data/rs_news/{YYYY-MM-DD}.json    <- daily archive

No API key required for RSS feeds.
GNews API: free tier at gnews.io (100 requests/day, no card needed).

Run:
    python scripts/fetch_rs_news.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

RS_NEWS_DIR = DATA_DIR / "rs_news"
RS_NEWS_DIR.mkdir(parents=True, exist_ok=True)

MAX_ARTICLES_PER_FEED = 8    # cap per feed to stay within token budget
MAX_AGE_DAYS          = 8    # only keep articles from the last 8 days
REQUEST_TIMEOUT       = 15
REQUEST_DELAY         = 1.0  # seconds between feed requests (polite)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; QuantAgri-NewsBot/1.0; "
        "+https://github.com/rmkenv/quantagri)"
    )
}

# ── RSS Feed Catalogue ────────────────────────────────────────────────
# Each entry: (category, source_name, url)
# All free, no auth required. Verified active as of May 2026.

RSS_FEEDS = [
    # ── Remote Sensing Science & Applications ──
    ("remote_sensing", "NASA Earth Observatory",
     "https://earthobservatory.nasa.gov/feeds/earth-observatory.rss"),

    ("remote_sensing", "NASA LP DAAC (Land Processes)",
     "https://lpdaac.usgs.gov/news_feed/"),

    ("remote_sensing", "ESA Earth Observation News",
     "https://www.esa.int/rssfeed/Our_Activities/Observing_the_Earth"),

    ("remote_sensing", "MDPI Remote Sensing Journal",
     "https://www.mdpi.com/rss/journal/remotesensing"),

    ("remote_sensing", "GIS Geography",
     "https://gisgeography.com/feed/"),

    ("remote_sensing", "EOS Data Analytics Blog",
     "https://eos.com/blog-tags/remote-sensing/feed/"),

    ("remote_sensing", "Copernicus / Sentinel Hub Blog",
     "https://www.sentinel-hub.com/blog/feed/"),

    # ── Agriculture & Precision Farming ──
    ("agriculture", "AgFunder News",
     "https://agfundernews.com/feed"),

    ("agriculture", "Precision Agriculture Today (AgWeb)",
     "https://www.agweb.com/feed/articles"),

    ("agriculture", "USDA Agricultural Research Service",
     "https://www.ars.usda.gov/news-events/news/rss/"),

    ("agriculture", "Farmonaut Remote Sensing Blog",
     "https://farmonaut.com/blogs/feed/"),

    # ── Flooding & Water ──
    ("flooding", "USGS Water Resources News",
     "https://www.usgs.gov/news/all/feed"),

    ("flooding", "FloodList",
     "https://floodlist.com/feed"),

    ("flooding", "NOAA National Water Center",
     "https://water.noaa.gov/rss/current_conditions.rss"),

    ("flooding", "Copernicus EMS (Emergency Management)",
     "https://emergency.copernicus.eu/mapping/ems-feeds"),

    # ── Freshwater & Aquifers ──
    ("freshwater", "USGS Groundwater Watch",
     "https://groundwaterwatch.usgs.gov/rss/gww_rss.xml"),

    ("freshwater", "USGS Water Science News",
     "https://www.usgs.gov/centers/water-resources/news/feed"),

    ("freshwater", "NASA GRACE Groundwater (JPL Water)",
     "https://grace.jpl.nasa.gov/news/rss/"),

    ("freshwater", "International Groundwater Resources Assessment Centre",
     "https://www.igrac.net/feed/"),

    ("freshwater", "Water Research Foundation News",
     "https://www.waterrf.org/news/feed"),

    ("freshwater", "Circle of Blue (Global Water News)",
     "https://www.circleofblue.org/feed/"),

    ("freshwater", "Global Water Forum",
     "https://globalwaterforum.org/feed/"),

    ("freshwater", "UN Water News",
     "https://www.unwater.org/news/rss"),

    # ── Drought ──
    ("drought", "NOAA Drought Monitor",
     "https://droughtmonitor.unl.edu/rss/dm_rss.xml"),

    ("drought", "USDA Drought News",
     "https://www.drought.gov/news/feed"),

    # ── Wildfires ──
    ("wildfire", "NASA FIRMS (Fire Info RSS)",
     "https://firms.modaps.eosdis.nasa.gov/rss/"),

    ("wildfire", "NIFC Wildfire News",
     "https://www.nifc.gov/nicc/sitreport/feed.xml"),

    ("wildfire", "InciWeb (Active Incidents)",
     "https://inciweb.nwcg.gov/feeds/rss/incidents/"),

    ("wildfire", "USFS Pacific Northwest Station",
     "https://www.fs.usda.gov/outernet/pnw/RSS/pnw_news.xml"),

    # ── Invasive Species ──
    ("invasive_species", "USDA APHIS Invasive Species",
     "https://www.aphis.usda.gov/rss/invasive-species.xml"),

    ("invasive_species", "Early Detection & Distribution Mapping (EDDMapS)",
     "https://www.eddmaps.org/rss/"),

    ("invasive_species", "IUCN Invasive Species Specialist Group",
     "https://www.iucngisd.org/gisd/rss.php"),

    # ── Pesticide / Herbicide Drift & Control ──
    ("pesticide_herbicide", "EPA Pesticide News",
     "https://www.epa.gov/rss/epa-pesticides-news.xml"),

    ("pesticide_herbicide", "USDA Agricultural Research - Pesticides",
     "https://www.ars.usda.gov/news-events/news/rss/?topic=pesticides"),

    ("pesticide_herbicide", "Weed Science Society of America",
     "https://wssa.net/feed/"),

    ("pesticide_herbicide", "CropLife Media",
     "https://www.croplife.com/feed/"),
]

# ── GNews API queries (free: gnews.io, 100 req/day) ──────────────────
# Sign up free at https://gnews.io — no credit card
GNEWS_QUERIES = [
    "remote sensing agriculture satellite",
    "NDVI crop monitoring satellite imagery",
    "flood mapping satellite Sentinel",
    "drought remote sensing MODIS",
    "wildfire satellite detection VIIRS",
    "invasive species satellite detection",
    "herbicide drift satellite monitoring",
    "precision agriculture earth observation",
    "groundwater depletion satellite GRACE",
    "aquifer monitoring remote sensing",
    "freshwater availability satellite imagery",
]


# ── RSS Parser ────────────────────────────────────────────────────────
def parse_rss_feed(category: str, source: str, url: str) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of article dicts."""
    try:
        import feedparser
    except ImportError:
        print("  [WARN] feedparser not installed — pip install feedparser")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"  [SKIP] {source}: {e}")
        return []

    articles = []
    for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
        # Parse published date
        pub_date = None
        for attr in ("published_parsed", "updated_parsed"):
            if hasattr(entry, attr) and getattr(entry, attr):
                try:
                    pub_date = datetime(*getattr(entry, attr)[:6], tzinfo=timezone.utc)
                    break
                except Exception:
                    pass

        # Skip old articles
        if pub_date and pub_date < cutoff:
            continue

        # Clean summary
        summary = getattr(entry, "summary", "") or ""
        # Strip basic HTML tags
        import re
        summary = re.sub(r"<[^>]+>", " ", summary).strip()
        summary = re.sub(r"\s+", " ", summary)[:400]

        articles.append({
            "category":  category,
            "source":    source,
            "title":     getattr(entry, "title", ""),
            "url":       getattr(entry, "link",  ""),
            "summary":   summary,
            "published": pub_date.isoformat() if pub_date else None,
        })

    return articles


# ── GNews API ─────────────────────────────────────────────────────────
def fetch_gnews(queries: list[str], api_key: str) -> list[dict]:
    """Fetch articles from GNews API for a list of queries."""
    articles = []
    seen_urls = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    for query in queries[:4]:  # cap at 4 queries to preserve daily quota
        try:
            resp = requests.get(
                "https://gnews.io/api/v4/search",
                params={
                    "q":        query,
                    "token":    api_key,
                    "lang":     "en",
                    "max":      5,
                    "sortby":   "publishedAt",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            for art in data.get("articles", []):
                url = art.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Parse date
                pub_str = art.get("publishedAt", "")
                pub_date = None
                try:
                    pub_date = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pass

                if pub_date and pub_date < cutoff:
                    continue

                articles.append({
                    "category":  "gnews",
                    "source":    art.get("source", {}).get("name", "GNews"),
                    "title":     art.get("title", ""),
                    "url":       url,
                    "summary":   art.get("description", "")[:400],
                    "published": pub_date.isoformat() if pub_date else pub_str,
                    "query":     query,
                })

            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"  [GNEWS ERR] query='{query}': {e}")

    return articles


# ── Format for newsletter prompt ──────────────────────────────────────
def format_news_for_prompt(articles: list[dict], max_per_category: int = 4) -> str:
    """Build a compact, structured summary for LLM injection."""
    if not articles:
        return "No recent remote sensing news articles retrieved this week."

    # Group by category
    by_cat: dict[str, list] = {}
    for a in articles:
        by_cat.setdefault(a["category"], []).append(a)

    category_labels = {
        "remote_sensing":     "REMOTE SENSING SCIENCE & APPLICATIONS",
        "agriculture":        "AGRICULTURE & PRECISION FARMING",
        "flooding":           "FLOOD MONITORING & MAPPING",
        "freshwater":         "FRESHWATER AVAILABILITY & AQUIFERS",
        "drought":            "DROUGHT MONITORING",
        "wildfire":           "WILDFIRE DETECTION & RESPONSE",
        "invasive_species":   "INVASIVE SPECIES DETECTION",
        "pesticide_herbicide":"PESTICIDE, HERBICIDE & CROP PROTECTION",
        "gnews":              "GENERAL EARTH OBSERVATION NEWS",
    }

    lines = []
    for cat, label in category_labels.items():
        arts = by_cat.get(cat, [])
        if not arts:
            continue
        lines.append(f"\n### {label}")
        for a in arts[:max_per_category]:
            pub = a.get("published", "")[:10] if a.get("published") else "recent"
            lines.append(
                f"- [{pub}] **{a['title']}** ({a['source']})\n"
                f"  {a['summary'][:200]}\n"
                f"  URL: {a['url']}"
            )

    return "\n".join(lines) if lines else "No categorised articles available."


# ── Main ──────────────────────────────────────────────────────────────
def run() -> dict:
    today    = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")
    print(f"\n[RS NEWS] {date_str} — fetching remote sensing news\n")

    all_articles: list[dict] = []

    # ── RSS feeds ─────────────────────────────────────────────────────
    for category, source, url in RSS_FEEDS:
        arts = parse_rss_feed(category, source, url)
        if arts:
            print(f"  [RSS ] {source}: {len(arts)} articles")
            all_articles.extend(arts)
        time.sleep(REQUEST_DELAY)

    # ── GNews API (optional — only if key provided) ───────────────────
    gnews_key = os.getenv("GNEWS_API_KEY", "")
    if gnews_key:
        print(f"\n  [GNWS] Fetching {len(GNEWS_QUERIES)} GNews queries...")
        gnews_arts = fetch_gnews(GNEWS_QUERIES, gnews_key)
        all_articles.extend(gnews_arts)
        print(f"  [GNWS] {len(gnews_arts)} articles from GNews")
    else:
        print("  [INFO] No GNEWS_API_KEY set — skipping GNews (RSS feeds sufficient)")

    # ── Write outputs ─────────────────────────────────────────────────
    output = {
        "fetchedAt":    today.isoformat(),
        "date":         date_str,
        "articleCount": len(all_articles),
        "articles":     all_articles,
    }

    (RS_NEWS_DIR / "latest.json").write_text(json.dumps(output, indent=2))
    (RS_NEWS_DIR / f"{date_str}.json").write_text(json.dumps(output, indent=2))

    print(f"\n[RS NEWS] {len(all_articles)} total articles → {RS_NEWS_DIR}/latest.json\n")
    return output


if __name__ == "__main__":
    run()
