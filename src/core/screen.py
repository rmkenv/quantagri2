"""
core/screen.py — shared Ollama Cloud LLM relevance screener.
Each wire passes its own system prompt / criteria.

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import time
import logging
import requests
from typing import List, Optional

logger = logging.getLogger(__name__)

OLLAMA_API_URL = "https://api.ollama.com/api/chat"
DEFAULT_MODEL = "gpt-oss:20b"


def _call_ollama(
    article: dict,
    system_prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> bool:
    """
    Returns True if the article passes relevance screening.
    Falls back to True (keep) on API errors so we don't silently drop articles.
    """
    user_msg = (
        "Title: {}\nSnippet: {}\nURL: {}\n\n"
        "Respond with exactly one word: YES or NO."
    ).format(
        article.get("title", ""),
        article.get("snippet", ""),
        article.get("url", ""),
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ],
        "stream": False,
    }
    headers = {"Authorization": "Bearer {}".format(api_key), "Content-Type": "application/json"}
    try:
        r = requests.post(OLLAMA_API_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        answer = r.json()["message"]["content"].strip().upper()
        logger.debug("Ollama → %s | %s", answer, article.get("title", "")[:60])
        return answer.startswith("YES")
    except requests.exceptions.HTTPError as e:
        logger.warning("Ollama HTTP %s — keeping article: %s",
                       e.response.status_code if e.response else "?", e)
        return True
    except requests.exceptions.Timeout:
        logger.warning("Ollama timeout — keeping article: %s", article.get("title", "")[:60])
        return True
    except KeyError:
        logger.warning("Ollama unexpected response shape — keeping article")
        return True
    except Exception as e:
        logger.warning("Ollama error (keeping article): %s", e)
        return True


def screen_articles(
    articles: List[dict],
    system_prompt: str,
    api_key: Optional[str],
    model: str = DEFAULT_MODEL,
    rate_limit_sec: float = 0.5,
) -> List[dict]:
    """
    Filter articles through the LLM. If api_key is None, screening is skipped.
    """
    if not articles:
        return articles

    wire = articles[0].get("wire", "unknown")

    if not api_key:
        logger.warning("[%s] OLLAMA_API_KEY not set — skipping LLM screening", wire)
        return articles

    passed = []
    for a in articles:
        keep = _call_ollama(a, system_prompt, api_key, model)
        if keep:
            passed.append(a)
        time.sleep(rate_limit_sec)

    logger.info("[%s] screened %d → %d passed", wire, len(articles), len(passed))
    return passed
