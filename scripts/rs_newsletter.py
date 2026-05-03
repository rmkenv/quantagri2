"""
QuantAgri — Remote Sensing Intelligence Digest
===============================================
Weekly roundup. Primary news source: Google News RSS (always fresh).
Supplemented by specialist feeds and optional GNews API.

Anti-hallucination: strict source-only rule with URL post-processing check.
Fallback: if fewer than 3 articles retrieved, postpones and logs warning.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR
from ollama_client import chat
from fetch_rs_news import RS_NEWS_DIR, format_news_for_prompt, CATEGORY_ORDER

RS_NEWS_NL_DIR = DATA_DIR / "rs_newsletter"
RS_NEWS_NL_DIR.mkdir(parents=True, exist_ok=True)

MIN_ARTICLES_TO_PUBLISH = 3   # skip if feed returned too little


def load_latest_news() -> dict:
    path = RS_NEWS_DIR / "latest.json"
    if not path.exists():
        print("  [WARN] No RS news — run fetch_rs_news.py first")
        return {"articles": [], "date": "unknown", "articleCount": 0}
    return json.loads(path.read_text())


def format_articles_for_prompt(articles: list[dict], max_per_cat: int = 5) -> str:
    """
    Structured article list for LLM. Each entry includes:
    title, source, date, URL, and summary snippet.
    URLs are passed explicitly so the LLM can embed them as hyperlinks.
    """
    if not articles:
        return "NO_ARTICLES_RETRIEVED"

    by_cat: dict[str, list] = {}
    for a in articles:
        by_cat.setdefault(a.get("category", "other"), []).append(a)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x.get("published") or "", reverse=True)

    lines = [f"TOTAL ARTICLES: {len(articles)}", ""]
    for cat, label in CATEGORY_ORDER:
        arts = by_cat.get(cat, [])[:max_per_cat]
        status = f"{len(arts)} articles" if arts else "NONE THIS WEEK"
        lines.append(f"### {label} [{status}]")
        if not arts:
            lines.append("(skip this section or write one honest sentence)\n")
            continue
        for i, a in enumerate(arts, 1):
            pub = (a.get("published") or "")[:10] or "this week"
            lines.append(
                f"{i}. TITLE: {a['title']}\n"
                f"   SOURCE: {a['source']} | DATE: {pub}\n"
                f"   URL: {a['url']}\n"
                f"   SUMMARY: {a['summary'][:350]}"
            )
        lines.append("")

    return "\n".join(lines)


def build_rs_newsletter_prompt(today_str: str, formatted_articles: str, article_count: int) -> str:
    return f"""You are the editor of the QuantAgri Remote Sensing Intelligence Digest.
Today is {today_str}. You retrieved {article_count} articles from RSS feeds this week.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES — READ BEFORE WRITING ANYTHING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ANTI-HALLUCINATION (absolute):
• Only reference articles listed in SOURCE ARTICLES below.
• Do NOT invent stories, agencies, studies, or events not in the source list.
• Do NOT add generic "tips", "how-to" advice, or agency descriptions as filler.
• If a section says [NONE THIS WEEK] → write exactly ONE sentence:
  "No new articles this week." — then move on. Do NOT pad it out.
• Every article you reference MUST include its URL as a Markdown hyperlink:
  [Article Title](URL) — use the exact URL from the source list.
• Do NOT link to any URL not present in the source list (except the four
  allowed agency homepages: nasa.gov, usgs.gov, esa.int, noaa.gov).

TONE:
• Audience: GIS professionals, ag lenders, farm managers, water resource
  managers, environmental scientists. Educated but mixed backgrounds.
• Write like a sharp colleague briefing you over coffee — direct, specific,
  no jargon without a brief explanation, no filler.
• When using technical terms, briefly explain on first use only:
  e.g. "NDVI (a satellite measure of vegetation health)"
  e.g. "SAR (radar that sees through cloud cover)"
  e.g. "GRACE (gravity satellites that measure groundwater change)"
• Active voice. Short sentences. Drop anything that adds no information.
• Target: 600–900 words total. Tight is better than long.

FORMAT:
• Standard Markdown. ## for section headers. **bold** for key terms.
• [text](url) for ALL article hyperlinks.
• No bullet points for filler — only use bullets for genuine lists of items.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE ARTICLES — ONLY THESE MAY BE REFERENCED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{formatted_articles}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WRITE THE DIGEST BELOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# QuantAgri Remote Sensing Intelligence Digest
## {today_str}
*Earth observation news for agriculture, water, hazards, and environmental monitoring*

---

**This week:** [One sentence — the most important story from the articles above.
Must cite a real article with a hyperlink. If zero articles: "A quiet week
in the feeds — the top items from recent issues are linked in the archive."]

---

## 🛰 Remote Sensing
[Summarise only articles tagged Remote Sensing above. Hyperlink each one.
If none: "No new articles this week."]

## 🌾 Agriculture & Crop Monitoring
[Summarise only Agriculture articles. Hyperlink each one.
Explain NDVI/EVI briefly if used. If none: "No new articles this week."]

## 🌊 Flood & Water Hazards
[Summarise only Flooding articles. Hyperlink each. Explain SAR briefly if used.
If none: "No new articles this week."]

## 💧 Freshwater & Groundwater
[Summarise only Freshwater articles. Hyperlink each.
Explain GRACE briefly if used: "GRACE satellites detect groundwater changes
by measuring tiny shifts in Earth's gravity field."
If none: "No new articles this week."]

## 🏜 Drought Watch
[Summarise only Drought articles. Hyperlink each. If none: one sentence.]

## 🔥 Wildfire & Forest Monitoring
[Summarise only Wildfire articles. Hyperlink each. If none: one sentence.]

## 🌿 Invasive Species
[Summarise only Invasive Species articles. Hyperlink each. If none: one sentence.]

## 🧪 Pesticide & Herbicide
[Summarise only Pesticide articles. Hyperlink each. If none: one sentence.]

---
*QuantAgri Remote Sensing Intelligence Digest · {today_str}*
*Sources: Google News · NASA Earth Observatory · ESA Copernicus · USGS*
*FloodList · InciWeb · Circle of Blue · USDA APHIS · EPA · and RSS feeds*
*[Past issues](https://github.com/rmkenv/quantagri/tree/main/data/rs_newsletter)*
"""


def check_for_fabricated_urls(markdown: str, source_articles: list[dict]) -> list[str]:
    """Return list of URLs in output that weren't in the source articles."""
    source_urls  = {a.get("url", "") for a in source_articles}
    allowed_domains = {"nasa.gov", "usgs.gov", "esa.int", "noaa.gov", "github.com"}
    output_urls  = set(re.findall(r'\]\((https?://[^\)]+)\)', markdown))
    return [
        u for u in output_urls
        if u not in source_urls and not any(d in u for d in allowed_domains)
    ]


def run():
    today     = datetime.now(timezone.utc)
    today_str = today.strftime("%B %d, %Y")
    date_str  = today.strftime("%Y-%m-%d")

    print(f"\n[RS NEWSLETTER] {today_str}\n")

    news_data = load_latest_news()
    articles  = news_data.get("articles", [])
    count     = len(articles)

    print(f"  [DATA] {count} articles from {news_data.get('date','?')}")

    if count < MIN_ARTICLES_TO_PUBLISH:
        msg = (
            f"Only {count} articles retrieved — below minimum of "
            f"{MIN_ARTICLES_TO_PUBLISH}. Check that fetch_rs_news.py ran "
            f"successfully and that GitHub Actions has internet access."
        )
        print(f"  [WARN] {msg}")
        # Write a minimal placeholder rather than a hallucinated digest
        placeholder = (
            f"# QuantAgri Remote Sensing Intelligence Digest\n"
            f"## {today_str}\n\n"
            f"*Feed retrieval returned {count} articles this week — "
            f"below the minimum threshold for a full digest. "
            f"Check the pipeline logs and retry.*\n"
        )
        (RS_NEWS_NL_DIR / f"{date_str}.md").write_text(placeholder)
        (RS_NEWS_NL_DIR / "latest.md").write_text(placeholder)
        print(f"  [OUT ] Placeholder written — no LLM call made")
        return

    formatted = format_articles_for_prompt(articles)
    prompt    = build_rs_newsletter_prompt(today_str, formatted, count)

    print(f"  [LLM ] {len(prompt):,} chars — calling Ollama Cloud...")
    markdown = chat(prompt, as_json=False, temperature=0.25)

    # Post-process: flag any fabricated URLs
    bad_urls = check_for_fabricated_urls(markdown, articles)
    if bad_urls:
        print(f"  [WARN] {len(bad_urls)} fabricated URL(s) detected — review output:")
        for u in bad_urls[:5]:
            print(f"         {u}")

    (RS_NEWS_NL_DIR / f"{date_str}.md").write_text(markdown)
    (RS_NEWS_NL_DIR / "latest.md").write_text(markdown)

    print(f"  [OUT ] {RS_NEWS_NL_DIR}/latest.md ({len(markdown):,} chars)")
    if bad_urls:
        print(f"  [WARN] Review output for {len(bad_urls)} unverified URL(s)")
    print(f"\n[RS NEWSLETTER] Done\n")


if __name__ == "__main__":
    run()
