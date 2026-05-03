"""
QuantAgri — Remote Sensing Intelligence Digest
===============================================
Weekly roundup of remote sensing news covering:
  agriculture, flooding, freshwater & aquifers, drought,
  wildfires, invasive species, pesticide/herbicide drift.

Anti-hallucination: LLM only references articles in source data.
Hyperlinks: article URLs passed as source material and embedded in output.
Tone: accessible, informative, practitioner-focused — not overly technical.

Output:
    data/rs_newsletter/latest.md
    data/rs_newsletter/{YYYY-MM-DD}.md

Schedule: Friday 22:00 UTC (cron: '0 22 * * 5')
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR
from ollama_client import chat
from fetch_rs_news import RS_NEWS_DIR, format_news_for_prompt

RS_NEWS_NL_DIR = DATA_DIR / "rs_newsletter"
RS_NEWS_NL_DIR.mkdir(parents=True, exist_ok=True)

MAX_ARTICLES_PER_SECTION = 5   # cap per section so digest stays readable


def load_latest_news() -> dict:
    path = RS_NEWS_DIR / "latest.json"
    if not path.exists():
        print("  [WARN] No RS news data — run fetch_rs_news.py first")
        return {"articles": [], "date": "unknown", "articleCount": 0}
    return json.loads(path.read_text())


def group_articles_by_category(articles: list[dict]) -> dict[str, list]:
    """Group articles by category, sorted newest-first within each group."""
    by_cat: dict[str, list] = {}
    for a in articles:
        by_cat.setdefault(a.get("category", "other"), []).append(a)
    # Sort each group newest-first
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x.get("published") or "", reverse=True)
    return by_cat


def format_articles_for_prompt(articles: list[dict], max_per_cat: int = MAX_ARTICLES_PER_SECTION) -> str:
    """
    Build a structured article list for LLM injection.
    Includes full URL for each article so LLM can embed hyperlinks.
    """
    if not articles:
        return "NO ARTICLES RETRIEVED THIS WEEK."

    category_order = [
        ("remote_sensing",     "REMOTE SENSING SCIENCE & APPLICATIONS"),
        ("agriculture",        "AGRICULTURE & PRECISION FARMING"),
        ("flooding",           "FLOOD MONITORING & MAPPING"),
        ("freshwater",         "FRESHWATER AVAILABILITY & AQUIFERS"),
        ("drought",            "DROUGHT MONITORING"),
        ("wildfire",           "WILDFIRE DETECTION & RESPONSE"),
        ("invasive_species",   "INVASIVE SPECIES DETECTION"),
        ("pesticide_herbicide","PESTICIDE, HERBICIDE & CROP PROTECTION"),
        ("gnews",              "ADDITIONAL EARTH OBSERVATION NEWS"),
    ]

    by_cat = group_articles_by_category(articles)
    lines  = [f"TOTAL ARTICLES: {len(articles)}", ""]

    for cat, label in category_order:
        arts = by_cat.get(cat, [])[:max_per_cat]
        if not arts:
            lines.append(f"### {label}\n[No articles this week]\n")
            continue
        lines.append(f"### {label}")
        for i, a in enumerate(arts, 1):
            pub  = (a.get("published") or "")[:10] or "recent"
            lines.append(
                f"{i}. TITLE: {a.get('title','(no title)')}\n"
                f"   SOURCE: {a.get('source','unknown')} | DATE: {pub}\n"
                f"   URL: {a.get('url','')}\n"
                f"   SUMMARY: {a.get('summary','')[:300]}"
            )
        lines.append("")

    return "\n".join(lines)


def build_rs_newsletter_prompt(today_str: str, formatted_articles: str, article_count: int) -> str:
    return f"""You are the editor of the "QuantAgri Remote Sensing Intelligence Digest",
a weekly newsletter read by GIS professionals, environmental scientists, precision
agriculture practitioners, water resource managers, and policy researchers.

Today is {today_str}. You have {article_count} source articles below.

═══════════════════════════════════════════════════════════════
ANTI-HALLUCINATION RULES — THESE ARE ABSOLUTE AND NON-NEGOTIABLE
═══════════════════════════════════════════════════════════════
1. ONLY reference articles that appear in the SOURCE ARTICLES section below.
   Do NOT invent, fabricate, or imagine articles that are not listed.
2. If a section has [No articles this week], write 1-2 sentences noting
   limited coverage — do NOT invent stories for that section.
3. Every claim must trace back to a specific article in the source list.
4. HYPERLINKS: For every article you reference, embed the URL as a Markdown
   hyperlink in the text: [Article Title](URL). Use the exact URL from the source.
5. If an article URL is missing or blank, cite as: Source Name (date) — no link.
6. Do NOT add links to external sites that are not in the source articles.
   Exception: you may link to well-known government/agency homepages
   (nasa.gov, usgs.gov, esa.int, epa.gov) as context, but not as article citations.
═══════════════════════════════════════════════════════════════

TONE AND STYLE RULES:
- Write for an educated but mixed audience — avoid unexplained jargon
- When technical terms are necessary, briefly explain them in plain language
  e.g. "NDVI (a satellite measure of vegetation health)"
- Active voice, clear sentences, 15-25 words per sentence target
- Each section should feel like a knowledgeable colleague briefing you,
  not an academic abstract or a press release
- Accessible but credible — think "The Economist" science section,
  not a journal article and not a tabloid

LENGTH: 800-1,000 words total. Quality over quantity — shorter and accurate
beats longer and speculative.

FORMAT: Standard Markdown. Use ## headers, **bold** for key terms on first use,
and [text](url) for all hyperlinks.

═══════════════════════════════════════════════════════════════
SOURCE ARTICLES (these are the ONLY articles you may reference)
═══════════════════════════════════════════════════════════════
{formatted_articles}
═══════════════════════════════════════════════════════════════

Write the newsletter now using ONLY the source articles above:

# QuantAgri Remote Sensing Intelligence Digest
## {today_str}
*Weekly earth observation news for agriculture, water, hazards, and environmental monitoring*

---

**THIS WEEK:** [1-2 sentences only — the single most important story from the source
articles above. Must cite a real article with a hyperlink.]

---

## 🛰 Remote Sensing: What's New
[2-3 paragraphs. Reference only articles in the Remote Sensing or GNews categories above.
Each article referenced must have a hyperlink. If no articles, say so briefly.]

## 🌾 Agriculture & Crop Monitoring
[Satellite crop monitoring, yield mapping, soil moisture, precision ag.
Reference only articles in the Agriculture category. Hyperlink every article cited.
Explain any technical terms briefly. If no articles, say so.]

## 🌊 Flood & Water Hazards
[SAR flood mapping, real-time flood alerts, post-event damage mapping.
Reference only articles in the Flooding category. Hyperlink every article cited.]

## 💧 Freshwater & Groundwater
[Aquifer depletion tracked by GRACE satellites (gravity-based groundwater monitoring),
river flow, reservoir levels, transboundary water stress.
Reference only articles in the Freshwater category. Hyperlink every article cited.
If no articles this week, briefly note which GRACE data products practitioners should check.]

## 🏜 Drought Watch
[Satellite drought indices, soil moisture anomalies, agricultural drought impacts.
Reference only Drought category articles. Hyperlink every article cited.]

## 🔥 Wildfire & Forest Monitoring
[Active fire detection via VIIRS/MODIS, burn severity, smoke, post-fire recovery.
Reference only Wildfire category articles. Hyperlink every article cited.]

## 🌿 Invasive Species & Land Cover
[Satellite detection of invasive plants, habitat change, aquatic invasives.
Reference only Invasive Species articles. Hyperlink every article cited.]

## 🧪 Pesticide & Herbicide Watch
[Drift events, application monitoring, regulatory updates.
Reference only Pesticide/Herbicide articles. Hyperlink every article cited.
If no articles, one sentence noting limited coverage is fine.]

## 📌 Quick Picks
[2-3 short bullets — additional noteworthy items from any category not already covered.
Each must be a real article from the source list with a hyperlink.]

---
*QuantAgri Remote Sensing Intelligence Digest · {today_str}*
*Compiled from: NASA Earth Observatory · ESA Copernicus · USGS · NASA GRACE/JPL*
*Circle of Blue · UN Water · FloodList · InciWeb · NIFC · USDA APHIS*
*EPA · MDPI Remote Sensing · AgFunder · GIS Geography · and additional RSS feeds*
*Articles sourced automatically from public RSS feeds.*
*[View past issues on GitHub](https://github.com/rmkenv/quantagri/tree/main/data/rs_newsletter)*
"""


def run():
    today     = datetime.now(timezone.utc)
    today_str = today.strftime("%B %d, %Y")
    date_str  = today.strftime("%Y-%m-%d")

    print(f"\n[RS NEWSLETTER] {today_str}\n")

    news_data     = load_latest_news()
    articles      = news_data.get("articles", [])
    article_count = len(articles)

    print(f"  [DATA] {article_count} articles from {news_data.get('date','?')}")

    if article_count == 0:
        print("  [WARN] No articles retrieved — digest will note limited coverage")

    formatted = format_articles_for_prompt(articles)
    prompt    = build_rs_newsletter_prompt(today_str, formatted, article_count)

    print(f"  [LLM ] {len(prompt):,} chars — calling Ollama Cloud...")
    markdown = chat(prompt, as_json=False, temperature=0.3)

    # Post-process: verify no fabricated links slipped through
    # (basic check — flag any URLs in output not present in source articles)
    source_urls = {a.get("url","") for a in articles if a.get("url")}
    import re
    output_urls = set(re.findall(r'\]\((https?://[^\)]+)\)', markdown))
    allowed_domains = {"nasa.gov","usgs.gov","esa.int","epa.gov","noaa.gov",
                       "github.com","copernicus.eu","un.org","unwater.org"}
    suspicious = []
    for url in output_urls:
        in_sources = url in source_urls
        from_allowed = any(d in url for d in allowed_domains)
        if not in_sources and not from_allowed:
            suspicious.append(url)

    if suspicious:
        print(f"  [WARN] {len(suspicious)} output URLs not in source articles — review:")
        for u in suspicious[:5]:
            print(f"         {u}")

    (RS_NEWS_NL_DIR / f"{date_str}.md").write_text(markdown)
    (RS_NEWS_NL_DIR / "latest.md").write_text(markdown)

    print(f"  [OUT ] {RS_NEWS_NL_DIR}/latest.md ({len(markdown):,} chars)")
    print(f"\n[RS NEWSLETTER] Done\n")


if __name__ == "__main__":
    run()
