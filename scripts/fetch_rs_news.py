"""
QuantAgri — Remote Sensing News Fetcher
========================================
Pulls articles from two tiers of sources:

TIER 1 — Google News RSS (primary, always reliable)
  Topic-specific search queries via news.google.com/rss/search
  No auth needed. Works in GitHub Actions. Always fresh.

TIER 2 — Specialist RSS feeds (supplementary)
  Domain-specific sources: NASA, ESA, FloodList, InciWeb etc.
  May occasionally return empty if behind CDN protection.

TIER 3 — GNews API (optional)
  Set GNEWS_API_KEY secret for 100 free req/day from gnews.io

Output:
    data/rs_news/latest.json
    data/rs_news/{YYYY-MM-DD}.json
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR

RS_NEWS_DIR = DATA_DIR / "rs_news"
RS_NEWS_DIR.mkdir(parents=True, exist_ok=True)

MAX_AGE_DAYS          = 8
MAX_ARTICLES_PER_FEED = 6
REQUEST_TIMEOUT       = 20
REQUEST_DELAY         = 0.8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── TIER 1: Google News RSS (primary — always works) ─────────────────
# Uses news.google.com/rss/search — free, no auth, always fresh
GOOGLE_NEWS_FEEDS = [
    ("remote_sensing", "Google News: Remote Sensing",
     "https://news.google.com/rss/search?q=remote+sensing+satellite+agriculture+earth+observation&hl=en-US&gl=US&ceid=US:en"),

    ("agriculture", "Google News: Precision Agriculture Satellite",
     "https://news.google.com/rss/search?q=precision+agriculture+satellite+imagery+NDVI+crop+monitoring&hl=en-US&gl=US&ceid=US:en"),

    ("agriculture", "Google News: Crop Monitoring",
     "https://news.google.com/rss/search?q=satellite+crop+monitoring+yield+forecast+Sentinel&hl=en-US&gl=US&ceid=US:en"),

    ("flooding", "Google News: Flood Satellite",
     "https://news.google.com/rss/search?q=flood+satellite+mapping+SAR+Sentinel+monitoring&hl=en-US&gl=US&ceid=US:en"),

    ("freshwater", "Google News: Groundwater Aquifer",
     "https://news.google.com/rss/search?q=groundwater+aquifer+depletion+GRACE+satellite+freshwater&hl=en-US&gl=US&ceid=US:en"),

    ("freshwater", "Google News: Water Scarcity",
     "https://news.google.com/rss/search?q=water+scarcity+aquifer+satellite+monitoring+drought&hl=en-US&gl=US&ceid=US:en"),

    ("drought", "Google News: Drought Satellite",
     "https://news.google.com/rss/search?q=drought+satellite+monitoring+NDVI+soil+moisture&hl=en-US&gl=US&ceid=US:en"),

    ("wildfire", "Google News: Wildfire Satellite",
     "https://news.google.com/rss/search?q=wildfire+satellite+detection+VIIRS+MODIS+burn+mapping&hl=en-US&gl=US&ceid=US:en"),

    ("invasive_species", "Google News: Invasive Species Remote Sensing",
     "https://news.google.com/rss/search?q=invasive+species+satellite+remote+sensing+detection&hl=en-US&gl=US&ceid=US:en"),

    ("pesticide_herbicide", "Google News: Pesticide Herbicide",
     "https://news.google.com/rss/search?q=pesticide+herbicide+drift+monitoring+satellite+agriculture&hl=en-US&gl=US&ceid=US:en"),

    ("remote_sensing", "Google News: Earth Observation New",
     "https://news.google.com/rss/search?q=earth+observation+satellite+launch+Copernicus+ESA+NASA&hl=en-US&gl=US&ceid=US:en"),
]

# ── TIER 2: Specialist RSS feeds (supplementary) ─────────────────────
SPECIALIST_FEEDS = [
    # Remote sensing
    ("remote_sensing", "NASA Earth Observatory",
     "https://earthobservatory.nasa.gov/feeds/earth-observatory.rss"),
    ("remote_sensing", "ESA Earth Observation",
     "https://www.esa.int/rssfeed/Our_Activities/Observing_the_Earth"),
    ("remote_sensing", "MDPI Remote Sensing Journal",
     "https://www.mdpi.com/rss/journal/remotesensing"),
    ("remote_sensing", "GIS Geography",
     "https://gisgeography.com/feed/"),
    # Agriculture
    ("agriculture", "AgFunder News",
     "https://agfundernews.com/feed"),
    ("agriculture", "USDA ARS News",
     "https://www.ars.usda.gov/news-events/news/rss/"),
    # Flooding
    ("flooding", "FloodList",
     "https://floodlist.com/feed"),
    ("flooding", "NOAA Water Center",
     "https://water.noaa.gov/rss/current_conditions.rss"),
    # Freshwater
    ("freshwater", "Circle of Blue",
     "https://www.circleofblue.org/feed/"),
    ("freshwater", "Global Water Forum",
     "https://globalwaterforum.org/feed/"),
    ("freshwater", "UN Water",
     "https://www.unwater.org/news/rss"),
    # Drought
    ("drought", "NOAA Drought Monitor",
     "https://droughtmonitor.unl.edu/rss/dm_rss.xml"),
    # Wildfire
    ("wildfire", "InciWeb Active Incidents",
     "https://inciweb.nwcg.gov/feeds/rss/incidents/"),
    ("wildfire", "NIFC Wildfire News",
     "https://www.nifc.gov/nicc/sitreport/feed.xml"),
    # Invasive species
    ("invasive_species", "USDA APHIS",
     "https://www.aphis.usda.gov/rss/invasive-species.xml"),
    # Pesticide
    ("pesticide_herbicide", "EPA Pesticides",
     "https://www.epa.gov/rss/epa-pesticides-news.xml"),
    ("pesticide_herbicide", "CropLife",
     "https://www.croplife.com/feed/"),
]

# ── GNews API queries ─────────────────────────────────────────────────
GNEWS_QUERIES = [
    "remote sensing agriculture satellite",
    "NDVI crop monitoring satellite",
    "flood mapping SAR Sentinel",
    "drought satellite NDVI monitoring",
    "wildfire detection VIIRS satellite",
    "invasive species satellite detection",
    "herbicide pesticide drift monitoring",
    "groundwater depletion GRACE satellite",
    "aquifer freshwater satellite monitoring",
]


# ── Parser ────────────────────────────────────────────────────────────
def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;",  "<", text)
    text = re.sub(r"&gt;",  ">", text)
    text = re.sub(r"&quot;","\"", text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\s+",   " ", text)
    return text.strip()


def _parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def parse_feed(category: str, source: str, url: str) -> list[dict]:
    try:
        import feedparser
    except ImportError:
        print("  [WARN] feedparser not installed")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        if resp.status_code != 200:
            return []
        content = resp.content
        if len(content) < 200:
            return []
    except Exception:
        return []

    try:
        feed = feedparser.parse(content)
    except Exception:
        return []

    articles = []
    for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
        pub_date = _parse_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        title   = _clean_html(getattr(entry, "title",   "") or "")
        summary = _clean_html(getattr(entry, "summary", "") or "")
        link    = getattr(entry, "link", "") or ""

        if not title or not link:
            continue

        articles.append({
            "category":  category,
            "source":    source,
            "title":     title,
            "url":       link,
            "summary":   summary[:400],
            "published": pub_date.isoformat() if pub_date else None,
        })

    return articles


def fetch_gnews(queries: list[str], api_key: str) -> list[dict]:
    articles = []
    seen     = set()
    cutoff   = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

    for query in queries[:5]:
        try:
            resp = requests.get(
                "https://gnews.io/api/v4/search",
                params={"q": query, "token": api_key, "lang": "en", "max": 5, "sortby": "publishedAt"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            for art in resp.json().get("articles", []):
                url = art.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                try:
                    pub = datetime.fromisoformat(art.get("publishedAt","").replace("Z","+00:00"))
                except Exception:
                    pub = None
                if pub and pub < cutoff:
                    continue
                articles.append({
                    "category":  "remote_sensing",
                    "source":    art.get("source",{}).get("name","GNews"),
                    "title":     art.get("title",""),
                    "url":       url,
                    "summary":   art.get("description","")[:400],
                    "published": pub.isoformat() if pub else None,
                })
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"  [GNEWS] {query[:30]}: {e}")

    return articles


# ── Format for newsletter ─────────────────────────────────────────────
CATEGORY_ORDER = [
    ("remote_sensing",     "REMOTE SENSING SCIENCE & APPLICATIONS"),
    ("agriculture",        "AGRICULTURE & PRECISION FARMING"),
    ("flooding",           "FLOOD MONITORING & MAPPING"),
    ("freshwater",         "FRESHWATER AVAILABILITY & AQUIFERS"),
    ("drought",            "DROUGHT MONITORING"),
    ("wildfire",           "WILDFIRE DETECTION & RESPONSE"),
    ("invasive_species",   "INVASIVE SPECIES DETECTION"),
    ("pesticide_herbicide","PESTICIDE & HERBICIDE WATCH"),
]


def format_news_for_prompt(articles: list[dict], max_per_cat: int = 5) -> str:
    if not articles:
        return "NO_ARTICLES_RETRIEVED"

    by_cat: dict[str, list] = {}
    for a in articles:
        by_cat.setdefault(a.get("category","other"), []).append(a)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x.get("published") or "", reverse=True)

    lines = [f"TOTAL ARTICLES THIS WEEK: {len(articles)}", ""]
    for cat, label in CATEGORY_ORDER:
        arts = by_cat.get(cat, [])[:max_per_cat]
        if not arts:
            lines.append(f"### {label}\nSTATUS: No articles this week\n")
            continue
        lines.append(f"### {label} ({len(arts)} articles)")
        for i, a in enumerate(arts, 1):
            pub = (a.get("published") or "")[:10] or "this week"
            lines.append(
                f"{i}. TITLE: {a['title']}\n"
                f"   SOURCE: {a['source']} | DATE: {pub}\n"
                f"   URL: {a['url']}\n"
                f"   SUMMARY: {a['summary']}"
            )
        lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────
def run() -> dict:
    today    = datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")
    print(f"\n[RS NEWS] {date_str}\n")

    all_articles: list[dict] = []
    seen_urls: set[str]      = set()

    def add(arts: list[dict]):
        for a in arts:
            if a.get("url") and a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                all_articles.append(a)

    # Tier 1: Google News (primary)
    print("  [T1  ] Google News RSS feeds...")
    for cat, source, url in GOOGLE_NEWS_FEEDS:
        arts = parse_feed(cat, source, url)
        add(arts)
        if arts:
            print(f"  [OK  ] {source}: {len(arts)} articles")
        time.sleep(REQUEST_DELAY)

    # Tier 2: Specialist feeds
    print(f"\n  [T2  ] Specialist RSS feeds...")
    for cat, source, url in SPECIALIST_FEEDS:
        arts = parse_feed(cat, source, url)
        add(arts)
        if arts:
            print(f"  [OK  ] {source}: {len(arts)} articles")
        time.sleep(REQUEST_DELAY * 0.5)

    # Tier 3: GNews API
    gnews_key = os.getenv("GNEWS_API_KEY", "")
    if gnews_key:
        print(f"\n  [T3  ] GNews API...")
        add(fetch_gnews(GNEWS_QUERIES, gnews_key))

    output = {
        "fetchedAt":    today.isoformat(),
        "date":         date_str,
        "articleCount": len(all_articles),
        "articles":     all_articles,
    }

    (RS_NEWS_DIR / "latest.json").write_text(json.dumps(output, indent=2))
    (RS_NEWS_DIR / f"{date_str}.json").write_text(json.dumps(output, indent=2))

    print(f"\n[RS NEWS] {len(all_articles)} articles → {RS_NEWS_DIR}/latest.json\n")
    return output


if __name__ == "__main__":
    run()
