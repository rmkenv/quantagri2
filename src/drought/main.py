"""
drought/main.py — Drought Wire orchestrator.

2 SerpAPI queries/day (60/month) — within free-tier budget across all 4 wires.
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core import extract, screen, geocode, load, utils
from drought.sensor_join import join_sensor

logger = logging.getLogger(__name__)

WIRE = "drought"

# 1 query/day = 30 SerpAPI calls/month across all 4 wires
QUERIES = [
    '"drought emergency" OR "drought declaration" OR "exceptional drought" OR "water shortage" OR "reservoir low" United States',
]

EXCLUSION_PATTERNS = [
    r"\bdrought of talent\b",
    r"\bdrought of ideas\b",
    r"\bscoring drought\b",
    r"\bwinless drought\b",
    r"\bgoal drought\b",
    r"\boffensive drought\b",
]

SYSTEM_PROMPT = (
    "You are a relevance screener for a drought news wire. "
    "Answer YES if the article describes a real drought event, drought emergency declaration, water shortage, "
    "reservoir depletion, groundwater decline, or crop loss due to drought in the United States. "
    "Answer NO if it is about sports, figurative uses of 'drought', or events outside the US. "
    "Respond with exactly one word: YES or NO."
)

CLASSIFICATION_MAP = {
    "drought_declaration": ["drought declaration", "drought emergency", "drought disaster"],
    "water_shortage":      ["water shortage", "water restriction", "water ban", "water rationing"],
    "reservoir_low":       ["reservoir", "lake level", "water level", "storage capacity"],
    "crop_loss":           ["crop loss", "crop failure", "agricultural drought", "livestock"],
    "exceptional_drought": ["exceptional drought", "D4", "extreme drought", "D3"],
}


def classify(article):
    text = "{} {}".format(article.get("title", ""), article.get("snippet", "")).lower()
    for event_type, triggers in CLASSIFICATION_MAP.items():
        if any(t in text for t in triggers):
            return event_type
    return "drought_event"


def run(cfg, test_mode=False, no_screen=False, lookback_override=None):
    api = cfg.get("api", {})
    geo = cfg.get("geocoding", {})
    etl = cfg.get("etl", {})

    serpapi_key = api.get("serpapi_key")
    ollama_key  = api.get("ollama_api_key")
    user_agent  = api.get("user_agent", "climatewire/1.0")
    lookback    = lookback_override or etl.get("lookback_days", 1)
    data_dir    = etl.get("data_dir", "data")
    rate_nom    = geo.get("rate_limit_sec", 1.0)
    timeout     = geo.get("timeout_sec", 10.0)
    screen_rate = cfg.get("screening", {}).get("rate_limit_sec", 0.5)

    if not serpapi_key:
        logger.error("SERPAPI_KEY not set — aborting")
        return

    logger.debug("[%s] starting run — lookback=%s days, test=%s, screen=%s",
                 WIRE, lookback, test_mode, not no_screen)

    articles = extract.fetch_articles(
        queries=QUERIES,
        api_key=serpapi_key,
        wire=WIRE,
        lookback_days=lookback,
        exclusion_patterns=EXCLUSION_PATTERNS,
    )
    logger.debug("[%s] after fetch+exclusions: %d articles", WIRE, len(articles))

    if test_mode:
        articles = articles[:10]

    if not no_screen:
        articles = screen.screen_articles(
            articles, SYSTEM_PROMPT, ollama_key, rate_limit_sec=screen_rate
        )
    logger.debug("[%s] after screening: %d articles", WIRE, len(articles))

    articles = geocode.geocode_articles(articles, user_agent, rate_nom, timeout)
    logger.debug("[%s] after geocoding: %d rows", WIRE, len(articles))

    for a in articles:
        a["event_type"] = classify(a)

    articles = join_sensor(articles)
    logger.debug("[%s] after sensor join: %d rows", WIRE, len(articles))

    if not test_mode:
        new, total = load.write_outputs(articles, WIRE, data_dir)
        logger.info("[%s] done — %d new rows, %d total", WIRE, new, total)
    else:
        logger.info("[%s] test mode — would write %d rows", WIRE, len(articles))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drought Wire")
    parser.add_argument("--config", default=None)
    parser.add_argument("--test", action="store_true", help="10 articles, no file writes")
    parser.add_argument("--no-screen", action="store_true", help="skip Ollama LLM screening")
    parser.add_argument("--debug", action="store_true", help="set log level to DEBUG")
    parser.add_argument("--lookback", type=int, default=None,
                        help="override lookback_days from config")
    args = parser.parse_args()

    cfg = utils.load_config(args.config)
    level = "DEBUG" if args.debug else cfg.get("etl", {}).get("log_level", "INFO")
    utils.setup_logging(level)
    run(cfg, test_mode=args.test, no_screen=args.no_screen, lookback_override=args.lookback)
