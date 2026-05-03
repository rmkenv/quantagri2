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
• Do NOT add generic tips, how-to advice, or filler text.
• If a section has no articles: write ONE sentence: "Nothing notable this week."
• Every article referenced MUST include its URL as a Markdown hyperlink
  embedded naturally in the prose: e.g. "...as [ESA reports](URL)."
  NOT as a standalone line after the paragraph.
• Do NOT link to any URL not in the source list (allowed exceptions:
  nasa.gov, usgs.gov, esa.int, noaa.gov homepages only).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO WRITE — READ THIS CAREFULLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are a journalist, not a summariser. The goal is not to list articles.
It is to give readers something they could not get by skimming headlines.

FOR EVERY SECTION WITH ARTICLES:

1. FIND THE ANGLE. What is the real story? What do these articles have in common?
   What does this week's news mean for someone who farms, manages water, fights
   fires, or makes lending decisions?

2. WRITE A NARRATIVE PARAGRAPH (3-5 sentences minimum per section).
   — Start with the most important INSIGHT, not the most important headline.
   — Connect multiple articles where there is a thread: if two water stories
     both point to Colorado River stress, say that explicitly.
   — Embed hyperlinks naturally mid-sentence:
     "ESA's [completion of the Sentinel-1 constellation](URL) this week
     means flood responders can now get updated radar imagery every 6 days
     instead of 12, a step-change for real-time disaster response."
   — Explain what each development means in practical terms for the reader.

3. TECHNICAL TERMS: explain briefly on first use, naturally in the sentence.
   — "NDVI (a satellite index tracking how green and healthy crops look)"
   — "SAR radar, which penetrates cloud cover that blocks optical satellites"
   — "GRACE satellites, which measure groundwater by detecting tiny shifts
      in Earth's gravitational pull"
   One brief clause is enough. Do not over-explain.

4. SO WHAT: End each active section with one sentence on practical implication.
   Who should care? What should they do differently because of this?

WHAT NOT TO DO:
X Do not write "Headline. One sentence summary. [Link]" — that is a list, not journalism.
X Do not open a section by copying an article title as your first sentence.
X Do not write "This article discusses..." or "According to the source..."
X Do not use bullet points to list article summaries.
X Do not pad sections with background that is not in the source articles.

TONE: Think "The Economist" science section — technically credible, fully readable
by a non-expert. Smart, direct, specific. Like a colleague who read everything
so you do not have to.

LENGTH: 800-1,000 words total. A tight 700 beats a padded 1,200.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE ARTICLES — ONLY THESE MAY BE REFERENCED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{formatted_articles}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WRITE THE DIGEST — USE ONLY SOURCE ARTICLES ABOVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# QuantAgri Remote Sensing Intelligence Digest
## {today_str}
*Earth observation news for agriculture, water, hazards, and environmental monitoring*

---

**This week's lead:** [2-3 sentences. Find the single most significant development
and explain why it matters practically. Hyperlink the key article naturally
mid-sentence — not as a standalone link. Give the reader a reason to keep reading.]

---

## 🛰 Remote Sensing

[Write 3-5 sentences of journalism. Find the common thread across articles.
What does this week's development mean for practitioners on the ground?
Hyperlinks embedded naturally in prose. If none: "Nothing notable this week."]

## 🌾 Agriculture & Crop Monitoring

[Write 3-5 sentences. What does this week's ag news mean for farmers, lenders,
or precision ag practitioners? Connect stories if there is a thread.
Translate satellite terms into field implications. Hyperlinks in prose.
If none: "Nothing notable this week."]

## 🌊 Flood & Water Hazards

[Write 3-5 sentences on flood monitoring and practical implications.
Explain SAR briefly if used. Hyperlinks in prose.
If none: "Nothing notable this week."]

## 💧 Freshwater & Groundwater

[Write 3-5 sentences. Water scarcity, aquifer stress, policy — what is the real
story and who should be paying attention?
Explain GRACE briefly if used: "GRACE satellites detect groundwater change by
measuring tiny shifts in Earth's gravitational pull."
Hyperlinks in prose. If none: "Nothing notable this week."]

## 🏜 Drought Watch

[3-5 sentences of journalism, or "Nothing notable this week."]

## 🔥 Wildfire & Forest Monitoring

[3-5 sentences of journalism, or "Nothing notable this week."]

## 🌿 Invasive Species

[3-5 sentences of journalism, or "Nothing notable this week."]

## 🧪 Pesticide & Herbicide

[3-5 sentences. What is the practical takeaway for crop protection decisions?
Hyperlinks in prose. If none: "Nothing notable this week."]

---
*QuantAgri Remote Sensing Intelligence Digest · {today_str}*
*Sources: Google News · NASA Earth Observatory · ESA Copernicus · USGS*
*FloodList · Circle of Blue · USDA APHIS · EPA · AgFunder · CropLife · and RSS feeds*
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
